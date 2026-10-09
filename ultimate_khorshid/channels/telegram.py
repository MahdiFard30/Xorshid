"""کانال تلگرام — کنترل کامل خورشید از موبایل. فقط stdlib، بدون وابستگی.

ساخت ربات (۲ دقیقه):
  1. در تلگرام به @BotFather پیام بده → دستور /newbot
  2. اسم و یوزرنیم بده → یک توکن مثل 123456:AAE... می‌گیری
  3. اجرا:  khorshid telegram --token 123456:AAE...
     یا:    export KHORSHID_TELEGRAM_TOKEN=... && khorshid telegram

امنیت: با --allow فقط به آیدی‌های خودت جواب بده:
  khorshid telegram --allow 123456789,@myusername
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ultimate_khorshid.core.registry import ChannelRegistry

API = "https://api.telegram.org/bot"
LIMIT = 4000  # سقف پیام تلگرام ۴۰۹۶ است؛ حاشیه امن

HELP_TEXT = """🤖 خورشید در تلگرام — چشم قربان!

هر چیزی بنویسی، مثل khorshid ask اجرا می‌شود:
• تتر چنده؟
• هوای تهران چطوره؟
• لیست فایل‌های پوشه . را نشان بده

دستورات:
/help — همین راهنما
/agents — لیست ایجنت‌ها
/tools — لیست ابزارها
/doctor — وضعیت سیستم
"""


def chunk_message(text: str, limit: int = LIMIT) -> List[str]:
    """تکه‌تکه کردن جواب بلند با حفظ خط‌ها."""
    text = text or ""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for line in text.splitlines(keepends=True):
        if len(line) > limit:  # خط غول‌پیکر را اجباری بشکن
            if cur:
                chunks.append(cur)
                cur = ""
            for i in range(0, len(line), limit):
                chunks.append(line[i:i + limit])
            continue
        if len(cur) + len(line) > limit:
            chunks.append(cur)
            cur = ""
        cur += line
    if cur:
        chunks.append(cur)
    return chunks or [""]


def parse_command(text: str) -> Tuple[str, str]:
    """'/agents x' -> ('agents', 'x'). غیرفرمان -> ('', متن)."""
    t = (text or "").strip()
    if not t.startswith("/"):
        return "", t
    parts = t[1:].split(None, 1)
    cmd = parts[0].split("@")[0].lower()
    return cmd, (parts[1] if len(parts) > 1 else "")


def extract_message(update: Dict[str, Any]) -> Optional[Tuple[int, str, str, str]]:
    """update تلگرام -> (chat_id, متن, نام کاربر, یوزرنیم) یا None."""
    try:
        msg = update.get("message") or update.get("edited_message") or {}
        text = (msg.get("text") or "").strip()
        if not text:
            return None
        chat = msg.get("chat") or {}
        user = msg.get("from") or {}
        name = (user.get("first_name") or "") + (
            f" {user.get('last_name')}" if user.get("last_name") else "")
        return int(chat["id"]), text, name.strip() or "کاربر", (
            user.get("username") or "")
    except Exception:
        return None


def is_allowed(username: str, user_id: Any, allow: List[str]) -> bool:
    """چک لیست سفید. خالی = همه مجازند."""
    if not allow:
        return True
    uname = (username or "").lower().lstrip("@")
    ids = {a.strip().lower().lstrip("@") for a in allow if a.strip()}
    return uname in ids or str(user_id or "") in ids


@ChannelRegistry.register("telegram")
class TelegramBot:
    channel_id = "telegram"

    def __init__(self, token: str, agent: Optional[str] = None,
                 allow: Optional[List[str]] = None) -> None:
        self.token = token
        self.agent = agent
        self.allow = allow or []
        self._rt = None  # KhorshidRuntime تنبل

    # ------------------------------------------------------------- API ---
    def _api(self, method: str, payload: Dict[str, Any],
             timeout: float = 60.0) -> Dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{API}{self.token}/{method}", data=data,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                detail = ""
            raise RuntimeError(f"خطای تلگرام {e.code}: {detail}")

    def me(self) -> Dict[str, Any]:
        return self._api("getMe", {})

    def get_updates(self, offset: int = 0, timeout: int = 50) -> List[Dict[str, Any]]:
        try:
            d = self._api("getUpdates", {"offset": offset, "timeout": timeout,
                                         "allowed_updates": ["message", "edited_message"]},
                          timeout=timeout + 15)
        except Exception as e:
            print(f"⚠️ getUpdates: {e}")
            return []
        return d.get("result", []) if d.get("ok") else []

    def send(self, chat_id: int, text: str) -> None:
        for i, part in enumerate(chunk_message(text)):
            try:
                self._api("sendMessage", {"chat_id": chat_id, "text": part or "…"})
            except Exception as e:
                print(f"⚠️ ارسال پیام {i}: {e}")
            if i:
                time.sleep(0.3)

    def typing(self, chat_id: int) -> None:
        try:
            self._api("sendChatAction", {"chat_id": chat_id, "action": "typing"},
                      timeout=10)
        except Exception:
            pass

    # ------------------------------------------------------------ منطق ---
    def _runtime(self):
        if self._rt is None:
            from ultimate_khorshid.runtime import KhorshidRuntime
            from ultimate_khorshid.core.config import load_config
            self._rt = KhorshidRuntime(load_config())
        return self._rt

    def answer(self, text: str) -> str:
        """جواب یک پیام متنی (دستور یا سؤال آزاد)."""
        cmd, _arg = parse_command(text)
        if cmd in ("start", "help"):
            return HELP_TEXT
        if cmd == "agents":
            from ultimate_khorshid.runtime import list_agents
            return "🤖 ایجنت‌ها:\n" + "\n".join(f"• {a}" for a in list_agents())
        if cmd == "tools":
            from ultimate_khorshid.runtime import list_tools
            names = sorted(list_tools())
            return f"🔧 {len(names)} ابزار:\n" + ", ".join(names[:60]) + (
                "…" if len(names) > 60 else "")
        if cmd == "doctor":
            import io
            from contextlib import redirect_stdout
            from ultimate_khorshid.cli.main import cmd_doctor
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    cmd_doctor(None)
                return buf.getvalue()[:3500]
            except Exception as e:
                return f"❌ {e}"
        if cmd:
            return f"دستور /{cmd} را نمی‌شناسم قربان. /help را ببین. 🤔"
        try:
            r = self._runtime().ask(text, agent=self.agent)
            return r.content[:10000] or "(پاسخ خالی)"
        except Exception as e:
            return f"❌ خطا: {e}"

    def handle_update(self, update: Dict[str, Any]) -> Optional[int]:
        """پردازش یک update. آیدی update را برمی‌گرداند (برای offset)."""
        uid = update.get("update_id")
        got = extract_message(update)
        if not got:
            return uid
        chat_id, text, name, username = got
        msg = update.get("message") or {}
        user_id = (msg.get("from") or {}).get("id")
        if not is_allowed(username, user_id, self.allow):
            print(f"⛔ پیام از کاربر غیرمجاز رد شد: {name} (@{username})")
            return uid
        print(f"📩 {name}: {text[:80]}")
        self.typing(chat_id)
        try:
            self.send(chat_id, self.answer(text))
        except Exception as e:
            print(f"⚠️ {e}")
        return uid


def _state_path() -> Path:
    p = Path.home() / ".ultimate-jarvis" / "telegram.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def run_polling(token: str, agent: Optional[str] = None,
                allow: Optional[List[str]] = None) -> None:
    """حلقه long-polling تلگرام (دیمون)."""
    bot = TelegramBot(token, agent=agent, allow=allow)
    try:
        me = bot.me().get("result", {})
        print(f"📱 ربات وصل شد: @{me.get('username', '?')} ({me.get('first_name', '')})")
    except Exception as e:
        print(f"❌ اتصال به تلگرام نشد: {e}")
        print("   توکن را چک کن (از @BotFather) و اینترنت را بررسی کن.")
        return
    try:
        offset = int(json.loads(_state_path().read_text(encoding="utf-8")).get("offset", 0))
    except Exception:
        offset = 0
    print("👂 گوش دادن به پیام‌ها... (توقف: Ctrl+C)")
    backoff = 0
    try:
        while True:
            try:
                updates = bot.get_updates(offset)
                backoff = 0
                for u in updates:
                    try:
                        uid = bot.handle_update(u)
                    except Exception as e:
                        print(f"⚠️ پردازش update: {e}")
                        uid = u.get("update_id")
                    if uid is not None:
                        offset = max(offset, uid + 1)
                try:
                    _state_path().write_text(json.dumps({"offset": offset}),
                                             encoding="utf-8")
                except Exception:
                    pass
            except KeyboardInterrupt:
                raise
            except Exception as e:
                backoff = min(backoff + 5, 60)
                print(f"❌ خطای حلقه (تلاش مجدد پس از {backoff} ثانیه): {e}")
                time.sleep(backoff)
    except KeyboardInterrupt:
        print("\n👋 ربات تلگرام خاموش شد.")
