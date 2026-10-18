"""No keyboard, microphone, speaker, model download or real agent service."""
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import wave

import pytest

from ultimate_khorshid.core.control import CancelledError, RunController, use_controller
from ultimate_khorshid.hotkey.manager import HotkeyManager
from ultimate_khorshid.voice.tts_session import Session, SmoothPlayer


@pytest.fixture
def manager(monkeypatch, tmp_path):
    from ultimate_khorshid.voice import audio
    monkeypatch.setattr(audio, 'stop_recording', lambda proc: None)
    mgr = HotkeyManager(hold_threshold=0, max_record=0)
    captures = []

    def start():
        path = tmp_path / f'capture-{len(captures)}.wav'
        path.touch()
        captures.append(path)
        mgr._rec_proc, mgr._rec_path = object(), str(path)
        return True

    mgr._start_capture = start
    yield mgr, captures
    mgr.stop()
    if mgr._worker:
        mgr._worker.join(2)


def test_listener_accepts_new_capture_during_stt_and_discards_late_text(manager):
    mgr, paths = manager
    entered, resume, answered = threading.Event(), threading.Event(), threading.Event()
    got = []

    def transcribe(path):
        if path == str(paths[0]):
            entered.set()
            assert resume.wait(2)
            return 'old'
        return 'new'

    mgr._capture_transcript = transcribe
    mgr.on_text = lambda text: (got.append(text), answered.set())
    try:
        mgr.press('ctrl')
        original = mgr._turn_controller
        mgr.release('ctrl')
        assert entered.wait(2)
        mgr.press('ctrl')  # Would block here if STT held the listener lock.
        assert original.is_cancelled
        assert mgr._armed and len(paths) == 2
        mgr.release('ctrl')
    finally:
        resume.set()
    assert answered.wait(2)
    assert got == ['new']


def test_slow_recorder_shutdown_cannot_overwrite_new_capture(manager, monkeypatch):
    from ultimate_khorshid.voice import audio
    mgr, paths = manager
    stopping, resume, answered = threading.Event(), threading.Event(), threading.Event()
    original_proc = []
    got = []

    def stop(proc):
        if proc is original_proc[0]:
            stopping.set()
            assert resume.wait(2)

    monkeypatch.setattr(audio, 'stop_recording', stop)
    mgr._capture_transcript = lambda path: Path(path).name
    mgr.on_text = lambda text: (got.append(text), answered.set())
    try:
        mgr.press('ctrl')
        original_proc.append(mgr._rec_proc)
        mgr.release('ctrl')
        assert stopping.wait(2)
        mgr.press('ctrl')
        mgr.release('ctrl')
        assert answered.wait(2)
    finally:
        resume.set()
    assert got == ['capture-1.wav']


def test_stopping_manager_suppresses_inflight_transcript(manager):
    mgr, _ = manager
    entered, resume = threading.Event(), threading.Event()
    got = []
    def transcribe(path):
        entered.set()
        assert resume.wait(2)
        return 'late'
    mgr._capture_transcript = transcribe
    mgr.on_text = got.append
    try:
        mgr.press('ctrl')
        mgr.release('ctrl')
        assert entered.wait(2)
        mgr.stop()
    finally:
        resume.set()
    mgr._worker.join(2)
    assert not mgr._worker.is_alive()
    assert got == []
    mgr.press('ctrl')
    assert not mgr._armed


def test_pending_recording_replaced_and_agent_runs_serially(manager):
    mgr, paths = manager
    entered, resume, answered = threading.Event(), threading.Event(), threading.Event()
    calls = []
    mgr._capture_transcript = lambda path: Path(path).name
    def pipeline(text):
        calls.append(text)
        if len(calls) == 1:
            entered.set()
            assert resume.wait(2)
        else:
            answered.set()
    mgr.run_voice_pipeline = pipeline
    try:
        mgr.press('ctrl')
        mgr.release('ctrl')
        assert entered.wait(2)
        # Submit finalized recordings directly to make the queue ordering
        # deterministic while the first agent call is still in progress.
        for _ in range(2):
            mgr.press('ctrl')
            with mgr._lock:
                capture = mgr._rec_proc, mgr._rec_path
                mgr._rec_proc, mgr._rec_path = None, ''
                mgr._armed = False
                mgr._finish_capture(capture, mgr._turn_controller)
            mgr.release('ctrl')
        assert not paths[1].exists()
        assert paths[2].exists()
    finally:
        resume.set()
    assert answered.wait(2)
    assert calls == ['capture-0.wav', 'capture-2.wav']


