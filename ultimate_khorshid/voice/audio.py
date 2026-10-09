"""Audio I/O — ضبط و پخش صدا با ابزارهای سیستم (بدون وابستگی اجباری).

ضبط: sounddevice (اختیاری) ← arecord ← ffmpeg ← sox
پخش: afplay ← aplay ← paplay ← ffplay ← PowerShell ← playsound(اختیاری)
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path


def which(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def backends() -> dict:
    """گزارش ابزارهای صوتی موجود."""
    return {
        "arecord": bool(shutil.which("arecord")),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "sox": bool(shutil.which("sox")),
        "aplay": bool(shutil.which("aplay")),
        "afplay": bool(shutil.which("afplay")),
        "espeak": bool(which("espeak-ng", "espeak")),
        "sounddevice": _has_sounddevice(),
    }


def _has_sounddevice() -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec("sounddevice") is not None
    except Exception:
        return False


# ---------------------------------------------------------------- ضبط ---

def record_fixed(path: str, seconds: int = 6, rate: int = 16000) -> str:
    """ضبط N ثانیه به فایل WAV. مسیر فایل را برمی‌گرداند."""
    seconds = max(1, min(60, seconds))
    # ۱) sounddevice (کراس‌پلتفرم، اگر نصب باشد)
    if _has_sounddevice():
        try:
            return _record_sounddevice(path, seconds, rate)
        except Exception:
            pass
    sys = platform.system()
    # ۲) arecord (لینوکس)
    if shutil.which("arecord"):
        cmd = ["arecord", "-f", "S16_LE", "-r", str(rate), "-c", "1",
               "-d", str(seconds), "-t", "wav", "-q", path]
        subprocess.run(cmd, check=True, capture_output=True, timeout=seconds + 10)
        return path
    # ۳) ffmpeg
    if shutil.which("ffmpeg"):
        if sys == "Darwin":
            src = ["-f", "avfoundation", "-i", ":0"]
        elif sys == "Windows":
            src = ["-f", "dshow", "-i", 'audio="Microphone"']
        else:
            src = ["-f", "alsa", "-i", "default"]
        cmd = ["ffmpeg", "-y", "-loglevel", "error", *src, "-t", str(seconds),
               "-ar", str(rate), "-ac", "1", path]
        subprocess.run(cmd, check=True, capture_output=True, timeout=seconds + 15)
        return path
    # ۴) sox
    if shutil.which("sox"):
        cmd = ["sox", "-d", "-r", str(rate), "-c", "1", "-t", "wav", path,
               "trim", "0", str(seconds)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=seconds + 10)
        return path
    raise RuntimeError(
        "ابزار ضبط پیدا نشد! یکی را نصب کنید:\n"
        "  لینوکس: sudo apt install alsa-utils  (یا ffmpeg)\n"
        "  مک: brew install ffmpeg\n"
        "  یا: pip install sounddevice")


def _record_sounddevice(path: str, seconds: int, rate: int) -> str:
    import sounddevice as sd  # type: ignore
    import numpy as np  # type: ignore
    print(f"🎤 در حال ضبط ({seconds} ثانیه)...")
    data = sd.rec(int(seconds * rate), samplerate=rate, channels=1, dtype="int16")
    sd.wait()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.asarray(data).tobytes())
    return path


def start_recording(path: str, rate: int = 16000):
    """شروع ضبط push-to-talk. هندل پروسه را برمی‌گرداند (با stop_recording تمامش کن)."""
    sys = platform.system()
    if shutil.which("arecord"):
        return subprocess.Popen(["arecord", "-f", "S16_LE", "-r", str(rate),
                                 "-c", "1", "-t", "wav", "-q", path],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if shutil.which("ffmpeg"):
        src = ["-f", "avfoundation", "-i", ":0"] if sys == "Darwin" else (
            ["-f", "dshow", "-i", 'audio="Microphone"'] if sys == "Windows"
            else ["-f", "alsa", "-i", "default"])
        return subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", *src,
                                 "-ar", str(rate), "-ac", "1", path],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    raise RuntimeError("برای حالت push-to-talk به arecord یا ffmpeg نیاز است.")


def stop_recording(proc) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# ---------------------------------------------------------------- پخش ---

def play(path: str) -> bool:
    """پخش فایل صوتی. True اگر پخش شد."""
    if not os.path.exists(path):
        return False
    sys = platform.system()
    try:
        if sys == "Darwin" and shutil.which("afplay"):
            subprocess.run(["afplay", path], check=True, timeout=300)
            return True
        if shutil.which("aplay"):
            subprocess.run(["aplay", "-q", path], check=True, timeout=300,
                           capture_output=True)
            return True
        if shutil.which("paplay"):
            subprocess.run(["paplay", path], check=True, timeout=300)
            return True
        if shutil.which("ffplay"):
            subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                           check=True, timeout=300)
            return True
        if sys == "Windows":
            subprocess.run(["powershell", "-c",
                            f"(New-Object Media.SoundPlayer '{path}').PlaySync()"],
                           check=True, timeout=300)
            return True
        try:
            from playsound import playsound  # type: ignore
            playsound(path)
            return True
        except Exception:
            pass
    except Exception as e:
        print(f"⚠️ خطای پخش: {e}")
        return False
    print(f"⚠️ ابزار پخشی پیدا نشد؛ فایل ذخیره شد: {path}")
    return False


# ------------------------------------------------------------- ابزار WAV ---

def pcm_to_wav(pcm: bytes, path: str, rate: int = 24000,
               channels: int = 1, width: int = 2) -> str:
    """PCM خام (خروجی TTS جمینای) → فایل WAV."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return path


def concat_wavs(paths: list[str], out: str) -> str:
    """چسباندن چند WAV هم‌فرمت."""
    if len(paths) == 1:
        shutil.copy(paths[0], out)
        return out
    with wave.open(paths[0], "rb") as first:
        params = first.getparams()
    with wave.open(out, "wb") as w:
        w.setparams(params)
        for p in paths:
            with wave.open(p, "rb") as r:
                w.writeframes(r.readframes(r.getnframes()))
    return out


def tmp_wav(prefix: str = "khorshid") -> str:
    return os.path.join(tempfile.gettempdir(), f"{prefix}_{os.getpid()}.wav")
