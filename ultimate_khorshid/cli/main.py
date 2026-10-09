"""CLI خورشید نهایی — khorshid (صرفاً argparse، بدون وابستگی)."""

from __future__ import annotations

import argparse
import json
import os
import sys


def _confirm(msg: str) -> bool:
    try:
        ans = input(f"⚠️  {msg} [y/N]: ").strip().lower()
        return ans in ("y", "yes", "بله", "آره")
    except (EOFError, KeyboardInterrupt):
        return False


def cmd_chat(args) -> int:
    from ultimate_khorshid.core.config import load_config
    from ultimate_khorshid.runtime import KhorshidRuntime
    cfg = load_config(args.config)
    if args.agent:
        cfg.agent.default_agent = args.agent
    rt = KhorshidRuntime(cfg, confirm_callback=_confirm, interactive=True)
    print(f"🤖 موتور: {rt.engine.engine_id} | مدل: {rt.model} | ایجنت: {args.agent or cfg.agent.default_agent}")
    rt.chat_loop(agent=args.agent)
    return 0


def cmd_ask(args) -> int:
    from ultimate_khorshid.core.config import load_config
    from ultimate_khorshid.runtime import KhorshidRuntime
    cfg = load_config(args.config)
    rt = KhorshidRuntime(cfg, confirm_callback=None if args.yes else _confirm,
                       interactive=False if args.yes else True)
    meta = {"resume_id": args.resume} if getattr(args, "resume", "") else None
    if getattr(args, "stream", False):
        r = rt.ask(args.query, agent=args.agent, stream=True, extra_meta=meta,
                   on_token=lambda d: print(d, end="", flush=True))
        print()
    else:
        r = rt.ask(args.query, agent=args.agent, extra_meta=meta)
        print(r.content)
    if args.verbose:
        print(f"\n---\nturns={r.turns} tools={[t.tool_name for t in r.tool_results]}")
    return 0


def cmd_agents(_args) -> int:
    from ultimate_khorshid.runtime import list_agents
    print("🤖 ایجنت‌ها:")
    desc = {"computer": "⭐ کامپیوتری همه‌کاره (پیش‌فرض)", "orchestrator": "حلقه function-calling",
            "react": "Thought/Action/Observation متنی", "codeact": "تولید+اجرای کد پایتون",
            "planner": "برنامه‌ریز چندمرحله‌ای", "researcher": "تحقیق عمیق با استناد",
            "autonomous": "خودمختار هدف‌محور", "simple": "گپ ساده بدون ابزار",
            "quiz": "📝 حل خودکار آزمون سایت"}
    for a in list_agents():
        print(f"  • {a:14s} {desc.get(a, '')}")
    return 0


def cmd_tools(args) -> int:
    from ultimate_khorshid.runtime import _ensure_imports, list_tools
    from ultimate_khorshid.core.registry import ToolRegistry
    _ensure_imports()
    if args.call:
        from ultimate_khorshid.tools.base import ToolExecutor
        from ultimate_khorshid.core.types import ToolCall
        tools = [cls() for _, cls in ToolRegistry.items()]
        ex = ToolExecutor(tools, interactive=not args.yes,
                          confirm_callback=None if args.yes else _confirm)
        try:
            params = json.loads(args.params or "{}")
        except Exception as e:
            print(f"JSON نامعتبر: {e}")
            return 1
        r = ex.execute(ToolCall(name=args.call, arguments=json.dumps(params, ensure_ascii=False)))
        print(f"{'✅' if r.success else '❌'}\n{r.content}")
        return 0 if r.success else 1
    print("🔧 ابزارها:")
    for n, d in sorted(list_tools().items()):
        print(f"  • {n:15s} {d}")
    return 0


