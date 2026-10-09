"""حلقه گفت‌وگوی صوتی — بشنو → بفهم → عمل کن → بگو."""

from __future__ import annotations

import os
from typing import Optional

from ultimate_khorshid.voice import audio as A
from ultimate_khorshid.voice import engines as E


def voice_chat(cfg=None, agent: Optional[str] = None, seconds: int = 6,
               push: bool = False, no_tts: bool = False, once: bool = False,
               voice: str = "Kore") -> None:
    """حلقه اصلی چت صوتی."""
    from ultimate_khorshid.core.config import load_config
    from ultimate_khorshid.runtime import KhorshidRuntime

    cfg = cfg or load_config()
    rt = KhorshidRuntime(cfg, interactive=False)
    has_key = bool(E.api_key())

    print("🎙️  خورشید صوتی روشن شد!")
    print(f"   ایجنت: {agent or cfg.agent.default_agent} | مدل: {rt.model}")
    print(f"   رونویسی: {'Gemini ☁️' if has_key else 'آفلاین/ناقص ⚠️'} | "
          f"صدا: {'خاموش' if no_tts else ('Gemini ☁️' if has_key else 'آفلاین')}")
    print("   برای خروج: Ctrl+C\n")

    n = 0
    while True:
        n += 1
        try:
            wav_in = A.tmp_wav("khorshid_in")
            if push:
                input(f"🎤 دور {n} — Enter بزن و حرف بزن، دوباره Enter بزن تا تمام شود...")
                proc = A.start_recording(wav_in)
                input("   ⏺ در حال ضبط... (Enter = پایان)")
                A.stop_recording(proc)
            else:
                input(f"🎤 دور {n} — Enter بزن و {seconds} ثانیه حرف بزن...")
                print(f"   ⏺ ضبط {seconds} ثانیه...")
                A.record_fixed(wav_in, seconds=seconds)
            print("   🧠 در حال فهمیدن...")
            try:
                query = E.transcribe_file(wav_in)
            except Exception as e:
                print(f"   ❌ {e}\n")
                continue
            print(f"\n👤 شما: {query}\n")
            if query.strip().lower() in ("خداحافظ", "خروج", "تمام", "exit", "quit"):
                bye = "خدانگهدار قربان! 👋"
                print(f"🤖 خورشید: {bye}")
                if not no_tts:
                    E.speak_text(bye, voice=voice)
                break
            print("   ⚙️ در حال انجام کار...")
            try:
                result = rt.ask(query, agent=agent)
            except Exception as e:
                print(f"   ❌ خطای ایجنت: {e}\n")
                continue
            print(f"🤖 خورشید:\n{result.content}\n")
            if not no_tts:
                try:
                    E.speak_text(result.content, voice=voice)
                except Exception as e:
                    print(f"   ⚠️ پخش صدا نشد: {e}")
            if once:
                break
        except (EOFError, KeyboardInterrupt):
            print("\n👋 خدانگهدار قربان!")
            break
        finally:
            try:
                if os.path.exists(wav_in):
                    os.remove(wav_in)
            except Exception:
                pass
