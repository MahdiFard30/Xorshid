"""Khorshid TTS session: one continuous PCM stream per reply.

Does not change the TTS model, reference voice, text normalization, agent, or tools.
The original final WAV is still produced by ultimate_khorshid.voice.tts_worker.
"""
import atexit
import json
import logging
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import uuid
import wave
from ultimate_khorshid.core.control import CancelledError, current_controller
from ultimate_khorshid.voice.ducking import duck_other_audio

ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


class SmoothPlayer:
    """One persistent output stream per response; no per-chunk aplay process."""
    def __init__(self, controller=None):
        self.items = queue.Queue()
        self.failure = None
        self.thread = None
        self.sent = 0
        self.waits = 0
        self.wait_seconds = 0.0
        self.first_audio_at = None
        self.started_at = time.monotonic()
        self._closed = False
        self.controller = controller
        self._aborted = threading.Event()

    def cancelled(self):
        return self._aborted.is_set() or (self.controller is not None and self.controller.is_cancelled)

    def _next(self):
        while not self.cancelled():
            try:
                return self.items.get(timeout=.05)
            except queue.Empty:
                pass
        return None

    def start(self):
        self.thread = threading.Thread(target=self._run, name='khorshid-smooth-audio', daemon=True)
        self.thread.start()

    def add(self, path):
        if self.failure:
            raise RuntimeError(f'Audio player failed: {self.failure}')
        self.items.put(str(path))

    def finish(self):
        if not self._closed:
            self._closed = True
            self.items.put(None)
        if self.thread:
            deadline = time.monotonic() + 900
            while self.thread.is_alive():
                if self.cancelled():
                    self.abort()
                    raise CancelledError('پخش پاسخ لغو شد.')
                if time.monotonic() > deadline:
                    self.abort()
                    raise TimeoutError('Continuous audio player did not finish')
                self.thread.join(timeout=.05)
        if self.cancelled():
            raise CancelledError('پخش پاسخ لغو شد.')
        if self.failure:
            raise RuntimeError(f'Continuous audio player failed: {self.failure}')
        logger.debug('[Voice] playback: chunks=%d first_audio=%.2fs waiting_for_next=%d total_wait=%.2fs',
            self.sent,
            (self.first_audio_at - self.started_at) if self.first_audio_at else -1,
            self.waits, self.wait_seconds)

    def abort(self):
        self._closed = True
        self._aborted.set()
        # Do not replay chunks after an error.
        while True:
            try: self.items.get_nowait()
            except queue.Empty: break
        self.items.put(None)

    def _run(self):
        try:
            import sounddevice as sd
            from ultimate_khorshid.interface.sun_bridge import SunBridge
            import numpy as np
            sun = SunBridge()
            try:
                first = self._next()
                if first is None:
                    return
                with wave.open(first, 'rb') as fp:
                    rate, channels, width = fp.getframerate(), fp.getnchannels(), fp.getsampwidth()
                if width != 2:
                    raise ValueError('Expected 16-bit PCM chunks')
                # 16-bit PCM, one PortAudio stream kept open until the complete response.
                device = os.environ.get('KHORSHID_SUN_AUDIO_DEVICE') or None
                if device is not None and device.isdecimal():
                    device = int(device)
                with duck_other_audio(), sd.RawOutputStream(samplerate=rate, channels=channels, dtype='int16',
                                        blocksize=0, latency='high', device=device) as stream:
                    item = first
                    while item is not None and not self.cancelled():
                        with wave.open(item, 'rb') as fp:
                            if (fp.getframerate(), fp.getnchannels(), fp.getsampwidth()) != (rate, channels, width):
                                raise ValueError('Audio chunk sample format changed')
                            while True:
                                if self.cancelled():
                                    break
                                frames = fp.readframes(2048)
                                if not frames: break
                                if self.first_audio_at is None:
                                    self.first_audio_at = time.monotonic()
                                    sun.state('speaking')
                                if self.cancelled():
                                    break
                                stream.write(frames)
                                # These meter updates follow PCM being sent to PortAudio.
                                samples = np.frombuffer(frames, dtype='<i2').astype('float32') / 32768.0
                                sun.level(float(np.sqrt(np.mean(samples * samples))))
                        self.sent += 1
                        requested = time.monotonic()
                        item = self._next()
                        elapsed = time.monotonic() - requested
                        if item is not None and elapsed > 0.05:
                            self.waits += 1
                            self.wait_seconds += elapsed
                    if self.cancelled():
                        stream.abort()  # Discard buffered PortAudio frames too.
            finally:
                try:
                    sun.state('idle')
                finally:
                    sun.close()
        except BaseException as exc:
            self.failure = str(exc)
            print('[Voice] continuous playback ERROR: ' + str(exc), flush=True)