def cmd_memory(args) -> int:
    from ultimate_khorshid.memory.store import get_memory
    mem = get_memory()
    if args.add:
        mid = mem.add(args.add, "cli")
        print(f"🧠 ذخیره شد (#{mid})")
    elif args.search:
        hits = mem.search(args.search, args.limit)
        if not hits:
            print("چیزی پیدا نشد.")
        for h in hits:
            print(f"#{h.id} [{h.created}] {h.text[:250]}")
    elif args.list:
        for h in mem.list_recent(args.limit):
            print(f"#{h.id} [{h.created}] {h.text[:200]}")
    elif args.ingest:
        from ultimate_khorshid.memory.ingest import ingest_directory, ingest_file
        p = os.path.expanduser(args.ingest)
        n = ingest_directory(p) if os.path.isdir(p) else ingest_file(p)
        print(f"📚 {n} تکه ذخیره شد.")
    else:
        print(f"حافظه: {mem.count()} رکورد.")
    return 0


def cmd_skill(args) -> int:
    from ultimate_khorshid.skills.manager import SkillManager
    sm = SkillManager([os.path.expanduser("~/.ultimate-jarvis/skills"),
                       os.path.expanduser("./skills")])
    sm.load_all()
    if args.show:
        sk = sm.get(args.show)
        if not sk:
            print("پیدا نشد.")
            return 1
        print(f"# {sk.name}\n{sk.description}\n\n{sk.body[:3000]}")
        return 0
    print("🎓 مهارت‌ها:\n" + sm.catalog_text())
    return 0


def cmd_serve(args) -> int:
    from ultimate_khorshid.server.app import serve
    serve(args.host, args.port)
    return 0


def cmd_ui(args) -> int:
    from ultimate_khorshid.server.app import serve
    serve(args.host, args.port, open_browser=not args.no_browser)
    return 0


def cmd_schedule(args) -> int:
    from ultimate_khorshid.scheduler.scheduler import TaskScheduler, TaskStore
    from ultimate_khorshid.runtime import KhorshidRuntime
    from ultimate_khorshid.core.config import load_config
    store = TaskStore()
    if args.add:
        tid = store.add(args.name or "task", args.add, args.agent, args.every)
        print(f"⏰ تسک #{tid} هر {args.every} ثانیه ثبت شد.")
        return 0
    if args.list or args.ls:
        tasks = store.list()
        if not tasks:
            print("(تسکی نیست)")
        for t in tasks:
            print(f"#{t.id} [{'ON' if t.enabled else 'OFF'}] {t.name} — هر {t.every_seconds}s — ایجنت:{t.agent}\n   {t.prompt[:120]}")
        return 0
    if args.remove:
        store.remove(args.remove)
        print("حذف شد.")
        return 0
    if args.run:
        rt = KhorshidRuntime(load_config())
        sched = TaskScheduler(store, lambda prompt, agent: rt.ask(prompt, agent=agent).content)
        print("⏰ زمان‌بند روشن شد (Ctrl+C برای توقف)...")
        sched.start()
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            sched.stop()
            print("\nخاموش شد.")
        return 0
    print("استفاده: schedule --add 'متن' --every 3600 | --list | --run | --remove ID")
    return 0


def cmd_voice(args) -> int:
    from ultimate_khorshid.core.config import load_config
    from ultimate_khorshid.voice.loop import voice_chat
    cfg = load_config(args.config)
    voice_chat(cfg, agent=args.agent, seconds=args.seconds, push=args.push,
               no_tts=args.no_tts, once=args.once, voice=args.voice or cfg.engine.voice)
    return 0


def cmd_speak(args) -> int:
    from ultimate_khorshid.voice.engines import speak_text
    from ultimate_khorshid.core.config import load_config
    cfg = load_config(args.config)
    wav = speak_text(args.text, out=args.out or "", voice=args.voice or cfg.engine.voice)
    if wav:
        print(f"🔊 ذخیره شد: {wav}")
    return 0


def cmd_listen(args) -> int:
    from ultimate_khorshid.voice import audio as A
    from ultimate_khorshid.voice.engines import transcribe_file
    wav = A.tmp_wav("khorshid_listen")
    print(f"🎤 {args.seconds} ثانیه حرف بزنید...")
    try:
        A.record_fixed(wav, seconds=args.seconds)
    except Exception as e:
        print(f"❌ {e}")
        return 1
    print("🧠 در حال رونویسی...")
    try:
        print(f"📝 {transcribe_file(wav)}")
    except Exception as e:
        print(f"❌ {e}")
        return 1
    return 0


