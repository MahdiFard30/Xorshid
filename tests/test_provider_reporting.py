from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from ultimate_khorshid.agents.base import provider_trace_ctx
from ultimate_khorshid.agents.simple import SimpleAgent
from ultimate_khorshid.core.config import KhorshidConfig
from ultimate_khorshid.core import tracing
from ultimate_khorshid.engine.base import EngineConnectionError
from ultimate_khorshid.engine.response_failover import ResponseFailover
from ultimate_khorshid.runtime import KhorshidRuntime


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(tracing, 'default_db', lambda: tmp_path/'traces.db')
    cfg = KhorshidConfig()
    cfg.agent.tools = 'calculator'
    cfg.agent.context_from_memory = False
    cfg.storage.db_path = str(tmp_path/'memory.db')
    rt = KhorshidRuntime(cfg)
    rt.model = 'gemini/requested'
    yield rt
    rt.executor.shutdown()


def test_fallback_metadata_footer_and_trace_use_actual_model(runtime):
    responses = iter([
        {'content':'', 'tool_calls':[{'name':'calculator','arguments':'{"expression":"2+2"}','id':'c1'}],
         'usage':{'prompt_tokens':0,'completion_tokens':0}},
        {'content':'چهار', 'tool_calls':[], 'usage':{'prompt_tokens':11,'completion_tokens':7}},
    ])
    def failed(*args, **kwargs): raise EngineConnectionError('HTTP 429')
    primary = SimpleNamespace(engine_id='gemini', generate=failed)
    cloud = SimpleNamespace(engine_id='groq', generate=lambda *a, **kw: next(responses))
    runtime.engine = ResponseFailover(primary, runtime.cfg, cloud, 'openai/gpt-oss-120b')
    result = runtime.ask('حاصل محاسبه را بگو', memory=False)
    assert result.metadata['engine'] == 'groq'
    assert result.metadata['model'] == 'openai/gpt-oss-120b'
    assert result.metadata['fallback'] is True
    assert result.metadata['usage'] == {'input_tokens':11,'output_tokens':7,'estimated':False}
    assert len(result.metadata['provider_calls']) == 2
    assert 'مدل: openai/gpt-oss-120b' in result.content
    assert 'مدل: gemini/requested' not in result.content
    detail = tracing.Tracer().trace_detail(result.metadata['trace_id'])
    assert [(u['engine'], u['model']) for u in detail['usage']] == [('groq','openai/gpt-oss-120b')] * 2
    assert detail['usage'][0]['in'] == detail['usage'][0]['out'] == 0
    # A subsequent primary success must not retain any earlier fallback data.
    primary.generate = lambda *a, **kw: {'content':'سلام', 'usage':{'input_tokens':2,'output_tokens':1}}
    fresh = runtime.ask('سلام', memory=False)
    assert fresh.metadata['engine'] == 'gemini'
    assert fresh.metadata['model'] == 'gemini/requested'
    assert fresh.metadata['fallback'] is False
    assert len(fresh.metadata['provider_calls']) == 1


@pytest.mark.parametrize('usage,estimated', [({},True), ({'prompt_tokens':0,'completion_tokens':0},False),
                                           ({'prompt_tokens':'bad','completion_tokens':-3},True)])
def test_estimated_and_reported_zero_tokens_are_distinct(usage, estimated):
    engine = SimpleNamespace(engine_id='mock', generate=lambda *a, **kw: {'content':'hello', 'usage':usage})
    agent = SimpleAgent(engine, 'mock/smart')
    with provider_trace_ctx() as records:
        agent._generate([{'role':'user','content':'hello'}])
    assert len(records) == 1
    assert records[0]['input_estimated'] is estimated
    assert records[0]['output_estimated'] is estimated
    if not estimated:
        assert records[0]['input_tokens'] == records[0]['output_tokens'] == 0


def test_provider_records_are_isolated_between_concurrent_requests():
    barrier = threading.Barrier(2)
    def run(name):
        def generate(*args, **kwargs):
            barrier.wait(timeout=2)
            return {'content':'hello','provider':{'engine':name,'model':name+'/model'}}
        agent = SimpleAgent(SimpleNamespace(engine_id='configured',generate=generate), 'configured/model')
        with provider_trace_ctx() as records:
            agent._generate([{'role':'user','content':'hello'}])
        return records
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, name) for name in ('groq', 'ollama')]
        results = [f.result(timeout=3) for f in futures]
    assert [[r['engine'] for r in records] for records in results] == [['groq'], ['ollama']]


