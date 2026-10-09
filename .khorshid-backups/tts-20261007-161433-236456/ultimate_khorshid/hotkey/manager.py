"""Global hotkey — پوش‌تو‌تاک (Push-to-Talk) برای احضار سریع خورشید.

نیاز: pip install pynput   (یا: pip install -e ".[hotkey]")
نیاز ضبط: arecord یا ffmpeg + میکروفون

طرز کار (پیش‌فرض ctrl):
  1. کلید را نگه دار → بعد از ~۰.۲۵ ثانیه ضبط شروع می‌شود 🎤
  2. حرف بزن...
  3. ول کن → رونویسی → اجرا → جواب صوتی ⚙️🔊

چرا آستانه ۰.۲۵ ثانیه؟ تا Ctrl+C و Ctrl+V (سریع) ضبط را روشن نکنند؛
اگر وسط نگه داشتن، کلید دیگری هم زده شود، چرخه لغو می‌شود (یعنی شرتکات بوده).
ترکیب کامل مثل ctrl+shift+j هم همین‌طور: نگه دار → حرف بزن → ول کن.
"""

from __future__ import annotations

import os
import threading
from typing import Callable, FrozenSet, Optional, Tuple

MODIFIERS = {"ctrl", "alt", "shift", "cmd", "win", "meta"}


def parse_combo(s: str) -> Tuple[FrozenSet[str], FrozenSet[str]]:
    """'Ctrl+Shift+J' -> ({ctrl,shift}, {j}). خروجی نرمال‌شده."""
    parts = [p.strip().lower() for p in s.replace(" ", "").split("+") if p.strip()]
    mods, keys = set(), set()
    for p in parts:
        p = {"control": "ctrl", "command": "cmd", "windows": "win",
             "option": "alt", "return": "enter"}.get(p, p)
        (mods if p in MODIFIERS else keys).add(p)
    return frozenset(mods), frozenset(keys)


def combo_display(s: str) -> str:
    mods, keys = parse_combo(s)
    order = ["ctrl", "alt", "shift", "cmd", "win", "meta"]
    parts = sorted(mods, key=lambda m: order.index(m) if m in order else 99) + sorted(keys)
    return "+".join(parts) if parts else "ctrl"


def is_single_modifier(s: str) -> bool:
    mods, keys = parse_combo(s)
    return len(mods) == 1 and len(keys) == 0


def describe(s: str) -> str:
    return f"پوش‌تو‌تاک {combo_display(s)}: نگه دار 🎤 حرف بزن، ول کن ⚙️"


def _beep(start: bool = True) -> None:
    """بوق شروع/پایان ضبط. روی هر سیستمی که نشد، silently رد شو."""
    try:
        import platform
        if platform.system() == "Windows":
            import winsound  # type: ignore
            winsound.Beep(880 if start else 660, 120)
        else:
            print("\a", end="", flush=True)
    except Exception:
        pass


