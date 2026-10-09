"""تست کنترل کامل (دسکتاپ/مرورگر/کریپتو/داشبورد) — آفلاین‌امن."""

import json
import urllib.request


def test_crypto_helpers():
    from ultimate_khorshid.tools.crypto import detect_coin, fmt
    assert detect_coin("تتر چنده؟")[0] == "USDT"
    assert detect_coin("قیمت بیت کوین")[0] == "BTC"
    assert detect_coin("BTC price")[0] == "BTC"
    assert detect_coin("دلار") is None  # دلار ≠ رمزارز (مسیر جدا دارد)
    assert detect_coin("سلام") is None
    assert fmt(230000) == "230,000"
    assert fmt(0.9994) == "0.9994"


def test_browser_tool_never_crashes():
    from ultimate_khorshid.core.types import ToolCall
    from ultimate_khorshid.runtime import KhorshidRuntime
    from ultimate_khorshid.core.config import KhorshidConfig
    rt = KhorshidRuntime(KhorshidConfig())
    r = rt.executor.execute(ToolCall(name="browser_open",
                                     arguments='{"url": "http://127.0.0.1:9/"}'))
    assert r.success is False  # یا نصب نیست یا وصل نمی‌شود — مهم: کرش نمی‌کند
    assert len(r.content) > 10


def test_desktop_tools_registered_and_safe():
    from ultimate_khorshid.runtime import list_tools
    tools = list_tools()
    for name in ("screenshot", "mouse_click", "type_text", "key_press",
                 "open_url", "open_app", "vision_ask", "crypto_price",
                 "browser_google_search", "speak", "listen", "display_info"):
        assert name in tools, name


def test_screenshot_bytes_fallback():
    from ultimate_khorshid.tools.desktop import get_screenshot_bytes
    data, mime = get_screenshot_bytes()
    assert mime in ("image/png", "image/svg+xml")
    assert len(data) > 100


def test_dashboard_exists():
    from pathlib import Path
    fp = Path("ultimate_khorshid/server/dashboard.html")
    if not fp.exists():
        fp = Path(__file__).resolve().parents[1] / "ultimate_khorshid" / "server" / "dashboard.html"
    html = fp.read_text(encoding="utf-8")
    for marker in ("خورشید نهایی", "/api/chat", "webkitSpeechRecognition",
                   "/api/screenshot", "Intl.DateTimeFormat"):
        assert marker in html, marker


def test_server_api():
    import threading
    from http.server import ThreadingHTTPServer
    from ultimate_khorshid.server.app import Handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        status = json.loads(urllib.request.urlopen(base + "/api/status", timeout=10).read())
        assert status["tools"] >= 40, status
        agents = json.loads(urllib.request.urlopen(base + "/api/agents", timeout=10).read())
        assert "computer" in agents["agents"]
        dash = urllib.request.urlopen(base + "/", timeout=10).read().decode("utf-8")
        assert "خورشید نهایی" in dash
        # چت آفلاین سرتاسری
        req = urllib.request.Request(base + "/api/chat",
                                     data=json.dumps({"message": "حساب کن: 6*7"}).encode(),
                                     headers={"Content-Type": "application/json"})
        chat = json.loads(urllib.request.urlopen(req, timeout=30).read())
        assert chat["ok"] and "42" in chat["reply"], chat
    finally:
        srv.shutdown()
