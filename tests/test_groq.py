import copy
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ultimate_khorshid.core.config import KhorshidConfig, apply_environment, load_config
from ultimate_khorshid.engine.base import EngineConnectionError
from ultimate_khorshid.engine.groq import GroqEngine


@pytest.fixture(autouse=True)
def isolated_key(monkeypatch, tmp_path):
    from ultimate_khorshid.core import vault
    from ultimate_khorshid.engine import groq
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    monkeypatch.setattr(vault, 'get_secret', lambda name, fallback='': os.environ.get(name) or fallback)
    monkeypatch.setattr(groq, 'KEY_FILE', tmp_path/'.groq.key')
    return groq.KEY_FILE


def test_dedicated_key_file_and_environment_precedence(isolated_key, monkeypatch):
    isolated_key.write_text('file-key\n')
    monkeypatch.setenv('OPENAI_API_KEY', 'wrong-service-key')
    monkeypatch.setenv('OPENAI_BASE_URL', 'http://wrong-service.invalid')
    assert GroqEngine().api_key == 'file-key'
    monkeypatch.setenv('GROQ_API_KEY', 'environment-key')
    assert GroqEngine().api_key == 'environment-key'
    assert GroqEngine(api_key='explicit-key').api_key == 'explicit-key'
    assert GroqEngine().base_url == 'https://api.groq.com/openai/v1'


def test_missing_key_never_uses_openai_key_or_network(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'wrong-service-key')
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **kw: pytest.fail('Network used without key'))
    engine = GroqEngine()
    assert engine.api_key == ''
    with pytest.raises(EngineConnectionError):
        engine.generate([], 'openai/gpt-oss-120b')
    with pytest.raises(EngineConnectionError):
        list(engine.generate_stream([], 'openai/gpt-oss-120b'))


@pytest.mark.parametrize('model', ['openai/gpt-oss-120b', 'groq/openai/gpt-oss-120b'])
def test_payload_uses_complete_model_id_and_preserves_input(model):
    messages = [
        {'role':'assistant', 'content':'', 'tool_calls':[{
            'id':'call-1', 'type':'function', 'function':{'name':'probe','arguments':'{}'},
            'thought_signature':'gemini-only',
        }]},
        {'role':'tool', 'name':'probe', 'tool_call_id':'call-1', 'content':'ok'},
    ]
    original = copy.deepcopy(messages)
    payload = GroqEngine(api_key='test-key')._payload(messages, model)
    assert payload['model'] == 'openai/gpt-oss-120b'
    assert 'name' not in payload['messages'][1]
    assert payload['messages'][1]['tool_call_id'] == 'call-1'
    assert 'thought_signature' not in payload['messages'][0]['tool_calls'][0]
    assert messages == original


def test_native_http_adapter_sends_only_to_groq(monkeypatch):
    sent = []
    def urlopen(req, **kwargs):
        sent.append(req)
        return io.BytesIO(json.dumps({'choices':[{'message':{'content':'سلام'}, 'finish_reason':'stop'}],
                                     'usage':{'prompt_tokens':10,'completion_tokens':2}}).encode())
    monkeypatch.setattr('urllib.request.urlopen', urlopen)
    result = GroqEngine(api_key='fake-key').generate([{'role':'user','content':'سلام'}], 'openai/gpt-oss-120b')
    assert result['content'] == 'سلام'
    assert sent[0].full_url == 'https://api.groq.com/openai/v1/chat/completions'
    assert sent[0].get_header('Authorization') == 'Bearer fake-key'
    assert sent[0].get_header('User-agent') == 'Khorshid/2.0'
    assert json.loads(sent[0].data)['model'] == 'openai/gpt-oss-120b'


def test_config_nested_keys_do_not_override_openai(tmp_path, monkeypatch):
    for name in ('KHORSHID_CONFIG', 'KHORSHID_MODEL', 'KHORSHID_ENGINE', 'KHORSHID_GROQ_MODEL'):
        monkeypatch.delenv(name, raising=False)
    config = tmp_path/'config.toml'
    config.write_text('[engine.groq]\napi_key="config-groq-key"\nmodel="openai/gpt-oss-20b"\n')
    cfg = load_config(config)
    assert cfg.engine.groq_api_key == 'config-groq-key'
    assert cfg.engine.openai_api_key != 'config-groq-key'
    monkeypatch.setenv('GROQ_API_KEY', 'environment-key')
    monkeypatch.setenv('KHORSHID_GROQ_MODEL', 'openai/gpt-oss-120b')
    apply_environment(cfg)
    assert cfg.engine.groq_model == 'openai/gpt-oss-120b'
    assert cfg.engine.groq_api_key == 'environment-key'