class HotkeyManager:
    """شنونده سراسری پوش‌تو‌تاک. بدون pynput خطای راهنما می‌دهد.

    متدهای press/release با «نام کلید» کار می‌کنند تا بدون pynput هم تست شوند؛
    کال‌بک‌های pynput فقط کلید را به نام تبدیل و به آن‌ها می‌دهند.
    """

    def __init__(self, combination: str = "ctrl", action: str = "voice",
                 on_text: Optional[Callable[[str], None]] = None,
                 hold_threshold: float = 0.25, max_record: float = 30.0,
                 agent: Optional[str] = None, voice: str = "Kore",
                 no_tts: bool = False) -> None:
        self.combination = combo_display(combination or "ctrl")
        self.action = action if action in ("voice", "dashboard") else "voice"
        self.on_text = on_text
        self.hold_threshold = hold_threshold
        self.max_record = max_record
        self.agent = agent
        self.voice = voice
        self.no_tts = no_tts
        self._mods, self._keys = parse_combo(self.combination)
        self._single = is_single_modifier(self.combination)
        self._pressed: set = set()
        self._armed = False        # آستانه نگه‌داشتن رد شده، منتظر ول کردن
        self._cancelled = False    # کلید دیگری وسط کار زده شد (شرتکات بوده)
        self._rec_proc = None      # هندل ضبط (فقط اکشن voice)
        self._rec_path = ""
        self._lock = threading.RLock()
        self._hold_timer: Optional[threading.Timer] = None
        self._max_timer: Optional[threading.Timer] = None
        self._listener = None

    # ---------------------------------------------------------- اتصال pynput ---
    def _need_pynput(self):
        try:
            from pynput import keyboard  # type: ignore
            return keyboard
        except ImportError:
            raise RuntimeError(
                "کتابخانه pynput نصب نیست. نصب:\n"
                '  pip install -e ".[hotkey]"   # یا: pip install pynput\n'
                "لینوکس ممکن است به دسترسی X11 نیاز داشته باشد (روی Wayland با sudo).")

    @staticmethod
    def _norm(key) -> str:
        try:
            from pynput.keyboard import Key  # type: ignore
            if key in (Key.ctrl, Key.ctrl_l, Key.ctrl_r):
                return "ctrl"
            if key in (Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr):
                return "alt"
            if key in (Key.shift, Key.shift_l, Key.shift_r):
                return "shift"
            if key in (Key.cmd, Key.cmd_l, Key.cmd_r):
                return "cmd"
            name = getattr(key, "name", None) or getattr(key, "char", None) or str(key)
            return str(name).lower().replace("key.", "")
        except Exception:
            return ""

    def _on_press(self, key) -> None:
        name = self._norm(key)
        if name:
            self.press(name)

    def _on_release(self, key) -> None:
        name = self._norm(key)
        if name:
            self.release(name)

    # ------------------------------------------------------- ماشین حالت PTT ---
    def press(self, name: str) -> None:
        """فشرده شدن یک کلید (نام نرمال‌شده مثل 'ctrl' یا 'j')."""
        with self._lock:
            if name in self._pressed:
                return  # تکرار خودکار را نادیده بگیر
            self._pressed.add(name)
            if self._single:
                only = next(iter(self._mods))
                if name == only and len(self._pressed) == 1 and not self._armed:
                    self._cancelled = False
                    if self.hold_threshold <= 0:
                        self._arm()
                    else:
                        self._cancel_hold_timer()
                        t = threading.Timer(self.hold_threshold, self._hold_elapsed)
                        t.daemon = True
                        self._hold_timer = t
                        t.start()
                else:
                    # کلید دیگر همراه مادرفایر = شرتکات معمولی (مثل Ctrl+C) → لغو
                    self._cancelled = True
                    self._cancel_hold_timer()
                    if self._armed:
                        self._abort()
            else:
                want = set(self._mods) | set(self._keys)
                if want <= self._pressed and not self._armed:
                    self._cancelled = False
                    self._arm()

    def release(self, name: str) -> None:
        """ول شدن یک کلید."""
        with self._lock:
            self._pressed.discard(name)
            if self._single:
                if name == next(iter(self._mods)):
                    self._cancel_hold_timer()
                    if self._armed and not self._cancelled:
                        self._finish()
                    else:
                        self._abort(silent=True)  # ضربه سریع یا شرتکات → هیچی
                    self._armed = False
                    self._cancelled = False
            else:
                want = set(self._mods) | set(self._keys)
                if self._armed and not (want <= self._pressed):
                    self._armed = False
                    self._finish()

    def _hold_elapsed(self) -> None:
        with self._lock:
            if self._cancelled or self._armed:
                return
            if next(iter(self._mods)) in self._pressed:
                self._arm()

    def _max_elapsed(self) -> None:
        with self._lock:
            if self._armed and self._rec_proc is not None:
                print("⏱ سقف ضبط رسید — پردازش...")
                self._armed = False
                self._finish()

    # -------------------------------------------------------------- ضبط ---
    def _arm(self) -> None:
        """آستانه رد شد: ضبط را شروع کن (فقط اکشن voice)."""
        self._cancel_hold_timer()
        self._armed = True
        if self.action != "voice":
            return
        if not self._start_capture():
            self._armed = False
            return
        if self.max_record > 0:
            self._cancel_max_timer()
            t = threading.Timer(self.max_record, self._max_elapsed)
            t.daemon = True
            self._max_timer = t
            t.start()

    def _start_capture(self) -> bool:
        """شروع ضبط واقعی. قابل monkeypatch در تست."""
        try:
            from ultimate_khorshid.voice import audio as A
            self._rec_path = A.tmp_wav("khorshid_ptt")
            self._rec_proc = A.start_recording(self._rec_path)
        except Exception as e:
            print(f"❌ ضبط شروع نشد: {e}")
            self._rec_proc = None
            return False
        print("🎤 ضبط... حرف بزن! (ول کن تا اجرا شود)")
        _beep(start=True)
        return True

    def _capture_transcript(self) -> str:
        """توقف ضبط + رونویسی. قابل monkeypatch در تست."""
        from ultimate_khorshid.voice import audio as A
        from ultimate_khorshid.voice.engines import transcribe_file
        proc, path = self._rec_proc, self._rec_path
        self._rec_proc = None
        if proc is None:
            return ""
        A.stop_recording(proc)
        _beep(start=False)
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        if size < 4000:
            print("🔇 چیزی شنیده نشد.")
            self._cleanup_wav(path)
            return ""
        print("🧠 در حال فهمیدن...")
        try:
            return transcribe_file(path)
        finally:
            self._cleanup_wav(path)

    @staticmethod
    def _cleanup_wav(path: str) -> None:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def _finish(self) -> None:
        """ول شدن کلید بعد از hold موفق → پردازش."""
        self._cancel_max_timer()
        self._cancel_hold_timer()
        if self.action == "dashboard":
            action_open_dashboard()
            return
        try:
            query = self._capture_transcript()
        except Exception as e:
            print(f"❌ {e}")
            return
        if not query.strip():
            return
        print(f"👤 {query}")
        if self.on_text is not None:
            try:
                self.on_text(query)
            except Exception as e:
                print(f"⚠️ خطای اکشن هات‌کی: {e}")
            return
        self.run_voice_pipeline(query)

    def _abort(self, silent: bool = False) -> None:
        self._cancel_hold_timer()
        self._cancel_max_timer()
        if self._rec_proc is not None:
            try:
                from ultimate_khorshid.voice import audio as A
                A.stop_recording(self._rec_proc)
            except Exception:
                pass
            self._rec_proc = None
            self._cleanup_wav(self._rec_path)
            self._rec_path = ""
            if not silent:
                print("🚫 لغو شد (شرتکات صفحه‌کلید).")
        self._armed = False

    def _cancel_hold_timer(self) -> None:
        try:
            if self._hold_timer:
                self._hold_timer.cancel()
        except Exception:
            pass
        self._hold_timer = None

    def _cancel_max_timer(self) -> None:
        try:
            if self._max_timer:
                self._max_timer.cancel()
        except Exception:
            pass
        self._max_timer = None

    # ------------------------------------------------------- اجرای فرمان ---
    def run_voice_pipeline(self, query: str) -> None:
        """اجرای دستور صوتی + جواب: انجام بده → بگو."""
        from ultimate_khorshid.runtime import KhorshidRuntime
        print("⚙️ در حال انجام کار...")
        try:
            result = KhorshidRuntime().ask(query, agent=self.agent)
        except Exception as e:
            print(f"❌ خطای ایجنت: {e}")
            return
        print(f"🤖 {result.content[:1500]}")
        if self.no_tts:
            return
        try:
            from ultimate_khorshid.voice import engines as E
            E.speak_text(result.content[:1500], voice=self.voice)
        except Exception as e:
            print(f"⚠️ پخش صدا نشد: {e}")

    # -------------------------------------------------------------- اجرا ---
    def start_background(self):
        keyboard = self._need_pynput()
        self._listener = keyboard.Listener(on_press=self._on_press,
                                           on_release=self._on_release, daemon=True)
        self._listener.start()
        print(f"⌨️ {describe(self.combination)} — برای توقف Ctrl+C")
        return self._listener

    def start_blocking(self) -> None:
        keyboard = self._need_pynput()
        print(f"⌨️ {describe(self.combination)} — برای توقف Ctrl+C")
        print("   (ضربه سریع یا Ctrl+C/V ضبط را روشن نمی‌کند — باید نگه داری)")
        with keyboard.Listener(on_press=self._on_press, on_release=self._on_release) as lst:
            lst.join()

    def stop(self) -> None:
        self._abort(silent=True)
        try:
            if self._listener:
                self._listener.stop()
        except Exception:
            pass


