"""Wake word — شنونده همیشه‌روشن «خورشید!» (بیدارباش صوتی).

بک‌اند: openwakeword (pip install openwakeword) + sounddevice برای میکروفون.
بدون آن‌ها: خطای راهنمای تمیز. برای تست، detect_frames با detector جعلی.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, List, Optional

DEFAULT_KEYWORDS = ("خورشید", "khorshid")


def backend_status() -> dict:
    import importlib.util
    return {"openwakeword": importlib.util.find_spec("openwakeword") is not None,
            "sounddevice": importlib.util.find_spec("sounddevice") is not None}


def need_error() -> Optional[str]:
    st = backend_status()
    missing = [k for k, v in st.items() if not v]
    if not missing:
        return None
    return ("برای wake word لازم است:\n  pip install openwakeword sounddevice\n"
            f"کمبود: {', '.join(missing)}")


def detect_frames(frames: Iterable[Any],
                  detector: Callable[[Any], List[str]]) -> Optional[str]:
    """حلقه تشخیص خالص روی فریم‌ها — اولین کلیدواژه یافته یا None."""
    for fr in frames:
        try:
            hits = detector(fr) or []
        except Exception:
            continue
        if hits:
            return str(hits[0])
    return None


class WakeListener:
    def __init__(self, keywords: tuple = DEFAULT_KEYWORDS, threshold: float = 0.5,
                 on_wake: Optional[Callable[[str], None]] = None) -> None:
        self.keywords = keywords
        self.threshold = threshold
        self.on_wake = on_wake or (lambda k: None)

    def listen_forever(self) -> None:
        err = need_error()
        if err:
            print(f"❌ {err}")
            return
        import numpy as np  # type: ignore
        import sounddevice as sd  # type: ignore
        from openwakeword.model import Model  # type: ignore
        print(f"👂 گوش به‌زنگ: {', '.join(self.keywords)} (توقف: Ctrl+C)")
        model = Model(wakeword_models=list(self.keywords))
        try:
            with sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                                blocksize=1280) as stream:
                while True:
                    data, _ = stream.read(1280)
                    scores = model.predict(np.frombuffer(data.tobytes(), dtype=np.int16))
                    for kw in self.keywords:
                        if scores.get(kw, 0) >= self.threshold:
                            print(f"🔔 بیدار شدم: {kw}")
                            try:
                                self.on_wake(kw)
                            except Exception as e:
                                print(f"⚠️ {e}")
                            model.reset()
                            break
        except KeyboardInterrupt:
            print("\n👋 شنونده خاموش شد.")
