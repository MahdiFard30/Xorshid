"""تست آپدیت نهایی ۲.۰ — آفلاین‌امن (تست‌های زنده در test_live.py)."""

import io
import json
import threading
import urllib.request
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# ---------------------------------------------------------- هواشناسی ---
def test_weather_pure():
    from ultimate_khorshid.tools.weather import CITIES_FA, describe_wmo
    assert CITIES_FA["تهران"] == "Tehran" and CITIES_FA["مشهد"] == "Mashhad"
    assert "صاف" in describe_wmo(0) and "برف" in describe_wmo(73)
    assert "رعد" in describe_wmo(95) and describe_wmo(999) == "نامشخص"


def test_weather_tool_registered():
    from ultimate_khorshid.runtime import KhorshidRuntime
    from ultimate_khorshid.core.config import KhorshidConfig
    rt = KhorshidRuntime(KhorshidConfig())
    assert "weather" in rt.tool_names and "notify" in rt.tool_names


def test_mock_weather_routing():
    from ultimate_khorshid.engine.mock import MockEngine
    m = MockEngine()
    avail = {"weather", "crypto_price"}
    c = m._plan_tool_call("هوای تهران چطوره؟", avail)
    assert c and c["name"] == "weather" and "تهران" in c["arguments"]
    c = m._plan_tool_call("هوا چطوره؟", avail)
    assert c and c["name"] == "weather"
    assert m._plan_tool_call("هوای تازه می‌خوام برم بیرون", avail) is None
    assert m._plan_tool_call("دمای CPU چنده؟", avail) is None


def test_mock_filesearch_no_fake_pattern():
    from ultimate_khorshid.engine.mock import MockEngine
    m = MockEngine()
    c = m._plan_tool_call("پیدا کن در پوشه src", {"file_search"})
    assert c is None  # بدون الگو: هیچ جست‌وجوی جعلی!
    c = m._plan_tool_call("جستجو کلمه سلام در فایل notes.txt", {"file_search"})
    assert c and "سلام" in c["arguments"]


# -------------------------------------------------------------- اعلان ---
def test_notify_tool():
    from ultimate_khorshid.tools.notify import NotifyTool
    buf = io.StringIO()
    with redirect_stdout(buf):
        r = NotifyTool().execute(message="سلام تست")
    assert r.success and "اعلان" in r.content
    r = NotifyTool().execute(message="  ")
    assert not r.success


# ------------------------------------------------------- وب + تایتل ---
HTML = ("<html><head><title>صفحه آزمایشی خورشید</title></head>"
        "<body><h1>سلام</h1><p>متن بدنه برای تست.</p></body></html>")


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_web_fetch_extracts_title():
    from ultimate_khorshid.tools.web import WebFetchTool
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/"
        r = WebFetchTool().execute(url=url)
        assert r.success and "صفحه آزمایشی خورشید" in r.content
        assert "متن بدنه" in r.content
    finally:
        srv.shutdown()


# -------------------------------------------------------------- ستاپ ---
def test_setup_wizard_noninteractive(tmp_path, monkeypatch):
    import ultimate_khorshid.core.settings as S
    import ultimate_khorshid.cli.setup_wizard as W
    monkeypatch.setattr(S, "settings_path", lambda: tmp_path / "s.json")
    rc = W.run_setup(engine="mock", extras="none", hotkey="alt", yes=True,
                     base_dir=tmp_path, install=False)
    assert rc == 0
    cfg = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert 'preferred_engine = "mock"' in cfg
    assert json.loads((tmp_path / "s.json").read_text())["hotkey"] == "alt"


def test_setup_toml_builders():
    from ultimate_khorshid.cli.setup_wizard import build_config_toml
    g = build_config_toml("gemini", "gemini/gemini-2.0-flash", "KEY123")
    assert "[engine.gemini]" in g and 'api_key = "KEY123"' in g
    o = build_config_toml("openai_compat", "openai/gpt-4o-mini", "SK",
                          "https://x.ai/v1")
    assert "https://x.ai/v1" in o and 'model = "gpt-4o-mini"' in o
    m = build_config_toml("mock", "mock/smart")
    assert 'default = "mock"' in m


