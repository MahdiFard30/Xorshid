"""موتورهای صوت — STT/TTS با Gemini API + TTS آفلاین/Pocket-TTS."""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import urllib.request
import urllib.error
from typing import List

from ultimate_khorshid.voice import audio as A

BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
    if key:
        return key
    try:
        from ultimate_khorshid.core.vault import get_secret
        return get_secret("GEMINI_API_KEY") or get_secret("GOOGLE_API_KEY") or ""
    except Exception:
        return ""


def _post(model: str, payload: dict, timeout: float = 90.0) -> dict:
    key = api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY تنظیم نشده.")
    req = urllib.request.Request(
        f"{BASE}/{model}:generateContent",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"Gemini صوتی خطا (HTTP {e.code}): {body}")


def _text_of(data: dict) -> str:
    try:
        return (data["candidates"][0]["content"]["parts"][0].get("text", "") or "").strip()
    except (KeyError, IndexError):
        return ""


class GeminiSTT:
    """رونویسی صدا با جمینای (فارسی/انگلیسی/چندزبانه)."""

    def __init__(self, model: str = "gemini-3.5-flash-lite") -> None:
        self.model = model

    def transcribe(self, wav_path: str, lang_hint: str = "fa") -> str:
        with open(wav_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        payload = {"contents": [{"role": "user", "parts": [
            {"text": ("Transcribe the following audio exactly in its original language "
                      "(most likely Persian/Farsi). Output ONLY the transcription, nothing else.")},
            {"inlineData": {"mimeType": "audio/wav", "data": b64}}]}]}
        data = _post(self.model, payload, timeout=90.0)
        txt = _text_of(data)
        if not txt:
            raise RuntimeError("رونویسی خالی برگشت.")
        return txt


def stt_backends() -> dict:
    import importlib.util
    return {"faster_whisper(local)": importlib.util.find_spec("faster_whisper") is not None,
            "gemini": bool(api_key()),
            "google-sr": importlib.util.find_spec("speech_recognition") is not None}


class LocalSTT:
    def __init__(self, model: str = "small") -> None:
        self.model_name = model

    def transcribe(self, wav_path: str, lang_hint: str = "fa") -> str:
        from faster_whisper import WhisperModel  # type: ignore
        m = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        segs, _ = m.transcribe(wav_path, language=lang_hint, beam_size=3)
        return "".join(s.text for s in segs).strip()


def transcribe_file(path: str, engine: str = "auto") -> str:
    import importlib.util
    want = (engine or "auto").lower()
    if want in ("auto", "local") and importlib.util.find_spec("faster_whisper"):
        try:
            return LocalSTT().transcribe(path)
        except Exception as e:
            if want == "local":
                raise RuntimeError(f"رونویسی محلی نشد: {e}")
    if want in ("auto", "gemini") and api_key():
        return GeminiSTT().transcribe(path)
    if want not in ("auto", "google"):
        raise RuntimeError(f"بک‌اند «{want}» در دسترس نیست. (stt: {stt_backends()})")
    try:
        import speech_recognition as sr  # type: ignore
        r = sr.Recognizer()
        with sr.AudioFile(path) as src:
            aud = r.record(src)
        return r.recognize_google(aud, language="fa-IR")
    except ImportError:
        raise RuntimeError("نه کلید Gemini هست نه SpeechRecognition نصب است. (pip install SpeechRecognition)")
    except Exception as e:
        raise RuntimeError(f"خطای رونویسی آفلاین: {e}")


def split_sentences(text: str, limit: int = 450) -> List[str]:
    text = clean_for_speech(text)
    parts = re.split(r"(?<=[.!?؟!\n])\s+", text)
    chunks, cur = [], ""
    for p in parts:
        if len(cur) + len(p) + 1 <= limit:
            cur = (cur + " " + p).strip()
        else:
            if cur:
                chunks.append(cur)
            cur = p
    if cur:
        chunks.append(cur)
    return chunks or [text[:limit]]


def clean_for_speech(text: str) -> str:
    t = re.sub(r"```.*?```", " . ", text, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[#*_>~|]", "", t)
    t = re.sub(r"https?://\S+", " لینک ", t)
    return re.sub(r"\s+", " ", t).strip()


def _is_persian(text: str) -> bool:
    fa = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    return fa > len(text) * 0.15


class GeminiTTS:
    def __init__(self, model: str = "gemini-2.5-flash-preview-tts",
                 voice: str = "Kore") -> None:
        self.model = model
        self.voice = voice or "Kore"

    def synthesize(self, text: str, out_path: str = "") -> str:
        text = clean_for_speech(text)
        if not text.strip():
            raise RuntimeError("متنی برای خواندن نیست.")
        style = ("Read aloud naturally in Persian with a calm, Khorshid-like assistant tone:\n"
                 if _is_persian(text) else
                 "Read aloud naturally with a calm, Khorshid-like assistant tone:\n")
        chunks = split_sentences(text)
        tmpdir = tempfile.mkdtemp(prefix="khorshid_tts_")
        wavs: List[str] = []
        for i, ch in enumerate(chunks):
            payload = {"contents": [{"parts": [{"text": style + ch}]}],
                       "generationConfig": {
                           "responseModalities": ["AUDIO"],
                           "speechConfig": {"voiceConfig": {
                               "prebuiltVoiceConfig": {"voiceName": self.voice}}}}}
            data = _post(self.model, payload, timeout=120.0)
            try:
                inline = data["candidates"][0]["content"]["parts"][0]["inlineData"]
                pcm = base64.b64decode(inline["data"])
            except (KeyError, IndexError):
                raise RuntimeError(f"TTS خروجی صوتی نداد: {str(data)[:300]}")
            rate = 24000
            m = re.search(r"rate=(\d+)", inline.get("mimeType", ""))
            if m:
                rate = int(m.group(1))
            wp = os.path.join(tmpdir, f"part{i}.wav")
            A.pcm_to_wav(pcm, wp, rate=rate)
            wavs.append(wp)
        out = out_path or A.tmp_wav("khorshid_speech")
        A.concat_wavs(wavs, out)
        return out


class LocalTTS:
    def speak(self, text: str) -> bool:
        text = clean_for_speech(text)[:2000]
        import shutil
        import subprocess
        try:
            if shutil.which("espeak-ng"):
                subprocess.run(["espeak-ng", "-v", "fa", "-s", "150", text],
                               check=True, timeout=120)
                return True
            if shutil.which("espeak"):
                subprocess.run(["espeak", "-v", "fa", text], check=True, timeout=120)
                return True
            if shutil.which("say"):
                subprocess.run(["say", text], check=True, timeout=120)
                return True
            import platform
            if platform.system() == "Windows":
                subprocess.run(["powershell", "-c",
                                f'Add-Type -AssemblyName System.Speech; '
                                f'(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak("{text[:500]}")'],
                               check=True, timeout=120)
                return True
        except Exception as e:
            print(f"⚠️ خطای TTS آفلاین: {e}")
            return False
        print("⚠️ ابزار TTS آفلاین پیدا نشد (espeak نصب کنید: sudo apt install espeak-ng)")
        return False


class PocketTTS:
    """TTS فارسی با صدای کلون‌شده کاربر، در venv جدا."""

    def __init__(self) -> None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        self.python = os.path.join(root, ".tts-venv", "bin", "python")
        self.script = os.path.join(root, "pocket_farsi_tts.py")

    def synthesize(self, text: str, out_path: str = "") -> str:
        from ultimate_khorshid.voice.tts_session import speak
        return speak(clean_for_speech(text), out_path, play_it=False)


def speak_text(text: str, out: str = "", voice: str = "Kore", play_it: bool = True) -> str:
    """Persistent original-voice synthesis, with playback as chunks become ready."""
    from ultimate_khorshid.voice.tts_session import speak
    try:
        return speak(clean_for_speech(text), out, play_it)
    except Exception as exc:
        raise RuntimeError(
            "تولید یا پخش صدای اختصاصی ناموفق بود؛ صدای دیگری جایگزین نشد. " + str(exc)
        ) from exc