class Session:
    def __init__(self):
        self.proc = None
        self.events = queue.Queue()
        self.start_lock = threading.Lock()
        self.request_lock = threading.Lock()

    def start(self):
        with self.start_lock:
            if self.proc is not None and self.proc.poll() is None:
                return
            self.events = queue.Queue()
            python = ROOT / '.tts-venv/bin/python'
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'
            self.proc = subprocess.Popen([str(python), '-m', 'ultimate_khorshid.voice.tts_worker'], cwd=ROOT, env=env,
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         text=True, encoding='utf-8', bufsize=1)
            proc, events = self.proc, self.events

            def reader():
                try:
                    for line in proc.stdout:
                        try: event = json.loads(line)
                        except ValueError: continue
                        if event.get('type') == 'ready':
                            print('[TTS] Ready on ' + event['device'] + '; original voice loaded once.', flush=True)
                        else:
                            events.put(event)
                finally:
                    events.put({'type': 'fatal', 'error': 'TTS worker stopped'})
            threading.Thread(target=reader, name='khorshid-tts-events', daemon=True).start()
            print('[TTS] Loading your voice and models once...', flush=True)

    def close(self):
        proc = self.proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        self.proc = None

    def speak(self, text, out='', play_it=True):
        from ultimate_khorshid.voice import audio as A
        controller = current_controller()
        if controller is not None:
            controller.check()
        with self.request_lock:
            if controller is not None:
                controller.check()
            self.start()
            request_id = uuid.uuid4().hex
            output = str(Path(out).resolve()) if out else A.tmp_wav('khorshid_pocket')
            player = None
            if play_it:
                player = SmoothPlayer(controller)
                player.start()
            with tempfile.TemporaryDirectory(prefix='khorshid_chunks_') as directory:
                cancel_path = Path(directory) / 'cancelled'
                request = {'id': request_id, 'text': text, 'output': output, 'directory': directory}
                started = time.monotonic()
                first_event = None
                cancellation_sent = False
                try:
                    self.proc.stdin.write(json.dumps(request, ensure_ascii=False) + '\n')
                    self.proc.stdin.flush()
                    deadline = time.monotonic() + 1200
                    while True:
                        cancelled = controller is not None and controller.is_cancelled
                        if cancelled and not cancellation_sent:
                            cancel_path.touch(exist_ok=True)
                            cancellation_sent = True
                            if player:
                                player.abort()
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError('TTS generation timed out')
                        try: event = self.events.get(timeout=min(remaining, .05))
                        except queue.Empty:
                            if player and player.failure:
                                raise RuntimeError(player.failure)
                            continue
                        if event.get('type') == 'fatal':
                            raise RuntimeError(event.get('error'))
                        if event.get('id') != request_id:
                            continue
                        cancelled = controller is not None and controller.is_cancelled
                        if cancelled:
                            if event['type'] in ('done', 'error'):
                                # Drain this request before reusing the resident
                                # model; late chunks can never reach a new turn.
                                raise CancelledError('تولید پاسخ لغو شد.')
                            continue
                        if event['type'] == 'error':
                            raise RuntimeError(event['error'])
                        if event['type'] == 'chunk':
                            path = Path(event['path']).resolve()
                            if path.parent != Path(directory).resolve():
                                raise RuntimeError('Invalid chunk path')
                            if first_event is None:
                                first_event = time.monotonic()
                                logger.debug('[Voice] first chunk ready in %.2fs', first_event - started)
                            if player:
                                player.add(path)
                        if event['type'] == 'done':
                            logger.debug('[Voice] full synthesis completed in %.2fs', time.monotonic()-started)
                            if player:
                                player.finish()
                            if controller is not None:
                                controller.check()
                            logger.debug('[Voice] response completed in %.2fs (including playback)',
                                         time.monotonic()-started)
                            return output
                except BaseException as exc:
                    if player:
                        player.abort()
                        if player.thread:
                            player.thread.join(timeout=2)
                    if not isinstance(exc, CancelledError):
                        self.close()
                    raise


_session = Session()
atexit.register(_session.close)

def warmup():
    _session.start()

def speak(text, out='', play_it=True):
    return _session.speak(text, out, play_it)
