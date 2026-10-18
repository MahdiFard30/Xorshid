"""Standalone Gemini Live audio trial. Does not import trading or original TTS."""
import argparse
import asyncio
from collections import deque
import contextlib
import getpass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DEFAULT_MODEL = 'gemini-3.8-live'
SYSTEM = 'نامت خورشید است. با مهدی فقط فارسی خودمانی، گرم و خوش\u200cبرخورد صحبت کن، مگر خودش صریحاً زبان دیگری بخواهد.\nتنها خطاب مجاز برای کاربر «قربان» است. هرگز او را «رفیق»، «داداش»، «دادا»، «عزیزم»، «برادر» یا خطاب مشابه صدا نکن. لازم نیست قربان را در هر جمله تکرار کنی؛ در جای طبیعی، مثلاً سلام یا پذیرش درخواست به کار ببر.\nسلام و تعارف گرم را نگه دار: «سلام قربان، چطوری؟»، «چشم قربان، بذار ببینیم چی شده». این\u200cها نمونه\u200cاند؛ مکانیکی تکرارشان نکن.\nگفتارت روان و محاوره\u200cای باشد، نه رسمی و اداری. از «می\u200cخوای»، «می\u200cتونیم»، «بذار» استفاده کن؛ شوخی سبک و مرتبط خوب است. پاسخ را خشک و تلگرافی نکن، ولی وقت کاربر را هم با مقدمه\u200cهای طولانی نگیر.\nبا آهنگ گرم و آسوده، تکیه\u200cهای طبیعی و بدون صدای تبلیغاتی یا خبرخوان حرف بزن. خنده مصنوعی، کشیدن افراطی کلمات و تغییر اغراق\u200cآمیز زیر و بمی نداشته باش.\nاگر نمی\u200cدانی یا درست نشنیدی، صادقانه بگو. تجربه و احساس انسانی یا کاری که انجام نداده\u200cای را ادعا نکن.\nشعر را با متن معتبر و مکث بین مصراع\u200cها بخوان؛ کلماتش را به محاوره تبدیل نکن. اگر از متن یا انتساب مطمئن نیستی بگو؛ آواز نخوان مگر بخواهد.\nاین نسخه آزمایش مکالمه است و ابزار کنترل کامپیوتر یا ترید ندارد؛ ادعای اجرای برنامه یا معامله نکن.\n'


class PlaybackBuffer:
    def __init__(self, maximum=24000*2*90, pitch=0.0):
        from ultimate_khorshid.interface.khorshid_live_pitch import PitchShifter
        self.pitch = PitchShifter(pitch)
        self.chunks = deque()
        self.size = 0
        self.maximum = maximum
        self.lock = threading.Lock()

    def put(self, data):
        if len(data) % 2:
            raise ValueError('Invalid PCM byte count')
        with self.lock:
            if self.size + len(data) > self.maximum:
                raise RuntimeError('صف صدا بیش از حد طولانی شد؛ اتصال را دوباره اجرا کن.')
            self.chunks.append(data)
            self.size += len(data)

    def take(self, length):
        with self.lock:
            result = bytearray()
            while self.chunks and len(result) < length:
                chunk = self.chunks.popleft()
                n = min(len(chunk), length-len(result))
                result.extend(chunk[:n]); self.size -= n
                if n < len(chunk): self.chunks.appendleft(chunk[n:])
            return self.pitch.process(bytes(result) + bytes(length-len(result)))

    def clear(self):
        with self.lock:
            self.chunks.clear(); self.size = 0
            self.pitch.reset()