# -------------------------------------------------- دیمون هات‌کی ---
def test_hotkey_daemon_mgmt(tmp_path, monkeypatch):
    import os
    import ultimate_khorshid.hotkey.manager as M
    monkeypatch.setattr(M, "_daemon_base", lambda: tmp_path)
    st = M.daemon_status()
    assert st["running"] is False and "پوش‌تو‌تاک" in st["describe"]
    assert "روشن نیست" in M.stop_daemon()
    (tmp_path / "hotkey.pid").write_text("999999999")
    assert "pid" in M.stop_daemon()  # pid مرده: پاک می‌شود
    assert not (tmp_path / "hotkey.pid").exists()
    (tmp_path / "hotkey.pid").write_text(str(os.getpid()))
    try:
        assert M.daemon_status()["running"] is True  # خودمان زنده‌ایم!
    finally:
        (tmp_path / "hotkey.pid").unlink(missing_ok=True)


# ------------------------------------------------------------ تلگرام ---
def test_telegram_pure_helpers():
    from ultimate_khorshid.channels.telegram import (chunk_message, extract_message,
                                                   is_allowed, parse_command)
    assert chunk_message("سلام") == ["سلام"]
    big = "x" * 9000
    assert len(chunk_message(big, 4000)) == 3
    assert parse_command("/agents") == ("agents", "")
    assert parse_command("/start@MyBot hi") == ("start", "hi")
    assert parse_command("تتر چنده؟") == ("", "تتر چنده؟")
    upd = {"update_id": 1, "message": {"text": "سلام",
           "chat": {"id": 7}, "from": {"first_name": "علی", "username": "ali"}}}
    assert extract_message(upd) == (7, "سلام", "علی", "ali")
    assert extract_message({"message": {"photo": [1]}}) is None
    assert is_allowed("ali", 7, []) is True
    assert is_allowed("ali", 7, ["@ali"]) is True
    assert is_allowed("ali", 7, ["999"]) is False
    assert is_allowed("", 7, ["7"]) is True


def test_telegram_answers_and_channel():
    from ultimate_khorshid.channels.telegram import TelegramBot
    from ultimate_khorshid.core.registry import ChannelRegistry
    assert ChannelRegistry.contains("telegram")
    bot = TelegramBot("FAKE", agent="simple")
    assert "/help" in bot.answer("/start") or "دستورات" in bot.answer("/start")
    assert "computer" in bot.answer("/agents")
    assert "ابزار" in bot.answer("/tools")
    assert "ابزارها" in bot.answer("/doctor")
    assert "نمی‌شناسم" in bot.answer("/foobar")

    class FakeR:
        def ask(self, q, agent=None):
            class R:
                content = f"echo:{q}"
            return R()
    bot._rt = FakeR()
    bot.allow = ["ali"]
    sent = []
    bot.send = lambda cid, txt: sent.append((cid, txt))
    upd = {"update_id": 5, "message": {"text": "تتر چنده",
           "chat": {"id": 9}, "from": {"id": 1, "first_name": "ع",
                                        "username": "ali"}}}
    assert bot.handle_update(upd) == 5
    assert sent and "echo:تتر چنده" in sent[0][1]
    bot.allow = ["boss"]
    sent.clear()
    bot.handle_update(upd)  # غیرمجاز → بدون ارسال
    assert sent == []


# --------------------------------------------------------------- متا ---
def test_version_and_parsers():
    from ultimate_khorshid import __version__
    from ultimate_khorshid.cli.main import build_parser
    assert __version__ == "2.0.0"
    p = build_parser()
    assert p.parse_args(["setup", "--engine", "gemini", "--yes"]).engine == "gemini"
    a = p.parse_args(["telegram", "--token", "T", "--allow", "1,2"])
    assert (a.token, a.allow) == ("T", "1,2")
    assert p.parse_args(["hotkey", "--stop"]).stop is True
    try:
        p.parse_args(["--version"])
        raise AssertionError("باید SystemExit می‌داد")
    except SystemExit as e:
        assert e.code == 0


def test_package_hygiene():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "ultimate_khorshid"
    missing = [d.name for d in root.iterdir()
               if d.is_dir() and d.name != "__pycache__"
               and not (d / "__init__.py").exists()]
    assert missing == [], missing
    from ultimate_khorshid.runtime import list_agents, list_tools
    from ultimate_khorshid.skills.manager import SkillManager
    assert len(list_tools()) >= 51, len(list_tools())
    assert len(list_agents()) >= 13, len(list_agents())
    assert len(SkillManager().load_all()) >= 9


def test_vision_endpoint():
    import threading
    from http.server import ThreadingHTTPServer
    from ultimate_khorshid.server.app import Handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        req = urllib.request.Request(base + "/api/vision", data=b"{}",
                                     headers={"Content-Type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=30).read())
        assert "result" in d  # بدون کلید: پیام راهنمای تمیز
    finally:
        srv.shutdown()