def cmd_hotkey(args) -> int:
    from ultimate_khorshid.core.settings import get_settings, set_settings
    from ultimate_khorshid.hotkey.manager import (daemon_status, describe, run_daemon,
                                                push_to_talk_once, stop_daemon)
    if args.stop:
        print(stop_daemon())
        return 0
    if args.status:
        st = daemon_status()
        state = f"\U0001f7e2 روشن (pid={st['pid']})" if st["running"] else "\u26aa خاموش"
        print(f"دیمون پوش‌تو‌تاک: {state} | {st['describe']}")
        return 0
    if args.set:
        s = set_settings(hotkey=args.set)
        print(f"⌨️ هات‌کی ذخیره شد: {describe(s['hotkey'])}")
        if not args.daemon and not args.test:
            return 0
    if args.action:
        set_settings(hotkey_action=args.action)
    s = get_settings()
    print(f"🤖 احضار سریع خورشید با {describe(s['hotkey'])} (اکشن: {s['hotkey_action']}).")
    if args.test:
        q = push_to_talk_once(s["hotkey"], hold=args.hold, max_record=args.max)
        if q:
            print(f"📝 شنیده شد: {q}")
        return 0
    if args.daemon:
        run_daemon(s["hotkey"], s["hotkey_action"], hold=args.hold, max_record=args.max)
    else:
        print("💡 برای روشن ماندن: khorshid hotkey --daemon")
        print("💡 برای یک تست سریع: khorshid hotkey --test")
    return 0


def cmd_quiz(args) -> int:
    from ultimate_khorshid.core.config import load_config
    from ultimate_khorshid.runtime import KhorshidRuntime
    from ultimate_khorshid.agents.base import AgentContext
    from ultimate_khorshid.core.types import Conversation
    cfg = load_config(args.config)
    rt = KhorshidRuntime(cfg)
    conv = Conversation()
    conv.add("user", args.query or f"سوال‌های این صفحه را جواب بده: {args.url}")
    ctx = AgentContext(conversation=conv, tools=rt.tool_names,
                       metadata={"url": args.url or "", "max_questions": args.max,
                                 "submit": args.submit})
    r = rt.build_agent("quiz").run(ctx)
    print(r.content)
    return 0