# ---------------------------------------------------------------- اکشن‌ها ---

def action_open_dashboard(port: int = 8899) -> None:
    import webbrowser
    url = f"http://127.0.0.1:{port}"
    print(f"🌐 باز کردن داشبورد: {url}")
    webbrowser.open(url)


def _daemon_base():
    from pathlib import Path
    base = Path.home() / ".ultimate-jarvis"
    base.mkdir(parents=True, exist_ok=True)
    return base


def daemon_status() -> dict:
    """وضعیت دیمون: روشن/خاموش + pid + ترکیب فعلی."""
    import platform
    import subprocess
    base = _daemon_base()
    fp = base / "hotkey.pid"
    running, pid = False, 0
    if fp.exists():
        try:
            pid = int(fp.read_text(encoding="utf-8").strip())
            if platform.system() == "Windows":
                out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                     capture_output=True, text=True, timeout=10)
                running = str(pid) in (out.stdout or "")
            else:
                os.kill(pid, 0)
                running = True
        except Exception:
            running = False
    try:
        from ultimate_khorshid.core.settings import get_settings
        combo = get_settings().get("hotkey", "ctrl")
    except Exception:
        combo = "ctrl"
    return {"running": running, "pid": pid, "hotkey": combo,
            "describe": describe(combo)}


