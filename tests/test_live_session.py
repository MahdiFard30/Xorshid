"""Offline tests for Live memory, barge-in, reconnect and at-most-once tools."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import struct
import sys
import threading
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

from ultimate_khorshid.core.config import KhorshidConfig
from ultimate_khorshid.core.types import ToolCall, ToolResult
from ultimate_khorshid.memory.automatic import AutomaticMemory
from ultimate_khorshid.tools.base import BaseTool, ToolExecutor, ToolSpec
from ultimate_khorshid.voice.live_session import (
    LiveMemory, LiveDeviceError, LiveTurn, ReplyGuard, ResumptionState,
    ReconnectRequested, ToolLedger, append_transcript, pcm_rms,
    reconnect_sessions, retryable_connection_error,
)


@pytest.fixture
def cfg(tmp_path):
    cfg = KhorshidConfig()
    cfg.storage.db_path = str(tmp_path / 'memory.db')
    return cfg


def content(query=None, reply=None, **kw):
    return NS(input_transcription=NS(text=query, finished=False) if query is not None else None,
              output_transcription=NS(text=reply, finished=False) if reply is not None else None, **kw)


def test_live_and_regular_memory_share_facts_and_history(cfg):
    ordinary = AutomaticMemory(cfg.storage.db_path)
    ordinary.remember('local', 'اسم من مهدی است', 'سلام', [], 'unverified_reply')
    live = LiveMemory(cfg)
    assert 'مهدی' in live.context()
    live.start(1)
    live.submit()
    live.observe(content('رنگ موردعلاقه من آبی است', 'یادم می‌ماند.'))
    live.finish()
    restarted = AutomaticMemory(cfg.storage.db_path)
    assert 'آبی' in ' '.join(restarted.facts())
    assert restarted.status()['turns'] == 2
    assert 'یادم می‌ماند' in restarted.recent('local')[-1]['content']


def test_model_reply_is_never_extracted_as_user_fact(cfg):
    live = LiveMemory(cfg)
    live.start(1)
    live.submit()
    live.observe(content('سلام', 'اسم من اشتباه است'))
    live.finish()
    assert live.store.facts() == []


def test_disconnected_partial_transcript_does_not_become_fact(cfg):
    live = LiveMemory(cfg)
    live.start(1)
    live.submit()
    live.observe(content('اسم من علی'))
    live.finish('incomplete')
    assert live.store.facts() == []
    assert live.store.status()['turns'] == 1
    live.start(2)
    live.submit()
    live.observe(NS(input_transcription=NS(text='اسم من مهدی است', finished=True)))
    live.finish('cancelled')
    assert live.store.facts() == ['نام کاربر: مهدی']


def test_interruption_and_disconnect_are_explicit_and_saved_once(cfg):
    live = LiveMemory(cfg)
    old = live.start(1)
    live.submit()
    live.observe(content('یک توضیح بده', 'نیمهٔ پاسخ'))
    live.start(2)
    assert old.closed and old.controller.is_cancelled
    live.submit()
    live.observe(content('درخواست بعدی', 'بخشی از جواب'))
    live.finish('incomplete')
    live.finish('incomplete')
    recent = live.store.recent('local')
    assert len(recent) == 4
    assert '[پاسخ کامل نشد: cancelled]' in recent[1]['content']
    assert '[پاسخ کامل نشد: incomplete]' in recent[3]['content']


def test_memory_disabled_does_not_create_database_and_disables_tools(cfg):
    from ultimate_khorshid.tools.memory_tools import MemoryStoreTool
    cfg.agent.context_from_memory = False
    live = LiveMemory(cfg)
    assert live.context() == '' and not Path(cfg.storage.db_path).exists()
    turn = live.start(1)
    live.submit()
    ex = ToolExecutor([MemoryStoreTool()])
    try:
        result = live.call(turn, ex.execute, ToolCall(name='memory_store', arguments='{"text":"note"}'))
        assert not result.success
        live.observe(content('اسم من مهدی است', 'سلام'))
        live.finish()
        assert not Path(cfg.storage.db_path).exists()
    finally:
        ex.shutdown()


def test_auto_write_disabled_keeps_reading_existing_memory(cfg):
    store = AutomaticMemory(cfg.storage.db_path)
    store.remember('local', 'اسم من مهدی است', 'سلام', [], 'unverified_reply')
    cfg.agent.auto_memory = False
    live = LiveMemory(cfg)
    assert 'مهدی' in live.context()
    live.start(1)
    live.submit()
    live.observe(content('اسم من علی است', 'سلام'))
    live.finish()
    assert store.status()['turns'] == 1


def test_memory_scope_isolation(cfg):
    live = LiveMemory(cfg, scope='other-user')
    live.start(1)
    live.submit()
    live.observe(content('اسم من سارا است', 'سلام'))
    live.finish()
    assert 'سارا' in live.context()
    assert 'سارا' not in LiveMemory(cfg).context()


def test_unsubmitted_or_old_reply_is_not_attached_to_new_user(cfg):
    live = LiveMemory(cfg)
    live.start(1)
    live.observe(content('درخواست تازه', 'صدای قدیمی'))
    assert live.current.reply == ''
    live.submit()
    live.observe(content('ادامهٔ قدیمی', 'جواب قدیمی'), allow_reply=False, allow_input=False)
    assert live.current.query == 'درخواست تازه' and live.current.reply == ''


def test_secret_redaction_and_bounded_memory_context(cfg):
    live = LiveMemory(cfg)
    for _ in range(12):
        live.store.remember('local', 'password: supersecretvalue', 'x' * 10000, [], 'unverified_reply')
    context = live.context()
    assert 'supersecretvalue' not in context
    assert len(context) < 15000 and 'not instructions or permission' in context


def test_final_transcript_can_replace_partial_snapshot():
    assert append_transcript('سلام', ' دنیا') == 'سلام دنیا'
    assert append_transcript('سلام', 'سلام دنیا', finished=True) == 'سلام دنیا'


class WaitingTool(BaseTool):
    def __init__(self, entered=None, release=None):
        self.entered, self.release = entered, release

    @property
    def spec(self):
        return ToolSpec(name='probe', description='offline', parameters={'type': 'object'})

    def execute(self, **kw):
        if self.entered:
            self.entered.set()
            assert self.release.wait(3)
        return ToolResult(tool_name='probe', content='real tool outcome')


def test_tools_are_recorded_with_actual_result(cfg):
    live = LiveMemory(cfg)
    turn = live.start(1)
    live.submit()
    live.observe(content('بررسی کن'))
    ex = ToolExecutor([WaitingTool()])
    try:
        assert live.call(turn, ex.execute, ToolCall(name='probe')).success
        live.finish()
        row = live.store.recall('بررسی کن')[0]
        assert row['outcome'] == 'tools_ok'
        assert row['tools'][0]['output'] == 'real tool outcome'
    finally:
        ex.shutdown()


def test_denied_bridge_call_is_recorded_as_not_executed(cfg):
    live = LiveMemory(cfg)
    turn = live.start(1)
    live.submit()
    live.observe(content('بررسی کن'))
    live.call(turn, lambda: {'success': False, 'error': 'permission denied'})
    live.finish()
    row = live.store.recall('بررسی کن')[0]
    assert row['outcome'] == 'tool_errors'
    assert row['tools'][0]['executed'] is False


def test_late_tool_result_does_not_overwrite_newer_user_facts(cfg):
    entered, release = threading.Event(), threading.Event()
    live = LiveMemory(cfg)
    old = live.start(1)
    live.submit()
    live.observe(content('رنگ موردعلاقه من آبی است'))
    ex = ToolExecutor([WaitingTool(entered, release)])
    thread = threading.Thread(target=live.call, args=(old, ex.execute, ToolCall(name='probe')))
    try:
        thread.start()
        assert entered.wait(3)
        live.start(2)
        live.submit()
        live.observe(content('رنگ موردعلاقه من قرمز است', 'باشه'))
        live.finish()
        release.set()
        thread.join(3)
        assert not thread.is_alive()
        assert live.store.facts() == ['رنگ موردعلاقه کاربر: قرمز']
        assert live.store.status()['turns'] == 3
    finally:
        release.set()
        thread.join(3)
        ex.shutdown()


def test_cancelled_turn_does_not_start_new_tool(cfg):
    live = LiveMemory(cfg)
    turn = live.start(1)
    live.start(2)
    run = Mock()
    with pytest.raises(Exception, match='لغو'):
        live.call(turn, run)
    run.assert_not_called()


def test_reply_guard_waits_for_old_reply_boundary():
    guard = ReplyGuard()
    turn = LiveTurn(2, submitted=True)
    guard.start(True)
    assert not guard.accept(content(reply='late'), turn, held=False)
    assert not guard.accept(content(interrupted=True), turn, held=False)
    assert guard.accept(content(reply='new'), turn, held=False)
    assert not guard.accept(content(reply='new'), turn, held=True)
    guard.start(True)
    assert not guard.accept(content(turn_complete=True), turn, held=False)
    assert guard.accept(content(reply='next'), turn, held=False)


def test_ptt_disconnect_drops_audio_and_requires_release():
    from ultimate_khorshid.interface.khorshid_live_trial import PushToTalk
    async def scenario():
        playback = NS(clear=Mock())
        gate = PushToTalk(asyncio.get_running_loop(), playback, lambda _: None)
        gate.press()
        old_generation = gate.generation
        gate.audio(b'pcm', old_generation)
        gate.suspend()
        assert not gate.capturing and gate.events.empty()
        gate.resume()
        gate.press()
        assert not gate.capturing
        gate.release()
        gate.press()
        assert gate.capturing
        gate.audio(b'stale', old_generation)
        assert gate.events.qsize() == 1  # only the fresh start event
        gate.close()
    asyncio.run(scenario())


def test_resumption_handles_are_updated_and_invalidated():
    state = ResumptionState()
    state.observe(NS(session_resumption_update=NS(resumable=True, new_handle='opaque')))
    assert state.handle == 'opaque'
    state.observe(NS(session_resumption_update=NS(resumable=True, new_handle=None)))
    assert state.handle == 'opaque'
    state.observe(NS(session_resumption_update=NS(resumable=False, new_handle=None), go_away=NS()))
    assert state.handle is None and state.go_away


def test_reconnect_uses_handle_and_does_not_replay_work():
    async def scenario():
        state, configs, runs = ResumptionState(), [], []
        @asynccontextmanager
        async def connect(config):
            configs.append(config)
            yield NS()
        async def run(session):
            runs.append(session)
            if len(runs) == 1:
                state.handle = 'resume-handle'
                raise ConnectionError('connection lost')
        disconnected, sleep = AsyncMock(), AsyncMock()
        await reconnect_sessions(connect, lambda h: {'handle': h}, run, state, disconnected, sleep=sleep)
        assert configs == [{'handle': None}, {'handle': 'resume-handle'}]
        disconnected.assert_awaited_once()
        sleep.assert_awaited_once_with(1)
    asyncio.run(scenario())


def test_rejected_handle_starts_fresh_session():
    class Rejected(Exception):
        code = 400
    async def scenario():
        state, handles = ResumptionState(), []
        state.handle = 'invalid-handle'
        @asynccontextmanager
        async def connect(handle):
            handles.append(handle)
            if handle:
                raise Rejected()
            yield NS()
        await reconnect_sessions(connect, lambda h: h, AsyncMock(), state, AsyncMock(), sleep=AsyncMock())
        assert handles == ['invalid-handle', None]
    asyncio.run(scenario())


def test_retry_is_bounded_and_fatal_errors_are_not_retried():
    async def scenario(error, expected):
        calls = []
        @asynccontextmanager
        async def connect(_):
            calls.append(1)
            raise error
            yield
        with pytest.raises(Exception):
            await reconnect_sessions(connect, lambda h: {}, AsyncMock(), ResumptionState(),
                                     AsyncMock(), attempts=2, sleep=AsyncMock())
        assert len(calls) == expected
    asyncio.run(scenario(ConnectionError('lost'), 3))
    asyncio.run(scenario(LiveDeviceError('device failed'), 1))
    asyncio.run(scenario(ValueError('bad config'), 1))


def test_retry_status_classification():
    class APIError(Exception):
        def __init__(self, code):
            self.code = code
    assert retryable_connection_error(APIError(503))
    assert retryable_connection_error(APIError(429))
    assert not retryable_connection_error(APIError(403))
    assert retryable_connection_error(ReconnectRequested())


def test_ledger_deduplicates_inflight_and_completed_calls():
    async def scenario():
        ledger = ToolLedger()
        release = asyncio.Event()
        calls = []
        async def run():
            calls.append(1)
            await release.wait()
            return {'success': True}
        one = asyncio.create_task(ledger.execute('id', 'tool', {'x': 1}, run))
        two = asyncio.create_task(ledger.execute('id', 'tool', {'x': 1}, run))
        await asyncio.sleep(0)
        release.set()
        assert await one == await two == {'success': True}
        assert await ledger.execute('id', 'tool', {'x': 1}, run) == {'success': True}
        assert calls == [1]
        assert not (await ledger.execute('id', 'tool', {'x': 2}, run))['success']
        await ledger.close()
    asyncio.run(scenario())


def test_cancelled_response_wait_does_not_cancel_running_tool():
    async def scenario():
        ledger, started, release = ToolLedger(), asyncio.Event(), asyncio.Event()
        run_count = []
        async def run():
            run_count.append(1)
            started.set()
            await release.wait()
            return {'success': True}
        waiter = asyncio.create_task(ledger.execute('id', 'tool', {}, run))
        await started.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        release.set()
        assert (await ledger.execute('id', 'tool', {}, run))['success']
        assert run_count == [1]
        await ledger.close()
    asyncio.run(scenario())


def test_ledger_rejects_cancelled_missing_and_excess_calls():
    async def scenario():
        ledger, run = ToolLedger(limit=1), AsyncMock(return_value={'success': True})
        ledger.cancelled.add('cancelled')
        assert not (await ledger.execute('', 'tool', {}, run))['success']
        assert not (await ledger.execute('cancelled', 'tool', {}, run))['success']
        assert (await ledger.execute('one', 'tool', {}, run))['success']
        assert not (await ledger.execute('two', 'tool', {}, run))['success']
        run.assert_awaited_once()
        await ledger.close()
    asyncio.run(scenario())


def test_native_live_config_validates_against_installed_sdk():
    from google.genai import types
    from ultimate_khorshid.interface.khorshid_gemini_live_runner import make_config
    config = make_config('Algenib', NS(executor=NS(tools={})), 'quoted history')
    typed = types.LiveConnectConfig.model_validate(config)
    assert typed.session_resumption is not None
    assert typed.context_window_compression.sliding_window is not None
    assert 'quoted history' in config['system_instruction']


def test_live_transcription_has_persian_and_dynamic_app_vocabulary(monkeypatch):
    from google.genai import types
    from ultimate_khorshid.tools import app_launcher
    from ultimate_khorshid.interface.khorshid_gemini_live_runner import make_config
    monkeypatch.setattr(app_launcher, 'speech_vocabulary', lambda: ['PhotonBrush', 'فوتون براش'])
    cfg = make_config('Algenib', NS(executor=NS(tools={})))
    typed = types.LiveConnectConfig.model_validate(cfg)
    assert typed.input_audio_transcription.language_codes == ['fa-IR', 'en-US']
    assert typed.input_audio_transcription.custom_vocabulary == ['PhotonBrush', 'فوتون براش']
    assert typed.speech_config.language_code == 'fa-IR'
    assert typed.speech_config.voice_config.prebuilt_voice_config.voice_name == 'Algenib'
    assert 'PhotonBrush' in cfg['system_instruction']
    assert typed.realtime_input_config.automatic_activity_detection.disabled


def test_live_tool_chains_use_explicit_blocking_instead_of_server_default():
    from ultimate_khorshid.interface.khorshid_gemini_live_runner import make_config
    cfg = make_config('Algenib', NS(executor=NS(tools={})))
    declarations = cfg['tools'][0]['function_declarations']
    assert {f['name'] for f in declarations} == {'khorshid_list_tools', 'khorshid_execute_tool'}
    assert all(f['behavior'] == 'BLOCKING' for f in declarations)


def test_live_bridge_preserves_app_discovery_and_error_fields():
    from ultimate_khorshid.interface.khorshid_gemini_live_runner import execute_tool
    executor = Mock(tools={'list_apps': NS(), 'open_app': NS()})
    executor.execute.return_value = ToolResult(tool_name='list_apps', content='catalog page',
        metadata={'apps':[{'name':'PhotonBrush','id':'photon.desktop'}],
                  'total':35,'offset':0,'next_offset':20})
    rt = NS(executor=executor)
    result = execute_tool(rt, 'khorshid_execute_tool', {'tool_name':'list_apps', 'arguments_json':'{}'})
    assert result['success'] and result['next_offset'] == 20
    assert result['apps'][0]['id'] == 'photon.desktop'
    executor.execute.return_value = ToolResult(tool_name='open_app', content='not found', success=False,
                                               metadata={'app_error':'app_not_found'})
    result = execute_tool(rt, 'khorshid_execute_tool',
                          {'tool_name':'open_app','arguments_json':'{"target":"فوتون براش"}'})
    assert not result['success'] and result['app_error'] == 'app_not_found'


def test_output_rms_is_normalized():
    assert pcm_rms(b'') == 0
    assert pcm_rms(struct.pack('<hh', -32768, 32767)) == pytest.approx(1, abs=.0001)
    assert pcm_rms(struct.pack('<hh', 16384, -16384)) == .5


@pytest.mark.parametrize('reconnect', [False, True])
@pytest.mark.parametrize('with_audio', [False, True])
def test_runner_records_turn_and_cleans_up_with_fake_devices(cfg, monkeypatch, reconnect, with_audio):
    from ultimate_khorshid.interface import khorshid_gemini_live_runner as runner
    from google import genai
    from ultimate_khorshid.core import settings
    monkeypatch.setattr(settings, 'apply_to_config', lambda c: c)
    states, connections = [], []
    ducker = Mock()
    ducker.hold.return_value.ready.wait.return_value = True
    monkeypatch.setattr(runner, 'audio_ducking', ducker)
    original_handle = runner.handle_content
    def handle(content, playback, output):
        if getattr(content, 'model_turn', None):
            ducker.hold.assert_called_once()
            ducker.hold.return_value.ready.wait.assert_called_once()
            ducker.hold.return_value.close.assert_not_called()
        original_handle(content, playback, output)
    monkeypatch.setattr(runner, 'handle_content', handle)
    executor = ToolExecutor([])
    rt = NS(cfg=cfg, executor=executor)
    monkeypatch.setattr(runner, 'tool_runtime', lambda: rt)
    monkeypatch.setattr(runner, 'SunBridge', lambda: NS(state=states.append, level=Mock(), close=Mock()))
    class Context:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    class Listener(Context):
        listener = NS(is_alive=lambda: True)
        def __init__(self, loop, gate):
            loop.call_soon(gate.press)
            loop.call_soon(gate.finish)
    monkeypatch.setattr(runner, 'QuietTerminal', Context)
    monkeypatch.setattr(runner, 'KeyListener', Listener)
    sd = NS(check_input_settings=Mock(), check_output_settings=Mock(),
            RawInputStream=lambda **kw: Context(), RawOutputStream=lambda **kw: Context())
    monkeypatch.setitem(sys.modules, 'sounddevice', sd)
    class Session:
        send_realtime_input = AsyncMock()
        def __init__(self, number):
            self.number = number
        async def receive(self):
            await asyncio.sleep(0)
            if self.number == 1:
                yield NS(session_resumption_update=NS(resumable=True, new_handle='opaque-handle'))
                audio = {'model_turn': NS(parts=[NS(inline_data=NS(data=b'\x01\x00'*480,
                    mime_type='audio/pcm;rate=24000'))])} if with_audio else {}
                yield NS(server_content=content('رنگ موردعلاقه من آبی است', 'به خاطر می‌سپارم', **audio))
                yield NS(server_content=content(turn_complete=True))
                if reconnect:
                    raise ConnectionError('simulated network drop')
            else:
                # A resumed response without a new request must not become a new memory turn.
                yield NS(server_content=content(reply='old reply', turn_complete=True))
            raise LiveDeviceError('stop fake devices')
    @asynccontextmanager
    async def connect(**kwargs):
        connections.append(kwargs)
        yield Session(len(connections))
    close = AsyncMock()
    monkeypatch.setattr(genai, 'Client', lambda **kw: NS(aio=NS(live=NS(connect=connect), aclose=close)))
    with pytest.raises(LiveDeviceError):
        asyncio.run(runner.conversation('fake-key'))
    close.assert_awaited_once()
    if with_audio:
        ducker.hold.assert_called_once()
        ducker.hold.return_value.close.assert_called_once_with(wait=False)
    else:
        ducker.hold.assert_not_called()
    assert len(connections) == (2 if reconnect else 1)
    if reconnect:
        assert connections[1]['config']['session_resumption'] == {'handle': 'opaque-handle'}
    store = AutomaticMemory(cfg.storage.db_path)
    assert store.status()['turns'] == 1
    assert store.facts() == ['رنگ موردعلاقه کاربر: آبی']