def cmd_doctor(_args) -> int:
    import platform
    print("🩺 Ultimate Khorshid Doctor\n")
    print(f"  پایتون: {platform.python_version()} | سیستم: {platform.system()} {platform.release()}")
    from ultimate_khorshid.runtime import list_agents, list_tools
    from ultimate_khorshid.skills.manager import SkillManager
    from ultimate_khorshid import __version__
    try:
        n_skills = len(SkillManager().load_all())
    except Exception:
        n_skills = 0
    print(f"  نسخه: {__version__}")
    print(f"  ایجنت‌ها: {len(list_agents())} | ابزارها: {len(list_tools())} | مهارت‌ها: {n_skills}")
    # موتورها
    try:
        from ultimate_khorshid.engine.ollama import OllamaEngine
        h = OllamaEngine().health()
        print(f"  ollama: {'✅ ' + str(h.get('models', [])) if h['ok'] else '❌ ' + str(h.get('error', ''))[:80]}")
    except Exception as e:
        print(f"  ollama: ❌ {e}")
    key = os.environ.get("OPENAI_API_KEY", "")
    print(f"  openai_api_key: {'✅ تنظیم شده' if key else '⚪ تنظیم نشده (می‌توانی با mock/ollama کار کنی)'}")
    gkey = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
    print(f"  gemini_api_key: {'✅ تنظیم شده' if gkey else '⚪ تنظیم نشده (از aistudio.google.com بگیر)'}")
    tg = os.environ.get("KHORSHID_TELEGRAM_TOKEN", "")
    print(f"  telegram: {'✅ توکن تنظیم شده' if tg else '⚪ توکن تنظیم نشده (اختیاری — کنترل خورشید از موبایل)'}")
    try:
        from ultimate_khorshid.voice.audio import backends
        b = backends()
        rec = "✅" if (b["arecord"] or b["ffmpeg"] or b["sox"] or b["sounddevice"]) else "❌"
        play = "✅" if (b["aplay"] or b["afplay"] or b["ffmpeg"]) else "❌"
        print(f"  voice: ضبط {rec} | پخش {play} | TTSآفلاین {'✅' if b['espeak'] else '⚪'}")
    except Exception:
        pass
    try:
        import importlib.util as _iu
        has_pw = _iu.find_spec("playwright") is not None
        has_gui = _iu.find_spec("pyautogui") is not None or _iu.find_spec("mss") is not None
        print(f"  browser(playwright): {'✅ نصب است' if has_pw else '⚪ نصب نیست (playwright install chromium)'}")
        print(f"  desktop(pyautogui/mss): {'✅ نصب است' if has_gui else '⚪ نصب نیست (pip install -e \".[desktop]\")'}")
        has_hk = _iu.find_spec("pynput") is not None
        print(f"  hotkey(pynput): {'✅ نصب است' if has_hk else '⚪ نصب نیست (pip install -e \".[hotkey]\")'}")
        try:
            from ultimate_khorshid.core.sandbox import detect_backend
            from ultimate_khorshid.core.vault import backend_name as _vb
            from ultimate_khorshid.voice.engines import stt_backends
            print(f"  sandbox(اجرای کد): ⚙️ {detect_backend()}")
            print(f"  vault: {'✅ os-keyring' if _vb() == 'os-keyring' else '⚪ config-file (پیشنهاد: pip install keyring)'}")
            _stt = stt_backends()
            print(f"  stt: {'✅ ' + ','.join(k for k, v in _stt.items() if v) if any(_stt.values()) else '❌ هیچ بک‌اندی'}")
        except Exception:
            pass
    except Exception:
        pass
    try:
        from ultimate_khorshid.memory.store import get_memory
        print(f"  حافظه: ✅ {get_memory().count()} رکورد")
    except Exception as e:
        print(f"  حافظه: ❌ {e}")
    print("\n💡 شروع: khorshid chat   |   مثال: khorshid ask 'ساعت چند است؟'")
    return 0


def cmd_init(args) -> int:
    import shutil
    from pathlib import Path
    src = Path(__file__).resolve().parents[2] / "configs" / f"{args.preset}.toml"
    dst = Path.home() / ".ultimate-jarvis" / "config.toml"
    if not src.exists():
        print(f"پریست پیدا نشد: {args.preset}")
        return 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)
    print(f"✅ کانفیگ «{args.preset}» در {dst} نصب شد.")
    return 0


def cmd_setup(args) -> int:
    from ultimate_khorshid.cli.setup_wizard import run_setup
    return run_setup(engine=args.engine, api_key=args.key or None,
                     extras=args.extras, hotkey=args.hotkey, yes=args.yes)


def cmd_telegram(args) -> int:
    import os
    token = args.token or os.environ.get("KHORSHID_TELEGRAM_TOKEN", "")
    if not token:
        print("\u274c توکن ربات لازم است. ساخت ربات (\u06f2 دقیقه):")
        print("   1. در تلگرام به @BotFather پیام بده \u2192 /newbot")
        print("   2. توکن را بگیر و اجرا کن:")
        print("      khorshid telegram --token 123456:AAE...")
        print("      # یا: export KHORSHID_TELEGRAM_TOKEN=...")
        return 1
    allow = [a.strip() for a in (args.allow or "").split(",") if a.strip()]
    from ultimate_khorshid.channels.telegram import run_polling
    run_polling(token, agent=args.agent, allow=allow)
    return 0


def cmd_traces(args) -> int:
    from ultimate_khorshid.core.tracing import Tracer
    tr = Tracer()
    if args.clear:
        print(f"🗑 {tr.clear()} trace پاک شد.")
        return 0
    if args.show:
        d = tr.trace_detail(args.show)
        if not d:
            print("پیدا نشد.")
            return 1
        print(f"🔍 {d['id']} | {d['name']} | {d['ts']} | {d['status']}")
        for s in d["spans"]:
            print(f"  • [{s['kind']}] {s['name']} — {s['ms']}ms {s['status']}")
        for u in d["usage"]:
            print(f"  💰 {u['engine']}/{u['model']}: in={u['in']} out={u['out']} ${u['cost']}")
        return 0
    rows = tr.recent_traces(args.limit)
    if not rows:
        print("(تریسی ثبت نشده — اول یک khorshid ask بزن)")
        return 0
    for t in rows:
        print(f"  • {t['id']} | {t['name'][:38]:38} | {t['ts']} | {t['status']}")
    return 0