def stop_daemon() -> str:
    """توقف دیمون روشن. پیام فارسی نتیجه را برمی‌گرداند."""
    import platform
    import subprocess
    import time
    base = _daemon_base()
    fp = base / "hotkey.pid"
    if not fp.exists():
        return "دیمون روشن نیست."
    try:
        pid = int(fp.read_text(encoding="utf-8").strip())
    except Exception:
        try:
            fp.unlink(missing_ok=True)
        except Exception:
            pass
        return "فایل pid خراب بود؛ پاک شد."
    try:
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=10)
        else:
            os.kill(pid, 15)
            for _ in range(15):
                time.sleep(0.2)
                try:
                    os.kill(pid, 0)
                except OSError:
                    break
            else:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
    except ProcessLookupError:
        pass
    except Exception as e:
        return f"⚠️ توقف نشد: {e}"
    try:
        fp.unlink(missing_ok=True)
    except Exception:
        pass
    return f"⏹ دیمون پوش‌تو‌تاک متوقف شد (pid={pid})."


def run_daemon(combination: str = "ctrl", action: str = "voice",
               hold: float = 0.25, max_record: float = 30.0) -> None:
    import sys
    from datetime import datetime
    st = daemon_status()
    if st["running"]:
        print(f"⚠️ دیمون از قبل روشن است (pid={st['pid']}). توقف: khorshid hotkey --stop")
        return
    base = _daemon_base()
    pid_fp, log_fp = base / "hotkey.pid", base / "hotkey.log"
    pid_fp.write_text(str(os.getpid()), encoding="utf-8")
    log_f = open(log_fp, "a", encoding="utf-8")
    _stdout = sys.stdout

    class _Tee:
        def write(self, s):
            _stdout.write(s)
            try:
                log_f.write(s)
                log_f.flush()
            except Exception:
                pass

        def flush(self):
            _stdout.flush()
            try:
                log_f.flush()
            except Exception:
                pass

    sys.stdout = _Tee()  # type: ignore
    try:
        print(f"─── روشن شدن دیمون: {datetime.now():%Y-%m-%d %H:%M} ───")
        HotkeyManager(combination, action=action,
                      hold_threshold=hold, max_record=max_record).start_blocking()
    except KeyboardInterrupt:
        print("\n👋 دیمون متوقف شد.")
    finally:
        sys.stdout = _stdout
        try:
            log_f.close()
        except Exception:
            pass
        try:
            pid_fp.unlink(missing_ok=True)
        except Exception:
            pass


def push_to_talk_once(combination: str = "ctrl", hold: float = 0.25,
                      max_record: float = 30.0, timeout: float = 120.0) -> str:
    """یک چرخه پوش‌تو‌تاک (برای تست): نگه دار → حرف بزن → ول کن → متن را برگردان."""
    done = threading.Event()
    box: list = []
    mgr = HotkeyManager(combination, action="voice",
                        on_text=lambda q: (box.append(q), done.set()),
                        hold_threshold=hold, max_record=max_record)
    mgr.start_background()
    print("🎧 یک بار امتحان کن: کلید را نگه دار، حرف بزن، ول کن...")
    ok = done.wait(timeout)
    mgr.stop()
    if not ok:
        print("⏱ وقتی تمام شد و چیزی گفته نشد.")
        return ""
    return box[0] if box else ""
