#!/usr/bin/env python3
"""Khorshid Gemini native Live audio with existing Khorshid tool executor.
Experimental: tool bridging depends on installed Google GenAI SDK and local tool schemas.
Does not use original TTS or modify the original launchers.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ultimate_khorshid.interface.khorshid_live_trial import (PlaybackBuffer, PushToTalk, KeyListener,
    QuietTerminal, get_key, safe_error, DEFAULT_MODEL, SYSTEM, handle_content)
from ultimate_khorshid.interface.sun_bridge import SunBridge
from ultimate_khorshid.voice.ducking import service as audio_ducking


def tool_runtime():
    # Import ONLY the original tool registry/executor, not the local speech model.
    from ultimate_khorshid.runtime import KhorshidRuntime
    from ultimate_khorshid.core.approval import desktop_confirm
    rt = KhorshidRuntime(confirm_callback=desktop_confirm)
    return rt


def tool_guide(runtime):
    specs = [t.spec for t in runtime.executor.tools.values()]
    out = []
    for s in specs:
        out.append(f'{s.name}: {s.description[:165]}')
    # Tools are discoverable at runtime even when this summary is abbreviated.
    return '\n'.join(out)[:24000]


def make_config(voice, runtime, memory_context=''):
    from ultimate_khorshid.interface.khorshid_live_trial import config
    from ultimate_khorshid.tools.app_launcher import speech_vocabulary
    cfg = config(voice)
    vocabulary = speech_vocabulary()
    cfg['input_audio_transcription'] = {
        'language_codes': ['fa-IR', 'en-US'], 'custom_vocabulary': vocabulary}
    cfg['speech_config']['language_code'] = 'fa-IR'
    cfg['session_resumption'] = {}
    cfg['context_window_compression'] = {'sliding_window': {}}
    cfg['system_instruction'] = (SYSTEM.replace(
        'این نسخه آزمایش مکالمه است و ابزار کنترل کامپیوتر یا ترید ندارد؛ ادعای اجرای برنامه یا معامله نکن.',
        'ابزارهای خورشید از طریق khorshid_list_tools و khorshid_execute_tool در دسترس‌اند. '
        'برای عمل روی کامپیوتر ابتدا ابزار صحیح را پیدا کن، فقط با درخواست صریح کاربر اجرا کن؛ '
        'انجام کاری را پیش از دریافت نتیجهٔ موفق ادعا نکن. برای اقدامات مخرب، تغییر مالی، '
        'یا ارسال اطلاعات حساس، اول اجازهٔ صریح بگیر.') +
        '\nابزارهای فعلی خورشید:\n' + tool_guide(runtime))
    # Always supply a positive, explicit tool policy even if the trial SYSTEM
    # wording changes and the replacement above no longer matches.
    cfg['system_instruction'] += """

قوانین قطعی خورشید Gemini Live برای گزارش معاملات دمو:
تو به ابزارهای واقعی خورشید وصل هستی. دستور قدیمی نسخهٔ آزمایشی مبنی بر
«نداشتن ابزار ترید یا کنترل کامپیوتر» در این نسخه معتبر نیست؛ هیچ‌وقت صرفاً
براساس آن ادعای نداشتن دسترسی نکن. وضعیت را فقط از نتیجهٔ ابزار بگو.

وقتی کاربر می‌پرسد «داری ترید می‌کنی؟»، «ربات چه کار می‌کند؟»،
«وضعیت معاملات چیست؟»، «طلا، یورو دلار، دلار ین چه وضعی دارند؟»،
یا گزارش کوتاه فعالیت معاملاتی می‌خواهد، بدون پرسیدن سؤال اضافی
مستقیماً تابع khorshid_execute_tool را با این آرگومان‌ها اجرا کن:
  tool_name = mt5_demo
  arguments_json = {"action":"status"}

برای درخواست «گزارش کامل»، «گزارش عملکرد»، یا «جزئیات معاملات»،
مستقیماً همین تابع را با این آرگومان‌ها اجرا کن:
  tool_name = mt5_demo
  arguments_json = {"action":"report"}

برای اطلاعات حساب و Balance/Equity واقعی یا قیمت/کندل از mt5_read استفاده کن؛
این ابزار با گزارش فعالیت ربات mt5_demo متفاوت است. برای گزارش ربات سراغ
mt5_read نرو. اگر نام ابزارهای بالا در فهرست نصب‌شده موجود است، نیازی به
khorshid_list_tools قبل از اولین فراخوانی آن‌ها نیست.