def cmd_costs(_args) -> int:
    from ultimate_khorshid.core.tracing import Tracer
    s = Tracer().cost_summary()
    print(f"💰 مجموع: ${s['cost_usd']} | ورودی: {s['tok_in']} | خروجی: {s['tok_out']} | تماس: {s['calls']}")
    for b in s["by_model"]:
        print(f"  • {b['model']}: ${b['cost_usd']} ({b['calls']} تماس)")
    print("  (قیمت‌ها تقریبی‌اند)")
    return 0


def cmd_vault(args) -> int:
    from ultimate_khorshid.core import vault as V
    if args.set:
        import getpass
        try:
            v = getpass.getpass(f"مقدار {args.set}: ")
        except Exception:
            v = input(f"مقدار {args.set}: ")
        if not v.strip():
            print("خالی است.")
            return 1
        try:
            print(f"✅ در {V.set_secret(args.set, v.strip())} ذخیره شد.")
        except RuntimeError as e:
            print(f"❌ {e}")
            return 1
        return 0
    if args.get:
        v = V.get_secret(args.get)
        print(f"{args.get} = {'***' + v[-4:] if len(v) > 4 else ('(خالی)' if not v else '***')}")
        return 0
    print(f"🔐 بک‌اند: {V.backend_name()}")
    w = V.warn_if_plain()
    if w:
        print(w)
    return 0


def cmd_eval(args) -> int:
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    ev = root / "evals"
    if not ev.exists():
        print("پوشه evals نیست.")
        return 1
    cmd = [sys.executable, "-m", "pytest", str(ev), "-q"] + (["-k", args.k] if args.k else [])
    print(f"🧪 اجرا: {' '.join(cmd)}")
    return subprocess.run(cmd).returncode


def cmd_checkpoints(args) -> int:
    from ultimate_khorshid.core import checkpoint as Ck
    if args.clear:
        rid = None if args.clear == "__ALL__" else args.clear
        print(f"🗑 {Ck.clear(rid)} چک‌پوینت پاک شد.")
        return 0
    rows = Ck.list_runs()
    if not rows:
        print("(چک‌پوینتی نیست)")
        return 0
    for r in rows:
        print(f"  • {r['id']} | {r['saved_at']} | {', '.join(r['keys'][:6])}")
    print("ادامه: khorshid ask '...' --agent planner --resume <id>")
    return 0


