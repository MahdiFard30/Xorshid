"""تست هات‌کی/تنظیمات/آزمون/APIهای جدید — آفلاین‌امن."""

import json
import urllib.request


def test_hotkey_parse():
    from ultimate_khorshid.hotkey.manager import parse_combo, is_single_modifier, describe
    mods, keys = parse_combo("Ctrl+Shift+J")
    assert mods == frozenset({"ctrl", "shift"}) and keys == frozenset({"j"})
    assert is_single_modifier("ctrl") is True
    assert is_single_modifier("ctrl+shift+j") is False
    assert "پوش‌تو‌تاک" in describe("ctrl") and "نگه دار" in describe("ctrl")
    assert "ctrl+shift+j" in describe("Ctrl+Shift+J")


def test_hotkey_manager_no_pynput_safe():
    from ultimate_khorshid.hotkey.manager import HotkeyManager
    m = HotkeyManager("ctrl+shift+j")
    assert m.combination == "ctrl+shift+j"
    import importlib.util
    has = importlib.util.find_spec("pynput") is not None
    if not has:
        try:
            m.start_background()
            raise AssertionError("باید خطای نصب می‌داد")
        except RuntimeError as e:
            assert "pynput" in str(e)


def test_settings_roundtrip(tmp_path, monkeypatch):
    import ultimate_khorshid.core.settings as S
    monkeypatch.setattr(S, "settings_path", lambda: tmp_path / "s.json")
    assert S.get_settings()["hotkey"] == "ctrl"
    S.set_settings(hotkey="alt", model="gemini/gemini-2.0-flash")
    s = S.get_settings()
    assert s["hotkey"] == "alt" and s["model"] == "gemini/gemini-2.0-flash"


def test_quiz_agent_builds():
    from ultimate_khorshid.runtime import KhorshidRuntime
    from ultimate_khorshid.core.config import KhorshidConfig
    rt = KhorshidRuntime(KhorshidConfig())
    ag = rt.build_agent("quiz")
    assert ag.agent_id == "quiz"
    # تطبیق جواب
    assert ag._match("تهران", [{"i": "0", "label": "تهران"},
                               {"i": "1", "label": "مشهد"}])["i"] == "0"
    assert ag._match("ب", [{"i": "0", "label": "xx"},
                           {"i": "1", "label": "yy"}])["i"] == "1"


def test_quiz_no_browser_graceful():
    from ultimate_khorshid.runtime import KhorshidRuntime
    from ultimate_khorshid.core.config import KhorshidConfig
    from ultimate_khorshid.agents.base import AgentContext
    from ultimate_khorshid.core.types import Conversation
    rt = KhorshidRuntime(KhorshidConfig())
    conv = Conversation()
    conv.add("user", "سوال‌ها را جواب بده")
    r = rt.build_agent("quiz").run(AgentContext(conversation=conv, tools=rt.tool_names))
    assert isinstance(r.content, str) and len(r.content) > 10


def test_new_server_endpoints():
    import threading
    from http.server import ThreadingHTTPServer
    from ultimate_khorshid.server.app import Handler

    def post(url, obj):
        req = urllib.request.Request(url, data=json.dumps(obj).encode(),
                                     headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=30).read())

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{port}"
        s = json.loads(urllib.request.urlopen(base + "/api/settings", timeout=10).read())
        assert s["ok"] and "hotkey" in s["settings"]
        s2 = post(base + "/api/settings", {"voice": "Charon"})
        assert s2["settings"]["voice"] == "Charon"
        post(base + "/api/settings", {"voice": "Kore"})  # برگرداندن
        b = post(base + "/api/browser", {"op": "snapshot"})
        assert "ok" in b  # بدون playwright خطای تمیز می‌دهد
        h = json.loads(urllib.request.urlopen(base + "/api/history?limit=3", timeout=10).read())
        assert "items" in h
        dash = urllib.request.urlopen(base + "/", timeout=10).read().decode("utf-8")
        for marker in ("تنظیمات", "حل آزمون سایت", "تاریخچه گفت‌وگو", "مرورگر واقعی", "set-hotkey"):
            assert marker in dash, marker
    finally:
        srv.shutdown()


def _ptt_mgr(combo="ctrl", **kw):
    """مدیر پوش‌تو‌تاک با ضبط جعلی — بدون میکروفون/کیبورد واقعی."""
    from ultimate_khorshid.hotkey.manager import HotkeyManager
    got = []
    kw.setdefault("hold_threshold", 0)
    kw.setdefault("max_record", 0)
    m = HotkeyManager(combo, on_text=got.append, **kw)
    m._start_capture = lambda: True
    m._capture_transcript = lambda: "تتر چنده"
    m._got = got
    return m


def test_ptt_hold_release_triggers():
    m = _ptt_mgr()
    m.press("ctrl")
    assert m._armed is True
    m.release("ctrl")
    assert m._got == ["تتر چنده"]


def test_ptt_quick_tap_does_nothing():
    m = _ptt_mgr(hold_threshold=999)
    m.press("ctrl")
    assert m._armed is False  # هنوز آستانه رد نشده
    m.release("ctrl")  # ول کردن سریع → هیچی
    assert m._got == []


def test_ptt_ctrl_c_cancels():
    m = _ptt_mgr()
    m.press("ctrl")
    assert m._armed is True
    m.press("c")  # شرتکات وسط نگه داشتن → لغو
    m.release("c")
    m.release("ctrl")
    assert m._got == []


def test_ptt_combo_hold_release():
    m = _ptt_mgr("ctrl+shift+j")
    m.press("ctrl")
    m.press("shift")
    assert m._armed is False  # هنوز کامل نشده
    m.press("j")
    assert m._armed is True
    m.release("j")  # ول کردن بخشی از ترکیب → پردازش
    assert m._got == ["تتر چنده"]
    m.release("ctrl")
    m.release("shift")


def test_ptt_dashboard_action_no_recording():
    from ultimate_khorshid.hotkey.manager import HotkeyManager
    import ultimate_khorshid.hotkey.manager as M
    opened = []
    orig = M.action_open_dashboard
    M.action_open_dashboard = lambda port=8899: opened.append(port)
    try:
        m = HotkeyManager("ctrl", action="dashboard", hold_threshold=0, max_record=0)
        started = []
        m._start_capture = lambda: started.append(1) or True
        m.press("ctrl")
        assert started == []  # اکشن داشبورد ضبط نمی‌خواهد
        m.release("ctrl")
        assert opened == [8899]
    finally:
        M.action_open_dashboard = orig
