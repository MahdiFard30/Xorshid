"""Temporarily lower other PulseAudio/PipeWire playback streams during speech.

Mixer I/O runs on one worker, never in PortAudio callbacks. Original channel
levels are restored unless the stream disappeared or the user changed them.
"""
from __future__ import annotations

import atexit
from contextlib import contextmanager
import json
import logging
import os
import shutil
import subprocess
import threading

log = logging.getLogger(__name__)


class PulseBackend:
    def __init__(self):
        self.command = shutil.which('pactl')

    def streams(self):
        if not self.command:
            return []
        result = subprocess.run([self.command, '--format=json', 'list', 'sink-inputs'],
                                capture_output=True, text=True, timeout=.7, check=True)
        return json.loads(result.stdout)

    def volume(self, index, values):
        subprocess.run([self.command, 'set-sink-input-volume', str(index),
                        *(str(v) for v in values)],
                       capture_output=True, timeout=.7, check=True)


def _levels(stream):
    return tuple(channel['value'] for channel in stream.get('volume', {}).values())


def _identity(stream):
    props = stream.get('properties', {})
    return (stream.get('client'), stream.get('channel_map'),
            props.get('application.process.id'), props.get('application.process.binary'),
            props.get('application.name'))


class StreamDucker:
    """Stateful mixer operations; also usable with an isolated/fake backend."""
    def __init__(self, backend, factor=.12):
        self.backend, self.factor = backend, factor
        self.saved = {}

    def refresh(self):
        streams = self.backend.streams()
        live = {s['index'] for s in streams}
        for index in self.saved.keys() - live:
            del self.saved[index]
        for stream in streams:
            index, identity, levels = stream['index'], _identity(stream), _levels(stream)
            props = stream.get('properties', {})
            if (not levels or str(props.get('application.process.id')) == str(os.getpid())
                    or props.get('khorshid.voice') == '1'
                    or props.get('application.name') == 'Khorshid'):
                continue
            previous = self.saved.get(index)
            if previous and previous[0] == identity:
                # A manual adjustment takes precedence until speech ends.
                continue
            applied = tuple(round(v * self.factor) for v in levels)
            self.backend.volume(index, applied)
            self.saved[index] = (identity, levels, applied)

    def restore(self):
        streams = {s['index']: s for s in self.backend.streams()}
        for index, (identity, original, applied) in list(self.saved.items()):
            stream = streams.get(index)
            if stream and _identity(stream) == identity and _levels(stream) == applied:
                try:
                    self.backend.volume(index, original)
                except Exception:
                    log.debug('Could not restore playback stream %s; retrying', index, exc_info=True)
                    continue
            del self.saved[index]


class Lease:
    def __init__(self, service):
        self.service = service
        self.ready = threading.Event()
        self.closed = False

    def close(self, wait=True):
        with self.service.lock:
            if self.closed:
                return
            self.closed = True
            self.service.leases.discard(self)
            last = not self.service.leases
            self.service.wake.set()
        if wait and last:
            self.service.idle.wait(2)


class DuckingService:
    def __init__(self, backend=None):
        self.ducker = StreamDucker(backend if backend is not None else PulseBackend())
        self.lock = threading.Lock()
        self.wake, self.idle = threading.Event(), threading.Event()
        self.idle.set()
        self.leases = set()
        self.thread = None
        self.stopping = False

    def hold(self):
        with self.lock:
            lease = Lease(self)
            if self.stopping:
                lease.ready.set()
                return lease
            self.leases.add(lease)
            self.idle.clear()
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name='speech-ducking', daemon=True)
                self.thread.start()
            self.wake.set()
            return lease

    def _run(self):
        while True:
            self.wake.clear()
            with self.lock:
                leases, stopping = list(self.leases), self.stopping
            try:
                if leases and not stopping:
                    self.ducker.refresh()
                else:
                    self.ducker.restore()
            except Exception:
                log.debug('Audio ducking mixer unavailable', exc_info=True)
            for lease in leases:
                lease.ready.set()
            with self.lock:
                if not leases and not self.leases and not self.ducker.saved:
                    self.idle.set()
            if stopping:
                return
            self.wake.wait(.1 if leases or self.ducker.saved else None)

    def close(self):
        with self.lock:
            self.stopping = True
            self.leases.clear()
            self.wake.set()
            thread = self.thread
        if thread:
            thread.join(timeout=3)


service = DuckingService()
atexit.register(service.close)


@contextmanager
def duck_other_audio():
    lease = service.hold()
    try:
        lease.ready.wait(1)
        yield
    finally:
        lease.close()


def voice_environment():
    """Tag only a voice playback child, never the browser or global environment."""
    return {**os.environ, 'PULSE_PROP_application.name': 'Khorshid',
            'PULSE_PROP_khorshid.voice': '1'}