def cmd_wake(args) -> int:
    from ultimate_khorshid.voice.wake import WakeListener
    kws = tuple(a.strip() for a in (args.keywords or "خورشید,khorshid").split(",") if a.strip())

    def _on_wake(kw):
        print(f"\n🤖 بله قربان؟ (شنیده شد: {kw})")
        if args.say:
            try:
                from ultimate_khorshid.voice.engines import speak_text
                speak_text("بله قربان؟")
            except Exception as e:
                print(f"⚠️ {e}")

    WakeListener(keywords=kws, threshold=args.threshold, on_wake=_on_wake).listen_forever()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="khorshid", description="🤖 ULTIMATE KHORSHID — ایجنت کامپیوتری فارسی")
    from ultimate_khorshid import __version__
    p.add_argument("--version", action="version", version=f"Ultimate Khorshid {__version__}")
    p.add_argument("--config", default=None, help="مسیر فایل کانفیگ TOML")
    sub = p.add_subparsers(dest="cmd")

    c = sub.add_parser("chat", help="گفت‌وگوی تعاملی")
    c.add_argument("--agent", default=None)

    c = sub.add_parser("ask", help="یک سؤال تکی")
    c.add_argument("query")
    c.add_argument("--agent", default=None)
    c.add_argument("--yes", "-y", action="store_true", help="بدون تأییدیه")
    c.add_argument("--verbose", "-v", action="store_true")
    c.add_argument("--stream", action="store_true", help="نمایش زنده توکن‌ها")
    c.add_argument("--resume", default="", help="ادامه پلن از چک‌پوینت (آیدی)")

    sub.add_parser("agents", help="لیست ایجنت‌ها")

    c = sub.add_parser("tools", help="لیست/اجرای ابزار")
    c.add_argument("--call", default=None, help="نام ابزار برای اجرا")
    c.add_argument("--params", default="{}", help="پارامترها (JSON)")
    c.add_argument("--yes", "-y", action="store_true")

    c = sub.add_parser("memory", help="حافظه دائمی")
    c.add_argument("--add", default=None)
    c.add_argument("--search", default=None)
    c.add_argument("--list", action="store_true")
    c.add_argument("--ingest", default=None, help="ایندکس فایل/پوشه در حافظه")
    c.add_argument("--limit", type=int, default=10)

    c = sub.add_parser("skill", help="مهارت‌ها")
    c.add_argument("--show", default=None)

    c = sub.add_parser("serve", help="اجرای API سرور")
    c.add_argument("--host", default="127.0.0.1")
    c.add_argument("--port", type=int, default=8899)

    c = sub.add_parser("ui", help="🖥️ داشبورد وب خورشید (رابط کاربری)")
    c.add_argument("--host", default="127.0.0.1")
    c.add_argument("--port", type=int, default=8899)
    c.add_argument("--no-browser", action="store_true")

    c = sub.add_parser("schedule", help="زمان‌بند تسک‌ها")
    c.add_argument("--add", default=None)
    c.add_argument("--name", default="task")
    c.add_argument("--agent", default="computer")
    c.add_argument("--every", type=int, default=3600)
    c.add_argument("--list", action="store_true")
    c.add_argument("--ls", action="store_true")
    c.add_argument("--remove", type=int, default=None)
    c.add_argument("--run", action="store_true")

    sub.add_parser("doctor", help="بررسی سلامت سیستم")

    c = sub.add_parser("init", help="نصب پریست کانفیگ")
    c.add_argument("--preset", default="default",
                   choices=["default", "computer-agent", "chat-simple", "gemini"])

    c = sub.add_parser("setup", help="\U0001f9d9 ویزارد نصب قدم‌به‌قدم خورشید")
    c.add_argument("--engine", default=None, choices=["mock", "ollama", "gemini", "openai_compat"])
    c.add_argument("--key", default=None, help="کلید API موتور ابری")
    c.add_argument("--extras", default=None, help="اکستراها: all/server/browser/desktop/voice/hotkey/none")
    c.add_argument("--hotkey", default=None, help="کلید پوش‌تو‌تاک (پیش‌فرض: ctrl)")
    c.add_argument("--yes", action="store_true", help="غیرتعاملی (پاسخ بله به همه)")

    c = sub.add_parser("telegram", help="\U0001f4f1 کنترل خورشید از تلگرام (ربات)")
    c.add_argument("--token", default=None, help="توکن ربات از @BotFather (یا KHORSHID_TELEGRAM_TOKEN)")
    c.add_argument("--agent", default=None, help="ایجنت پاسخ‌گو (پیش‌فرض کانفیگ)")
    c.add_argument("--allow", default="", help="آیدی‌های مجاز با کاما (خالی = همه)")

    c = sub.add_parser("voice", help="🎙️ گفت‌وگوی صوتی با خورشید")
    c.add_argument("--agent", default=None)
    c.add_argument("--seconds", type=int, default=6, help="طول ضبط هر دور (ثانیه)")
    c.add_argument("--push", action="store_true", help="ضبط با Enter شروع/پایان (نامحدود)")
    c.add_argument("--no-tts", action="store_true", help="بدون پخش صدای جواب")
    c.add_argument("--once", action="store_true", help="فقط یک دور")
    c.add_argument("--voice", default=None, help="صدای TTS (Kore/Charon/Fenrir/...)")

    c = sub.add_parser("speak", help="🔊 خواندن یک متن با صدای خورشید")
    c.add_argument("text")
    c.add_argument("--out", default="", help="مسیر ذخیره WAV")
    c.add_argument("--voice", default=None)

    c = sub.add_parser("listen", help="🎤 ضبط و رونویسی صدا")
    c.add_argument("--seconds", type=int, default=5)

    c = sub.add_parser("hotkey", help="🎙️ پوش‌تو‌تاک سراسری: نگه دار→حرف بزن→ول کن (پیش‌فرض: ctrl)")
    c.add_argument("--set", default=None, help="تغییر ترکیب، مثلاً 'ctrl+shift+j' یا 'alt'")
    c.add_argument("--action", default=None, choices=["voice", "dashboard"])
    c.add_argument("--daemon", action="store_true", help="روشن ماندن و گوش دادن")
    c.add_argument("--test", action="store_true", help="یک چرخه آزمایشی پوش‌تو‌تاک")
    c.add_argument("--hold", type=float, default=0.25, help="آستانه نگه‌داشتن به ثانیه (پیش‌فرض 0.25)")
    c.add_argument("--max", type=float, default=30.0, help="سقف ضبط به ثانیه (پیش‌فرض 30)")
    c.add_argument("--stop", action="store_true", help="توقف دیمون روشن")
    c.add_argument("--status", action="store_true", help="وضعیت دیمون")

    c = sub.add_parser("quiz", help="📝 حل خودکار آزمون/فرم یک صفحه وب")
    c.add_argument("query", nargs="?", default="")
    c.add_argument("--url", default="")
    c.add_argument("--max", type=int, default=30)
    c.add_argument("--submit", action="store_true", help="ثبت نهایی فرم")

    c = sub.add_parser("traces", help="🔍 مشاهده traceهای ثبت‌شده")
    c.add_argument("--limit", type=int, default=15)
    c.add_argument("--show", default="", help="آیدی trace برای جزئیات")
    c.add_argument("--clear", action="store_true", help="پاک‌سازی همه")

    c = sub.add_parser("costs", help="💰 گزارش هزینه و توکن مدل‌ها")

    c = sub.add_parser("vault", help="🔐 گاوصندوق کلیدها (keyring)")
    c.add_argument("--set", default="", help="ذخیره راز (مثل GEMINI_API_KEY)")
    c.add_argument("--get", default="", help="نمایش ماسک‌شده راز")

    c = sub.add_parser("eval", help="🧪 اجرای سوئیت ارزیابی (evals/)")
    c.add_argument("-k", default="", help="فیلتر تست")

    c = sub.add_parser("checkpoints", help="💾 چک‌پوینت اجراها (resume)")
    c.add_argument("--clear", nargs="?", const="__ALL__", default=None,
                   help="پاک‌سازی (آیدی یا همه)")

    c = sub.add_parser("wake", help="👂 شنونده بیدارباش صوتی (wake word)")
    c.add_argument("--keywords", default="خورشید,khorshid", help="کلمات با کاما")
    c.add_argument("--threshold", type=float, default=0.5)
    c.add_argument("--say", action="store_true", help="جواب صوتی «بله قربان؟»")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not args.cmd:
        print("🤖 ULTIMATE KHORSHID — برای راهنما: khorshid --help | شروع سریع: khorshid chat")
        return 0
    fn = {"chat": cmd_chat, "ask": cmd_ask, "agents": cmd_agents, "tools": cmd_tools,
          "memory": cmd_memory, "skill": cmd_skill, "serve": cmd_serve, "ui": cmd_ui,
          "schedule": cmd_schedule, "doctor": cmd_doctor, "init": cmd_init,
          "voice": cmd_voice, "speak": cmd_speak, "listen": cmd_listen,
          "hotkey": cmd_hotkey, "quiz": cmd_quiz, "setup": cmd_setup,
          "telegram": cmd_telegram, "traces": cmd_traces, "costs": cmd_costs,
          "vault": cmd_vault, "eval": cmd_eval, "checkpoints": cmd_checkpoints,
          "wake": cmd_wake}[args.cmd]
    try:
        return fn(args)
    except KeyboardInterrupt:
        print("\nلغو شد.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