def test_groq_is_discoverable_without_changing_primary():
    from ultimate_khorshid.engine.discovery import engine_for_model
    cfg = KhorshidConfig()
    cfg.engine.groq_api_key = 'config-key'
    engine = engine_for_model('groq/openai/gpt-oss-120b', cfg)
    assert engine.engine_id == 'groq'
    assert engine.api_key == 'config-key'


def test_groq_automatically_occupies_second_position(isolated_key):
    from ultimate_khorshid.engine.response_failover import ResponseFailover
    isolated_key.write_text('local-test-key')
    primary = SimpleNamespace(engine_id='gemini')
    wrapper = ResponseFailover(primary, KhorshidConfig())
    stages = list(wrapper._providers('gemini/test'))
    assert [name for name, _, _ in stages] == ['gemini', 'groq', 'ollama', 'mock']
    assert stages[1][1] == 'openai/gpt-oss-120b'


def test_unconfigured_groq_is_skipped_without_request():
    from ultimate_khorshid.engine.response_failover import ResponseFailover
    wrapper = ResponseFailover(SimpleNamespace(engine_id='gemini'), KhorshidConfig())
    assert [name for name, _, _ in wrapper._providers('gemini/test')] == ['gemini', 'ollama', 'mock']


def test_audio_upload_uses_transcription_endpoint_and_original_audio(tmp_path, monkeypatch):
    path = tmp_path/'recording.wav'
    path.write_bytes(b'original-pcm-file')
    sent = []
    def urlopen(request, **kwargs):
        sent.append(request)
        return io.BytesIO(json.dumps({'text':' سلام خورشید '}).encode())
    monkeypatch.setattr('urllib.request.urlopen', urlopen)
    assert GroqEngine(api_key='fake-key').transcribe(path) == 'سلام خورشید'
    req = sent[0]
    assert req.full_url == 'https://api.groq.com/openai/v1/audio/transcriptions'
    assert b'original-pcm-file' in req.data
    assert b'whisper-large-v3-turbo' in req.data
    assert b'name="language"\r\n\r\nfa\r\n' in req.data
    assert req.get_header('Content-type').startswith('multipart/form-data; boundary=')
    assert req.get_header('User-agent') == 'Khorshid/2.0'


@pytest.mark.parametrize('gemini_available', [True, False])
def test_stt_uses_groq_when_gemini_unavailable(monkeypatch, gemini_available):
    from ultimate_khorshid.voice import engines
    cfg = KhorshidConfig()
    cfg.engine.groq_api_key = 'fake-groq-key'
    monkeypatch.setattr('ultimate_khorshid.core.config.load_config', lambda: cfg)
    monkeypatch.setattr(engines, 'api_key', lambda: 'fake-gemini-key' if gemini_available else '')
    def fail(*args, **kwargs): raise RuntimeError('quota exceeded')
    monkeypatch.setattr(engines.GeminiSTT, 'transcribe', fail)
    calls = []
    monkeypatch.setattr(GroqEngine, 'transcribe', lambda self, path: calls.append(path) or 'سلام')
    assert engines.transcribe_file('test.wav', engine='gemini') == 'سلام'
    assert calls == ['test.wav']


def test_successful_gemini_stt_never_contacts_groq(monkeypatch):
    from ultimate_khorshid.voice import engines
    monkeypatch.setattr(engines, 'api_key', lambda: 'fake-key')
    monkeypatch.setattr(engines.GeminiSTT, 'transcribe', lambda self, path: 'سلام')
    monkeypatch.setattr(GroqEngine, 'transcribe', lambda *a: pytest.fail('Unnecessary audio upload'))
    assert engines.transcribe_file('test.wav', engine='gemini') == 'سلام'


def test_stt_cancellation_does_not_upload_to_fallback(monkeypatch):
    from ultimate_khorshid.core.control import CancelledError, RunController, use_controller
    from ultimate_khorshid.voice import engines
    controller = RunController()
    monkeypatch.setattr(engines, 'api_key', lambda: 'fake-key')
    def fail(*args):
        controller.cancel()
        raise RuntimeError('previous request failed')
    monkeypatch.setattr(engines.GeminiSTT, 'transcribe', fail)
    monkeypatch.setattr(GroqEngine, 'transcribe', lambda *a: pytest.fail('Cancelled audio uploaded'))
    with use_controller(controller), pytest.raises(CancelledError):
        engines.transcribe_file('test.wav', engine='gemini')
