"""Runtime-only integration with the supplied Ultimate Khorshid source files.

No project source files, hotkey settings or TTS models are edited.
"""
import functools
import os
import queue
import signal
import sys
import threading
import time
from pathlib import Path

from sun_bridge import SunBridge


class MeterUnavailable(Exception):
    pass


def play_metered(path, sun):
    """Play decoded audio and meter PCM against the output device's DAC clock.

    All socket I/O and RMS calculations happen outside the audio callback.
    Failure before opening the stream allows the existing player to take over.
    """
    try:
        import numpy as np
        import sounddevice as sd
        import soundfile as sf
        # Bound memory use. Normal Khorshid responses are far smaller than this.
        info = sf.info(path)
        if info.frames * info.channels > 24_000_000:
            raise ValueError('Audio is too large for the metered player')
        samples, rate = sf.read(path, dtype='float32', always_2d=True)
        if not len(samples):
            return False
    except Exception as exc:
        raise MeterUnavailable(str(exc)) from exc

    done = threading.Event()
    stop_meter = threading.Event()
    meter_queue = queue.Queue(maxsize=64)
    cursor = 0
    callback_errors = []
    underflows = [0]

    def callback(outdata, frames, timing, status):
        nonlocal cursor
        outdata.fill(0)
        try:
            if status.output_underflow:
                underflows[0] += 1
            count = min(frames, len(samples) - cursor)
            if count:
                outdata[:count] = samples[cursor:cursor + count]
                # Convert PortAudio clock to monotonic time for the meter worker.
                when = time.monotonic() + max(0, timing.outputBufferDacTime - timing.currentTime)
                try:
                    meter_queue.put_nowait((cursor, count, when))
                except queue.Full:
                    pass  # Dropping a visual update must never drop audio.
                cursor += count
        except Exception as exc:
            callback_errors.append(exc)
            raise sd.CallbackAbort()
        if cursor >= len(samples):
            raise sd.CallbackStop()

    def meter():
        while not stop_meter.is_set():
            try:
                start, count, when = meter_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if stop_meter.wait(max(0, when - time.monotonic())):
                return
            block = samples[start:start + count]
            rms = float(np.sqrt(np.mean(block * block)))
            sun.level(rms)

    device = os.environ.get('KHORSHID_SUN_AUDIO_DEVICE') or None
    if device and device.isdecimal():
        device = int(device)
    try:
        stream = sd.OutputStream(samplerate=rate, channels=samples.shape[1],
                                 dtype='float32', blocksize=max(128, int(rate * 0.025)),
                                 device=device, latency='low', callback=callback,
                                 finished_callback=done.set)
    except Exception as exc:
        raise MeterUnavailable(str(exc)) from exc
    worker = threading.Thread(target=meter, name='sun-audio-meter', daemon=True)
    started = False
    try:
        # Callback events, rather than text generation, switch the sun to speaking.
        stream.start()
        started = True
        worker.start()
        deadline = time.monotonic() + len(samples) / rate + 15
        while not done.wait(0.1):
            if time.monotonic() > deadline:
                raise RuntimeError('Audio playback timed out')
        if callback_errors:
            raise RuntimeError(f'Audio callback failed: {callback_errors[0]}')
        if underflows[0]:
            print(f'[Sun] Audio buffer underruns: {underflows[0]}', flush=True)
        return True
    except Exception as exc:
        if not started:
            raise MeterUnavailable(str(exc)) from exc
        # Never replay the whole response if a stream failed halfway through.
        print(f'[Sun] Playback stopped: {exc}', file=sys.stderr, flush=True)
        return False
    finally:
        stop_meter.set()
        stream.abort()
        stream.close()
        if worker.is_alive():
            worker.join(timeout=1)
        sun.state('idle')


def install_hooks(sun):
    from ultimate_khorshid.voice import audio as audio
    from ultimate_khorshid.voice import engines
    from ultimate_khorshid.hotkey.manager import HotkeyManager

    if getattr(audio, '_sun_hooks_installed', False):
        return
    audio._sun_hooks_installed = True

    original_start = audio.start_recording
    original_stop = audio.stop_recording
    original_play = audio.play
    original_fixed = audio.record_fixed

    @functools.wraps(original_start)
    def start_recording(*args, **kwargs):
        try:
            proc = original_start(*args, **kwargs)
        except BaseException:
            sun.state('idle')
            raise
        sun.state('listening')
        return proc

    @functools.wraps(original_stop)
    def stop_recording(*args, **kwargs):
        try:
            return original_stop(*args, **kwargs)
        finally:
            sun.state('thinking')

    @functools.wraps(original_fixed)
    def record_fixed(*args, **kwargs):
        sun.state('listening')
        try:
            result = original_fixed(*args, **kwargs)
        except BaseException:
            sun.state('idle')
            raise
        sun.state('thinking')
        return result

    @functools.wraps(original_play)
    def play(path):
        try:
            return play_metered(path, sun)
        except MeterUnavailable as exc:
            print(f'[Sun] Original audio player used; amplitude unavailable: {exc}', flush=True)
            sun.state('speaking')
            try:
                return original_play(path)
            finally:
                sun.state('idle')

    audio.start_recording = start_recording
    audio.stop_recording = stop_recording
    audio.record_fixed = record_fixed
    audio.play = play

    # Restore idle on empty transcript, no_tts, errors, cancellation, and success.
    original_finish = HotkeyManager._finish
    @functools.wraps(original_finish)
    def finish(self, *args, **kwargs):
        try:
            return original_finish(self, *args, **kwargs)
        finally:
            sun.state('idle')
    HotkeyManager._finish = finish

    original_abort = HotkeyManager._abort
    @functools.wraps(original_abort)
    def abort(self, *args, **kwargs):
        had_capture = self._rec_proc is not None
        try:
            return original_abort(self, *args, **kwargs)
        finally:
            if had_capture:
                sun.state('idle')
    HotkeyManager._abort = abort

    # Pocket and Gemini both use audio.play. Direct OS speech is state-only.
    original_local = engines.LocalTTS.speak
    @functools.wraps(original_local)
    def local_speak(self, *args, **kwargs):
        print('[Sun] Local OS speech: state only, PCM amplitude unavailable.', flush=True)
        sun.state('speaking')
        try:
            return original_local(self, *args, **kwargs)
        finally:
            sun.state('idle')
    engines.LocalTTS.speak = local_speak


def main():
    # This session contains only the child launched by the overlay and its children.
    if os.name == 'posix':
        os.setsid()
    project = Path(__file__).resolve().parent
    sys.path.insert(0, str(project))
    os.chdir(project)
    sun = SunBridge()
    install_hooks(sun)
    # Keep long TTS/model calls in thinking state without arbitrary timeouts.
    from ultimate_khorshid.cli.main import main as khorshid_main
    sys.argv = ['khorshid', 'hotkey', '--daemon']
    sun.state('idle')
    print('[Sun] Connected: capture states + Pocket/Gemini playback PCM.', flush=True)
    try:
        return khorshid_main()
    finally:
        sun.state('idle')
        sun.close()


if __name__ == '__main__':
    raise SystemExit(main())