def test_first_press_during_reply_preserves_new_recording_until_transcription(monkeypatch, tmp_path):
    """Use the real capture path allocator; older tests supplied unique paths."""
    from ultimate_khorshid.voice import audio, engines
    monkeypatch.setattr(audio.tempfile, 'tempdir', str(tmp_path))
    monkeypatch.setattr('ultimate_khorshid.hotkey.manager._beep', lambda **kwargs: None)
    captured, spoken, transcripts = [], [], []
    speaking, finish_old, old_cleaned, answered = (threading.Event() for _ in range(4))
    pipeline_returned = threading.Event()

    def record(path):
        with wave.open(path, 'wb') as fp:
            fp.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            fp.writeframes(b'\x01\x00' * 8000)
        captured.append(Path(path))
        return object()

    def transcribe(path, **kwargs):
        with wave.open(path, 'rb') as fp:
            assert fp.getnframes() == 8000
        transcripts.append(path)
        return 'original request' if len(transcripts) == 1 else 'changed request'

    monkeypatch.setattr(audio, 'start_recording', record)
    monkeypatch.setattr(audio, 'stop_recording', lambda proc: None)
    monkeypatch.setattr(engines, 'transcribe_file', transcribe)
    mgr = HotkeyManager(combination='1', hold_threshold=0, max_record=0)
    original_cleanup = mgr._cleanup_wav

    def cleanup(path):
        original_cleanup(path)
        if pipeline_returned.is_set() and path == str(captured[0]):
            old_cleaned.set()

    def reply(text):
        spoken.append(text)
        if len(spoken) == 1:
            speaking.set()
            assert finish_old.wait(2)
            pipeline_returned.set()
        else:
            answered.set()

    mgr._cleanup_wav = cleanup
    mgr.run_voice_pipeline = reply
    try:
        mgr.press('1'); mgr.release('1')
        assert speaking.wait(2)
        old_controller = mgr._turn_controller
        mgr.press('1')
        assert old_controller.is_cancelled
        finish_old.set()
        assert old_cleaned.wait(2)
        assert captured[1].exists(), 'Previous reply deleted the active microphone recording'
        assert captured[0] != captured[1]
        mgr.release('1')
        assert answered.wait(2)
        assert spoken == ['original request', 'changed request']
        assert len(transcripts) == 2  # No second press or second recording needed.
    finally:
        finish_old.set()
        mgr.stop()
        if mgr._worker:
            mgr._worker.join(2)


def test_failed_recorder_start_removes_its_reserved_file(monkeypatch, tmp_path):
    from ultimate_khorshid.voice import audio
    monkeypatch.setattr(audio.tempfile, 'tempdir', str(tmp_path))
    def fail(path):
        assert Path(path).exists()
        raise RuntimeError('Microphone unavailable')
    monkeypatch.setattr(audio, 'start_recording', fail)
    mgr = HotkeyManager(combination='1', hold_threshold=0, max_record=0)
    try:
        mgr.press('1')
        assert not mgr._armed and mgr._rec_proc is None and not mgr._rec_path
        assert list(tmp_path.glob('khorshid_ptt_*.wav')) == []
    finally:
        mgr.stop()


def test_stale_hold_timer_cannot_restart_stopped_manager(manager):
    mgr, paths = manager
    mgr._pressed.add('ctrl')
    mgr.stop()
    mgr._hold_elapsed()
    assert not mgr._armed
    assert paths == []


def test_quick_ctrl_shortcut_does_not_cancel_response():
    mgr = HotkeyManager(hold_threshold=999, max_record=0)
    controller = mgr._turn_controller = RunController()
    try:
        mgr.press('ctrl')
        mgr.press('c')
        mgr.release('c')
        mgr.release('ctrl')
        assert not controller.is_cancelled
    finally:
        mgr.stop()


@pytest.fixture
def audio_devices(monkeypatch, tmp_path):
    from contextlib import nullcontext
    monkeypatch.setattr('ultimate_khorshid.voice.tts_session.duck_other_audio', nullcontext)
    states, writes, aborts = [], [], []
    wrote = threading.Event()
    controller = RunController()
    class Stream:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def write(self, data):
            writes.append(data)
            controller.cancel()
            wrote.set()
        def abort(self): aborts.append(True)
    class Sun:
        def state(self, state): states.append(state)
        def level(self, level): pass
        def close(self): pass
    monkeypatch.setitem(sys.modules, 'sounddevice', SimpleNamespace(RawOutputStream=Stream))
    monkeypatch.setitem(sys.modules, 'ultimate_khorshid.interface.sun_bridge', SimpleNamespace(SunBridge=Sun))
    path = tmp_path/'chunk.wav'
    with wave.open(str(path), 'wb') as fp:
        fp.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        fp.writeframes(b'\x00\x01' * 12000)
    return controller, path, states, writes, aborts, wrote