درخواست گزارش فقط خواندنی است: برای آن تأیید اضافی نخواه و هرگز
start یا stop را به جای status/report فراخوانی نکن. تغییر معاملات یا تنظیمات
مالی بدون اجازهٔ صریح و سازوکار تأیید امن ممنوع است. اگر ابزار ناموفق بود،
خطای واقعی ابزار را به فارسی بگو و داده یا دلیل خطا را حدس نزن.
برای هر نماد XAUUSD و EURUSD و USDJPY جداگانه گزارش کن؛ روشن بودن پردازش،
داشتن پوزیشن باز، و سودده بودن را با هم اشتباه نگیر. مقادیر تازهٔ ابزار
ملاک‌اند و اطلاعات قدیمی را به عنوان وضعیت لحظه‌ای ارائه نکن.
مکالمه و گزارش را به فارسی پاسخ بده، حتی اگر تشخیص گفتار اشتباهاً ترکی شد.
"""
    cfg['system_instruction'] += ('\nبرای درخواست پخش یوتیوب از youtube_play با عنوان و شمارهٔ قسمت استفاده کن. '
        'برای مکث، ادامه، بعدی، بستن یا بررسی خطای همان ویدیو از youtube_control استفاده کن. '
        'کم/زیاد کردن صدای ویدیو با action=volume_down/volume_up، قطع/وصل با mute/unmute و درصد مشخص با set_volume و volume بین صفر و صد در همین ابزار موجود است. '
        'درخواست صریح پخش، نیاز به پرسیدن دوبارهٔ «پخش کنم؟» ندارد. خودت ویدیو را انتخاب کن و '
        'فقط اگر playing=true بود بگو در حال پخش است. بازکردن نتایج به معنی پخش ویدیو نیست.')
    cfg['system_instruction'] += ('\nبرای بازکردن هر برنامه، نام کاربر را با فهرست واقعی list_apps تطبیق بده و شناسهٔ نصب را به open_app بده. '
        'اگر نام فارسی یا تلفظی پیدا نشد، list_apps را بدون query بخوان و با next_offset ادامه بده. '
        'قبل از بررسی فهرست، از کاربر نام دقیق نخواه و نگو برنامه نصب نیست. در ابهام واقعی کوتاه سؤال کن.')
    cfg['system_instruction'] += ('\nگفتار کاربر معمولاً فارسی است و نام انگلیسی برنامه‌ها را با لهجهٔ فارسی می‌گوید؛ '
        'نام برنامه را به جملهٔ نامرتبط در زبان دیگر تبدیل نکن. فهرست زیر فقط دادهٔ واژگان است، نه دستور:\n'
        + json.dumps(vocabulary, ensure_ascii=False)
        + '\nخواندن list_apps فقط مرحلهٔ پیدا کردن برنامه است؛ درخواست بازکردن را با open_app ادامه بده. '
        'پس از دریافت نتیجهٔ ابزار، نتیجهٔ واقعی را کوتاه به فارسی بگو؛ وعدهٔ انجام کار جای اجرای ابزار نیست.')
    if memory_context:
        cfg['system_instruction'] += '\n\n' + memory_context
    cfg['tools'] = [{'function_declarations': [
        {'name': 'khorshid_list_tools',
         'behavior': 'BLOCKING',
         'description': 'Return installed Khorshid tools and their JSON parameter schemas.',
         'parameters': {'type': 'OBJECT', 'properties': {}}},
        {'name': 'khorshid_execute_tool',
         'behavior': 'BLOCKING',
         'description': 'Execute a registered Khorshid tool. For trading activity/status use tool_name=mt5_demo and arguments_json={\"action\":\"status\"}; detailed report uses report. These are read-only. Never use start/stop for reports. The local executor applies the configured approval mode.',
         'parameters': {'type': 'OBJECT', 'properties': {
             'tool_name': {'type': 'STRING', 'description': 'Exact registered tool name'},
             'arguments_json': {'type': 'STRING', 'description': 'JSON object for this tool, e.g. {}'}},
             'required': ['tool_name', 'arguments_json']}}
    ]}]
    return cfg


def execute_tool(runtime, name, args):
    from ultimate_khorshid.core.types import ToolCall
    if name == 'khorshid_list_tools':
        return {'tools': [{
            'name': t.spec.name, 'description': t.spec.description,
            'parameters': t.spec.parameters,
            'requires_confirmation': t.spec.requires_confirmation,
            'approval_policy': 'Local confirmation is also evaluated per tool action by the executor.',
        } for t in runtime.executor.tools.values()]}
    if name != 'khorshid_execute_tool':
        return {'success': False, 'error': 'Unknown Live bridge function'}
    tool_name = str(args.get('tool_name', ''))
    if tool_name not in runtime.executor.tools:
        return {'success': False, 'error': 'Unknown Khorshid tool: ' + tool_name}
    parameters = args.get('arguments_json', '{}')
    if not isinstance(parameters, str):
        return {'success': False, 'error': 'arguments_json must be JSON text'}
    # Validate tool arguments before evaluating permissions.
    try:
        parsed = json.loads(parameters)
        if not isinstance(parsed, dict):
            return {'success': False, 'error': 'Tool arguments must be an object'}
    except ValueError as exc:
        return {'success': False, 'error': 'Invalid tool JSON: ' + str(exc)}

    # Explicit read-only allowances for existing MT5 reporting tools.
    read_only_mt5 = (
        tool_name == 'mt5_read'
        and parsed.get('action') in ('status', 'quotes', 'candles')
    ) or (
        tool_name == 'mt5_demo'
        and parsed.get('action') in ('status', 'report', 'catalog')
        and set(parsed) == {'action'}
    )

    blocked_name = any(
        x in tool_name.lower()
        for x in ('trade', 'order', 'mt5', 'metatrader',
                  'shell_exec', 'python_exec')
    )

    # MT5 reporting is available; mutations stay outside this Live bridge.
    # Other consequential actions go through the shared local approval dialog.
    if blocked_name and not read_only_mt5:
        return {
            'success': False,
            'error': 'Tool requires confirmation or is not permitted in Live.'
        }

    print(f'[Live Tool Detail] {tool_name}', flush=True)
    result = runtime.executor.execute(ToolCall(name=tool_name, arguments=json.dumps(parsed, ensure_ascii=False)))
    print(f'[Live Tool Result] {tool_name}: {"OK" if result.success else "FAILED"}', flush=True)
    response = {'success': result.success, 'result': str(result.content)[:16000],
                'approval_required': bool(result.metadata.get('approval_required'))}
    if tool_name == 'list_apps':
        response.update({field: result.metadata[field] for field in
                         ('apps', 'total', 'offset', 'next_offset') if field in result.metadata})
    if 'app_error' in result.metadata:
        response['app_error'] = result.metadata['app_error']
    return response


async def conversation(key):
    import sounddevice as sd
    from google import genai
    from google.genai import types
    import contextlib
    import queue
    import threading
    import time
    from ultimate_khorshid.voice.live_session import (
        LiveMemory, ReplyGuard, ResumptionState, ToolLedger, LiveDeviceError,
        ReconnectRequested, reconnect_sessions, pcm_rms,
    )

    sun = SunBridge()
    runtime = tool_runtime()
    memory = LiveMemory(runtime.cfg)
    ledger, resumption, replies = ToolLedger(), ResumptionState(), ReplyGuard()
    playback = PlaybackBuffer(pitch=0.0)
    loop = asyncio.get_running_loop()
    gate = PushToTalk(loop, playback, lambda m: print(m, flush=True))
    gate.suspend()
    callback_failed = threading.Event()
    meter_queue = queue.Queue(maxsize=4)
    last_voice = [0.0]
    duck_lease = [None]
    duck_started = [0.0]
    duck_pending = [False]

    def release_duck():
        if duck_lease[0] is not None:
            duck_lease[0].close(wait=False)
            duck_lease[0] = None
    client = genai.Client(api_key=key, http_options={'api_version': 'v1beta'})
    voice = os.environ.get('KHORSHID_GEMINI_LIVE_VOICE', 'Algenib')
    model = os.environ.get('KHORSHID_LIVE_MODEL', DEFAULT_MODEL)
    setup = [None]
    resources = contextlib.ExitStack()
    key_listener = [None]

    original_press = gate.press
    def press():
        fresh = not gate.held and gate.connected and not gate.require_release and not gate.closed
        if fresh:
            replies.start(memory.current is not None)
        original_press()
        if fresh and gate.held:
            memory.start(gate.generation)
            last_voice[0] = 0.0
            release_duck()
            sun.state('listening')
    gate.press = press
    original_finish = gate.finish
    def finish():
        submitted = gate.held and not gate.closed
        original_finish()
        if submitted:
            memory.submit()
            sun.state('thinking')
    gate.finish = finish

    def record(data, frames, timing, status):
        if gate.capturing:
            try:
                loop.call_soon_threadsafe(gate.audio, bytes(data), gate.generation)
            except RuntimeError:
                pass

    def play(out, frames, timing, status):
        try:
            raw = playback.take(frames * 2)
            out[:] = raw
            if any(raw):
                last_voice[0] = time.monotonic()
                try:
                    meter_queue.put_nowait((gate.generation, raw))
                except queue.Full:
                    pass
        except Exception:
            out[:] = bytes(frames * 2)
            callback_failed.set()

    def configure(handle):
        if not handle or setup[0] is None:
            setup[0] = make_config(voice, runtime, memory.context())
        cfg = dict(setup[0])
        cfg['session_resumption'] = {'handle': handle} if handle else {}
        return cfg

    @contextlib.asynccontextmanager
    async def connect(cfg):
        async with contextlib.AsyncExitStack() as stack:
            session = await asyncio.wait_for(stack.enter_async_context(
                client.aio.live.connect(model=model, config=cfg)), timeout=30)
            yield session

    async def disconnected():
        release_duck()
        gate.suspend()
        memory.finish('incomplete')
        replies.start(False)
        last_voice[0] = 0.0
        sun.state('idle')
        print('[Live] گفتار ارسال‌نشده کنار گذاشته شد؛ پس از اتصال، کلید را دوباره بگیرید.', flush=True)

    async def run(session):
        if key_listener[0] is None:
            try:
                resources.enter_context(QuietTerminal())
                key_listener[0] = resources.enter_context(KeyListener(loop, gate))
                resources.enter_context(sd.RawOutputStream(
                    samplerate=24000, channels=1, dtype='int16', blocksize=480,
                    latency='low', callback=play))
                resources.enter_context(sd.RawInputStream(
                    samplerate=16000, channels=1, dtype='int16', blocksize=320, callback=record))
            except Exception as exc:
                raise LiveDeviceError('Audio/key setup failed: ' + str(exc)) from exc
        gate.resume()
        sun.state('idle')
        print('[Gemini Live Khorshid] Connected. Hold 1, speak, release. Ctrl+C exits.', flush=True)
        print('[Live] حافظه تابع تنظیمات مشترک است؛ ابزارهای اثرگذار تأیید محلی می‌خواهند.', flush=True)
        workers, call_turns, tool_error = set(), {}, [None]

        def worker_done(task):
            workers.discard(task)
            if not task.cancelled():
                exc = task.exception()
                if exc is not None:
                    tool_error[0] = exc

        async def tools(batch, turn, eligible):
            responses = []
            for fc in batch:
                params = fc.args or {}
                async def invoke(fc=fc, params=params):
                    if not eligible or fc.id in ledger.cancelled:
                        return {'success': False, 'error': 'No current submitted request; tool was not executed.'}
                    return await asyncio.to_thread(memory.call, turn, execute_tool, runtime, fc.name, params)
                result = await ledger.execute(fc.id, fc.name, params, invoke)
                if fc.id not in ledger.cancelled:
                    responses.append(types.FunctionResponse(id=fc.id, name=fc.name, response=result))
            if responses:
                await asyncio.wait_for(session.send_tool_response(function_responses=responses), timeout=20)

        async def send():
            while True:
                kind, data = await gate.events.get()
                if kind == 'start':
                    kw = {'activity_start': types.ActivityStart()}
                elif kind == 'end':
                    kw = {'activity_end': types.ActivityEnd()}
                else:
                    kw = {'audio': types.Blob(data=data, mime_type='audio/pcm;rate=16000')}
                await asyncio.wait_for(session.send_realtime_input(**kw), timeout=20)

        async def receive():
            while True:
                seen = False
                async for message in session.receive():
                    seen = True
                    resumption.observe(message)
                    cancellation = getattr(message, 'tool_call_cancellation', None)
                    if cancellation:
                        for ident in cancellation.ids or []:
                            ledger.cancelled.add(ident)
                            turn = call_turns.get(ident)
                            if turn:
                                turn.controller.cancel('Server cancelled tool call')
                                if turn.closed and replies.waiting:
                                    replies.start(False)
                    calls = getattr(message, 'tool_call', None)
                    if calls:
                        batch = calls.function_calls or []
                        turn = memory.current
                        eligible = bool(turn and turn.submitted and not gate.held and not replies.waiting)
                        for fc in batch:
                            call_turns[fc.id] = turn
                        task = asyncio.create_task(tools(batch, turn, eligible))
                        workers.add(task)
                        task.add_done_callback(worker_done)
                        sun.state('thinking')
                    content = getattr(message, 'server_content', None)
                    if content:
                        was_waiting = replies.waiting
                        interrupted = bool(getattr(content, 'interrupted', False))
                        allowed = replies.accept(content, memory.current, gate.held)
                        memory.observe(content, allow_reply=allowed,
                                       allow_input=not was_waiting or interrupted)
                        if interrupted or gate.held:
                            playback.clear()
                            release_duck()
                        if allowed:
                            turn = getattr(content, 'model_turn', None)
                            audio = any(getattr(getattr(part, 'inline_data', None), 'data', None)
                                        and str(getattr(part.inline_data, 'mime_type', '')).startswith('audio/pcm')
                                        for part in (getattr(turn, 'parts', None) or []))
                            if audio and duck_lease[0] is None:
                                generation = gate.generation
                                lease = duck_lease[0] = audio_ducking.hold()
                                duck_started[0] = time.monotonic()
                                duck_pending[0] = True
                                try:
                                    await asyncio.to_thread(lease.ready.wait, 1)
                                finally:
                                    duck_pending[0] = False
                                duck_started[0] = time.monotonic()
                                if gate.held or gate.generation != generation:
                                    continue
                            handle_content(content, playback, lambda m: print(m, flush=True))
                        elif not was_waiting:
                            transcript = getattr(content, 'input_transcription', None)
                            if transcript and transcript.text:
                                print('شما: ' + transcript.text, flush=True)
                        if (getattr(content, 'turn_complete', False) and not was_waiting
                                and memory.current and memory.current.submitted and not gate.held):
                            memory.finish('cancelled' if interrupted else None)
                if not seen:
                    raise ConnectionError('Gemini Live session closed')

        async def monitor():
            speaking = False
            while True:
                await asyncio.sleep(.05)
                level = None
                while not meter_queue.empty():
                    generation, raw = meter_queue.get_nowait()
                    if generation == gate.generation:
                        level = pcm_rms(raw)
                active = time.monotonic() - last_voice[0] < .28
                if (duck_lease[0] is not None and not duck_pending[0] and playback.size == 0 and not active
                        and time.monotonic() - duck_started[0] > .35):
                    release_duck()
                if active and not gate.held:
                    if level is not None:
                        sun.level(level)
                    elif not speaking:
                        sun.state('speaking')
                    speaking = True
                elif speaking:
                    if not gate.held:
                        sun.state('idle')
                    speaking = False
                if callback_failed.is_set():
                    raise LiveDeviceError('Audio output callback failed')
                if gate.overflow:
                    raise LiveDeviceError('Microphone queue overflow; network cannot keep up')
                if not key_listener[0].listener.is_alive():
                    raise LiveDeviceError('Key listener stopped')
                if tool_error[0] is not None:
                    raise tool_error[0]
                if (resumption.go_away and not memory.current and not gate.held
                        and not workers and not active and playback.size == 0):
                    raise ReconnectRequested('Server requested connection rotation')

        tasks = [asyncio.create_task(send()), asyncio.create_task(receive()), asyncio.create_task(monitor())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            gate.suspend()
            release_duck()
            memory.finish('incomplete')
            for task in tasks + list(workers):
                task.cancel()
            await asyncio.gather(*tasks, *list(workers), return_exceptions=True)

    try:
        sd.check_input_settings(channels=1, dtype='int16', samplerate=16000)
        sd.check_output_settings(channels=1, dtype='int16', samplerate=24000)
        with resources:
            await reconnect_sessions(connect, configure, run, resumption, disconnected,
                                     notify=lambda m: print('[Live] ' + m, flush=True))
    finally:
        gate.close()
        release_duck()
        memory.finish('cancelled')
        playback.clear()
        await ledger.close()
        runtime.executor.shutdown()
        await client.aio.aclose()
        sun.state('idle')
        sun.close()


def main():
    if os.name == 'posix':
        try:
            os.setsid()  # Overlay cleanup also owns any local approval dialog.
        except PermissionError:
            pass  # Already a process-group leader when launched from a terminal.
    key = ''
    try:
        key = get_key()
        if not key: raise RuntimeError('GEMINI_API_KEY not set')
        asyncio.run(conversation(key))
    except KeyboardInterrupt:
        print('[Gemini Live] Stopped.', flush=True)
        return 0
    except Exception as exc:
        print('[Gemini Live] '+safe_error(exc, key), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