def test_server_exposes_provider_metadata_without_unrelated_private_fields(monkeypatch):
    from ultimate_khorshid.server import app
    metadata = {'engine':'groq','model':'actual/model','fallback':True,
                'usage':{'input_tokens':3,'output_tokens':4,'estimated':False},
                'unrelated_private_field':'must not be returned'}
    fake = SimpleNamespace(ask=lambda *a, **kw: SimpleNamespace(content='hello',turns=1,
                          tool_results=[],metadata=metadata), executor=SimpleNamespace(shutdown=lambda:None))
    monkeypatch.setattr('ultimate_khorshid.runtime.KhorshidRuntime', lambda cfg: fake)
    monkeypatch.setattr(app, 'load_config', KhorshidConfig)
    result = app._run_query('hello','simple')
    assert result['metadata']['engine'] == 'groq'
    assert result['metadata']['model'] == 'actual/model'
    assert 'unrelated_private_field' not in result['metadata']


def test_mixed_providers_within_one_turn_keep_separate_usage(runtime):
    count = 0
    def primary(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            raise EngineConnectionError('HTTP 429')
        return {'content':'چهار', 'usage':{'prompt_tokens':8,'completion_tokens':4}}
    cloud = SimpleNamespace(engine_id='groq', generate=lambda *a, **kw: {
        'content':'', 'tool_calls':[{'name':'calculator','arguments':'{"expression":"2+2"}','id':'c1'}],
        'usage':{'prompt_tokens':5,'completion_tokens':2}})
    runtime.engine = ResponseFailover(SimpleNamespace(engine_id='gemini',generate=primary),runtime.cfg,cloud,'cloud/model')
    result = runtime.ask('حاصل محاسبه را بگو', memory=False)
    assert [p['engine'] for p in result.metadata['provider_calls']] == ['groq','gemini']
    assert result.metadata['engine'] == 'gemini'
    assert result.metadata['usage'] == {'input_tokens':13,'output_tokens':6,'estimated':False}


def test_buffered_fallback_stream_keeps_actual_provider(runtime):
    def fail(*args, **kwargs): raise EngineConnectionError('HTTP 429')
    cloud = SimpleNamespace(engine_id='groq', generate=lambda *a, **kw: {'content':'سلام'})
    runtime.engine = ResponseFailover(SimpleNamespace(engine_id='gemini',generate=fail),runtime.cfg,cloud,'cloud/model')
    chunks = []
    result = runtime.ask('سلام', agent='simple', memory=False, on_token=chunks.append)
    assert ''.join(chunks) == result.content == 'سلام'
    assert result.metadata['engine'] == 'groq'
    assert result.metadata['model'] == 'cloud/model'
    assert len(result.metadata['provider_calls']) == 1


def test_http_chat_and_compatible_api_report_actual_provider_and_usage(monkeypatch):
    import json
    import urllib.request
    from http.server import ThreadingHTTPServer
    from ultimate_khorshid.server import app
    metadata = {'engine':'groq','model':'actual/model','fallback':True,
                'usage':{'input_tokens':3,'output_tokens':4,'estimated':True}}
    monkeypatch.setattr(app, '_run_query', lambda *a, **kw: {'content':'hello','turns':1,'tools':[],
                                                          'tools_used':[],'metadata':metadata})
    monkeypatch.setattr(app, 'hist_add', lambda *a: None)
    server = ThreadingHTTPServer(('127.0.0.1',0), app.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def post(path, data):
        request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path,
                                         data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=5) as response:
            return json.loads(response.read())
    try:
        chat = post('/api/chat', {'message':'hello'})
        assert chat['metadata'] == metadata
        response = post('/v1/chat/completions', {'model':'requested/model','messages':[{'role':'user','content':'hello'}]})
        assert response['model'] == 'actual/model'
        assert response['usage'] == {'prompt_tokens':3,'completion_tokens':4,'total_tokens':7}
        assert response['usage_estimated'] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