def test_player_stops_current_chunk_and_discards_portaudio_buffer(audio_devices):
    controller, path, states, writes, aborts, wrote = audio_devices
    player = SmoothPlayer(controller)
    player.add(path)
    player.add(path)
    player.start()
    assert wrote.wait(2)
    player.thread.join(2)
    assert not player.thread.is_alive()
    assert len(writes) == 1  # Neither the rest of this WAV nor the next is sent.
    assert aborts == [True]
    assert states[-1] == 'idle'
    with pytest.raises(CancelledError):
        player.finish()


def test_player_cancels_while_waiting_for_first_chunk(audio_devices):
    controller, _, states, writes, _, _ = audio_devices
    player = SmoothPlayer(controller)
    player.start()
    controller.cancel()
    player.thread.join(2)
    assert not player.thread.is_alive()
    assert writes == []
    assert states[-1] == 'idle'


def test_player_restores_background_only_after_cancelled_output_is_aborted(audio_devices, monkeypatch):
    from contextlib import contextmanager
    controller, path, _, writes, aborts, wrote = audio_devices
    events=[]
    @contextmanager
    def duck():
        events.append('duck')
        try:
            yield
        finally:
            assert writes and aborts == [True]
            events.append('restore')
    monkeypatch.setattr('ultimate_khorshid.voice.tts_session.duck_other_audio', duck)
    player=SmoothPlayer(controller)
    player.add(path); player.start()
    assert wrote.wait(2)
    player.thread.join(2)
    assert not player.failure
    assert events == ['duck','restore']


def test_session_drains_cancelled_events_and_reuses_worker(monkeypatch, tmp_path):
    session = Session()
    controller = RunController()
    requests, closed, players = [], [], []
    class Input:
        def write(self, line):
            req = json.loads(line)
            requests.append(req)
            ident = req['id']
            if len(requests) == 1:
                controller.cancel()
                session.events.put({'type':'chunk', 'id':ident, 'path':'stale.wav'})
                session.events.put({'type':'error', 'id':ident, 'error':'cancelled'})
            else:
                session.events.put({'type':'done', 'id':ident, 'path':req['output']})
        def flush(self): pass
    class Player:
        thread = None
        failure = None
        def __init__(self, controller): self.paths = []; players.append(self)
        def start(self): pass
        def add(self, path): self.paths.append(path)
        def abort(self): pass
        def finish(self): pass
    session.proc = SimpleNamespace(stdin=Input())
    monkeypatch.setattr(session, 'start', lambda: None)
    monkeypatch.setattr(session, 'close', lambda: closed.append(True))
    import ultimate_khorshid.voice.tts_session as module
    monkeypatch.setattr(module, 'SmoothPlayer', Player)
    with use_controller(controller), pytest.raises(CancelledError):
        session.speak('old', str(tmp_path/'old.wav'))
    assert players[0].paths == []
    assert not closed
    assert session.events.empty()
    assert session.speak('new', str(tmp_path/'new.wav')) == str(tmp_path/'new.wav')
    assert len(requests) == 2
    assert players[1].paths == []


def test_precancelled_speech_does_not_start_models(monkeypatch):
    session = Session()
    monkeypatch.setattr(session, 'start', lambda: pytest.fail('Started cancelled request'))
    controller = RunController()
    controller.cancel()
    with use_controller(controller), pytest.raises(CancelledError):
        session.speak('cancelled', play_it=False)


def test_speak_text_preserves_cancellation_type(monkeypatch):
    from ultimate_khorshid.voice import engines, tts_session
    def cancelled(*args): raise CancelledError('cancelled')
    monkeypatch.setattr(tts_session, 'speak', cancelled)
    with pytest.raises(CancelledError):
        engines.speak_text('سلام')


@pytest.mark.parametrize('when', ['before', 'during'])
def test_runtime_uses_callers_controller_and_checks_agent_boundaries(tmp_path, monkeypatch, when):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    from ultimate_khorshid.core.config import KhorshidConfig
    from ultimate_khorshid.runtime import KhorshidRuntime
    from ultimate_khorshid.core import tracing
    monkeypatch.setattr(tracing, 'default_db', lambda: tmp_path/'traces.db')
    cfg = KhorshidConfig()
    cfg.agent.tools = ''
    cfg.intelligence.default_model = 'mock/test'
    cfg.storage.db_path = str(tmp_path/'memory.db')
    rt = KhorshidRuntime(cfg)
    called = []
    controller = RunController()
    def run(ctx):
        from ultimate_khorshid.agents.base import AgentResult
        called.append(True)
        controller.cancel()
        return AgentResult(content='late response')
    monkeypatch.setattr(rt, 'build_agent', lambda agent: SimpleNamespace(run=run))
    if when == 'before':
        controller.cancel()
    try:
        with use_controller(controller):
            result = rt.ask('hello', memory=False)
        assert result.metadata['cancelled']
        assert rt.last_controller is controller
        assert called == ([] if when == 'before' else [True])
    finally:
        rt.executor.shutdown()