def get_key():
    key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    if key: return key.strip()
    from dotenv import dotenv_values
    values = dotenv_values(ROOT/'.env')
    key = values.get('GEMINI_API_KEY') or values.get('GOOGLE_API_KEY')
    if key: return key.strip()
    python = ROOT/'.venv/bin/python'
    if python.is_file():
        # Reuse the existing vault through its own interpreter. Never print its
        # stdout/stderr or persist the secret in this standalone environment.
        code = ('import json; from ultimate_khorshid.core.vault import get_secret; '
                'print(json.dumps({"key": get_secret("GEMINI_API_KEY") or get_secret("GOOGLE_API_KEY") or ""}))')
        try:
            result = subprocess.run([str(python), '-c', code], cwd=ROOT,
                                    capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                key = json.loads(result.stdout).get('key')
                if key: return key.strip()
        except (OSError, ValueError, subprocess.TimeoutExpired): pass
    return getpass.getpass('کلید Gemini پیدا نشد؛ اینجا وارد کن (نمایش و ذخیره نمی‌شود): ').strip()


def config(voice):
    return {
        'response_modalities': ['AUDIO'],
        'system_instruction': SYSTEM,
        'speech_config': {'voice_config': {'prebuilt_voice_config': {'voice_name': voice}}},
        'input_audio_transcription': {},
        'output_audio_transcription': {},
        'realtime_input_config': {
            'automatic_activity_detection': {
                'disabled': True,
            },
            'activity_handling': 'START_OF_ACTIVITY_INTERRUPTS',
        },
    }


def handle_content(content, playback, output):
    """Process every part, and discard queued audio on server interruption."""
    if getattr(content, 'interrupted', False):
        playback.clear()
        output('\n[Live] پاسخ قطع شد؛ گوش می‌دهم.')
        return
    for field, label in [('input_transcription', 'شما'), ('output_transcription', 'خورشید')]:
        transcript = getattr(content, field, None)
        if transcript and getattr(transcript, 'text', None):
            output(f'{label}: {transcript.text}')
    turn = getattr(content, 'model_turn', None)
    if turn:
        for part in turn.parts or []:
            inline = getattr(part, 'inline_data', None)
            if inline and inline.data:
                mime = inline.mime_type or ''
                if not mime.startswith('audio/pcm'):
                    raise ValueError('Unexpected server audio format: '+mime)
                if 'rate=' in mime and not re.search(r'rate=24000(?:;|$)', mime):
                    raise ValueError('Unexpected server audio sample rate')
                playback.put(inline.data)


class QuietTerminal:
    """Hide/discard key echo in the foreground terminal, not other apps."""
    def __enter__(self):
        self.saved = None
        try:
            import termios
            self.fd = sys.stdin.fileno()
            if os.isatty(self.fd) and os.tcgetpgrp(self.fd) == os.getpgrp():
                self.saved = termios.tcgetattr(self.fd)
                changed = self.saved[:]
                changed[3] &= ~(termios.ECHO | termios.ECHONL)
                termios.tcsetattr(self.fd, termios.TCSANOW, changed)
        except (OSError, ValueError, AttributeError): pass
        return self

    def __exit__(self, *_):
        if self.saved is not None:
            import termios
            try:
                termios.tcflush(self.fd, termios.TCIFLUSH)
                termios.tcsetattr(self.fd, termios.TCSANOW, self.saved)
            except OSError: pass


class PushToTalk:
    """All state transitions run on the asyncio loop; key repeats are ignored."""
    def __init__(self, loop, playback, output=print):
        self.loop, self.playback, self.output = loop, playback, output
        self.events = asyncio.Queue()
        self.held = False
        self.capturing = False
        self.closed = False
        self.connected = True
        self.require_release = False
        self.generation = 0
        self.release_timer = None
        self.overflow = False

    def press(self):
        if self.closed: return
        if not self.connected or self.require_release:
            return
        if self.release_timer is not None:
            self.release_timer.cancel(); self.release_timer = None
        self.capturing = True
        if self.held: return
        self.held = True
        self.generation += 1
        self.playback.clear()
        self.events.put_nowait(('start', None))
        self.output('[Live] ضبط؛ حرف بزن، بعد کلید ۱ را رها کن.')

    def release(self):
        if self.require_release:
            self.require_release = False
            return
        if self.closed or not self.held: return
        # No new audio is admitted after key release. Brief debounce only
        # prevents X11 autorepeat releases from ending a held utterance.
        self.capturing = False
        if self.release_timer is not None: self.release_timer.cancel()
        self.release_timer = self.loop.call_later(.07, self.finish)

    def finish(self):
        self.release_timer = None
        if self.closed or not self.held: return
        self.held = False
        self.capturing = False
        self.events.put_nowait(('end', None))
        self.output('[Live] ارسال میکروفون بسته شد؛ منتظر پاسخ.')

    def audio(self, data, generation):
        if self.closed or not self.capturing or generation != self.generation: return
        # Fail clearly instead of building up a minutes-long voice queue.
        if self.events.qsize() >= 50:
            self.overflow = True
            return
        self.events.put_nowait(('audio', data))

    def close(self):
        self.closed = True
        self.capturing = self.held = False
        if self.release_timer is not None: self.release_timer.cancel()
        self.playback.clear()

    def suspend(self):
        """Discard unsent audio on disconnect; require a fresh physical press."""
        self.connected = False
        self.require_release = self.require_release or self.held
        self.capturing = self.held = False
        self.generation += 1
        if self.release_timer is not None:
            self.release_timer.cancel()
            self.release_timer = None
        while not self.events.empty():
            self.events.get_nowait()
        self.overflow = False
        self.playback.clear()

    def resume(self):
        if not self.closed:
            self.connected = True


class KeyListener:
    def __init__(self, loop, gate):
        from pynput import keyboard
        self.loop, self.gate = loop, gate
        def matches(key):
            return getattr(key, 'char', None) in ('1', '۱')
        def press(key):
            if matches(key):
                try: loop.call_soon_threadsafe(gate.press)
                except RuntimeError: pass
        def release(key):
            if matches(key):
                try: loop.call_soon_threadsafe(gate.release)
                except RuntimeError: pass
        self.listener = keyboard.Listener(on_press=press, on_release=release)

    def __enter__(self):
        self.listener.start()
        self.listener.wait()
        return self

    def __exit__(self, *_):
        self.gate.close()
        self.listener.stop()
        self.listener.join(timeout=1)


async def conversation(args, key):
    from google import genai
    from google.genai import types
    import sounddevice as sd
    playback = PlaybackBuffer(pitch=args.pitch)
    loop = asyncio.get_running_loop()
    gate = PushToTalk(loop, playback, lambda value: print(value, flush=True))
    callback_failed = threading.Event()

    def record(data, frames, timing, status):
        if not gate.capturing: return
        generation = gate.generation
        try: loop.call_soon_threadsafe(gate.audio, bytes(data), generation)
        except RuntimeError: pass

    def play(out, frames, timing, status):
        try: out[:] = playback.take(frames*2)
        except Exception:
            out[:] = bytes(frames*2)
            callback_failed.set()

    sd.check_input_settings(device=args.input_device, channels=1, dtype='int16', samplerate=16000)
    sd.check_output_settings(device=args.output_device, channels=1, dtype='int16', samplerate=24000)
    client = genai.Client(api_key=key, http_options={'api_version': 'v1beta'})
    tasks = []
    try:
        async with contextlib.AsyncExitStack() as stack:
            print('[Live] در حال اتصال به '+args.model+' …', flush=True)
            session = await asyncio.wait_for(stack.enter_async_context(
                client.aio.live.connect(model=args.model, config=config(args.voice))), timeout=25)
            # Microphone starts only after a successful server connection.
            with QuietTerminal(), KeyListener(loop, gate) as key_listener, sd.RawOutputStream(device=args.output_device, samplerate=24000,
                    channels=1, dtype='int16', blocksize=480, latency='low', callback=play), \
                 sd.RawInputStream(device=args.input_device, samplerate=16000,
                    channels=1, dtype='int16', blocksize=320, latency='low', callback=record):
                print('[Live] وصل شد. کلید ۱ را نگه دار و حرف بزن؛ رها کن تا جواب بدهد. خروج: Ctrl+C', flush=True)
                print('[Live] وسط پاسخ کلید ۱ را بگیر تا قطع شود. صدای آزمایشی: '+args.voice, flush=True)

                async def send():
                    while True:
                        kind, data = await gate.events.get()
                        if kind == 'start':
                            payload = {'activity_start': types.ActivityStart()}
                        elif kind == 'end':
                            payload = {'activity_end': types.ActivityEnd()}
                        else:
                            payload = {'audio': types.Blob(data=data, mime_type='audio/pcm;rate=16000')}
                        await asyncio.wait_for(session.send_realtime_input(**payload), timeout=15)

                async def receive():
                    while True:
                        got_message = False
                        async for message in session.receive():
                            got_message = True
                            content = message.server_content
                            if content:
                                if gate.held:
                                    # Do not let late chunks from the interrupted reply restart playback.
                                    playback.clear()
                                    transcript = getattr(content, 'input_transcription', None)
                                    if transcript and transcript.text: print('شما: '+transcript.text, flush=True)
                                else:
                                    handle_content(content, playback, lambda value: print(value, flush=True))
                            if getattr(message, 'go_away', None):
                                print('[Live] سرویس پایان نزدیک این نشست را اعلام کرد؛ اگر قطع شد دوباره اجرا کن.', flush=True)
                        if not got_message:
                            raise ConnectionError('Live stream ended')

                async def monitor():
                    while True:
                        await asyncio.sleep(2)
                        if callback_failed.is_set(): raise RuntimeError('Audio output callback failed')
                        if gate.overflow: raise RuntimeError('شبکه از ارسال صدا عقب افتاد؛ دوباره اجرا کن.')
                        if not key_listener.listener.is_alive(): raise RuntimeError('شنونده کلید متوقف شد؛ دوباره اجرا کن.')

                tasks = [asyncio.create_task(send()), asyncio.create_task(receive()), asyncio.create_task(monitor())]
                try:
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done: task.result()
                finally:
                    gate.close()
                    playback.clear()
                    for task in tasks: task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        gate.close()
        playback.clear()
        await client.aio.aclose()


def safe_error(exc, key):
    message = str(exc)
    if key: message = message.replace(key, '[API KEY REDACTED]')
    return re.sub(r'AIza[\w-]+', '[API KEY REDACTED]', message)[:1000]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=os.environ.get('KHORSHID_LIVE_MODEL', DEFAULT_MODEL))
    parser.add_argument('--voice', default='Charon')
    parser.add_argument('--pitch', type=float, default=-1.0, help='Output pitch in semitones (-3 to 3); 0 disables effect')
    parser.add_argument('--devices', action='store_true')
    parser.add_argument('--input-device', type=int)
    parser.add_argument('--output-device', type=int)
    args = parser.parse_args()
    key = ''
    try:
        import sounddevice as sd
        if args.devices:
            print(sd.query_devices()); return 0
        print('Gemini Live با کلید ۱؛ این ترمینال را در فوکوس نگه دار. برنامه صوتی قبلی را ببند.')
        print('فقط هنگام نگه‌داشتن ۱ صدا ارسال می‌شود؛ هزینه/سهمیه API اعمال می‌شود. از هدفون استفاده کن.')
        print('ابزار و ترید به این آزمایش وصل نیستند؛ صدا و تنظیمات اصلی خورشید تغییر نمی‌کنند.')
        print(f'[Live] تنظیم زیر و بمی خروجی: {args.pitch:+g} نیم‌پرده؛ برای صدای اصلی --pitch 0', flush=True)
        key = get_key()
        if not key: raise ValueError('No Gemini API key supplied')
        asyncio.run(conversation(args, key))
        return 0
    except KeyboardInterrupt:
        print('\n[Live] میکروفون و اتصال بسته شدند.'); return 0
    except Exception as exc:
        print('[Live] خطا: '+safe_error(exc, key), file=sys.stderr)
        print('اگر خطا مربوط به دسترسی مدل، سهمیه یا صداست، همین پیام را بدون کلید API بفرست.', file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
