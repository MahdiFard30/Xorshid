import copy
from types import SimpleNamespace

import pytest

from ultimate_khorshid.core.config import KhorshidConfig
from ultimate_khorshid.core.control import CancelledError, RunController, use_controller
from ultimate_khorshid.engine.base import EngineConnectionError
from ultimate_khorshid.engine.response_failover import ResponseFailover


@pytest.fixture(autouse=True)
def no_real_cloud_credentials(monkeypatch):
    monkeypatch.setattr('ultimate_khorshid.engine.groq.GroqEngine',
                        lambda **kwargs: SimpleNamespace(api_key=''))


def chain(outcomes):
    calls = []
    def engine(name):
        def generate(messages, model, **kwargs):
            calls.append((name, model, copy.deepcopy(messages)))
            result = outcomes.get(name, EngineConnectionError('HTTP 429'))
            messages.clear()  # A provider must not mutate the next one's input.
            if isinstance(result, Exception):
                raise result
            return result
        return SimpleNamespace(engine_id=name, generate=generate)
    cfg = KhorshidConfig()
    cfg.engine.ollama_model = 'configured-local-model'
    wrapper = ResponseFailover(engine('gemini'), cfg, engine('cloud'), 'configured-cloud-model')
    wrapper.local, wrapper.mock = engine('ollama'), engine('mock')
    return wrapper, calls


@pytest.mark.parametrize('winner', ['gemini', 'cloud', 'ollama', 'mock'])
def test_uses_exact_order_and_stops_at_first_success(winner):
    result = {'content':'ok', 'tool_calls':[], 'usage':{}}
    wrapper, calls = chain({winner:result})
    messages = [{'role':'user','content':'hello'}]
    answer = wrapper.generate(messages, 'gemini/test')
    order = ['gemini', 'cloud', 'ollama', 'mock']
    assert [name for name, _, _ in calls] == order[:order.index(winner)+1]
    assert all(history == messages for _, _, history in calls)
    assert answer['provider']['engine'] == winner
    assert answer['provider']['failed_providers'] == order[:order.index(winner)]
    assert 'provider' not in result
    assert wrapper.last_engine == winner
    if winner == 'cloud':
        assert wrapper.last_model == 'configured-cloud-model'
    if winner == 'ollama':
        assert wrapper.last_model == 'configured-local-model'


@pytest.mark.parametrize('failure', ['HTTP 400', 'HTTP 401', 'HTTP 403', 'HTTP 404',
                                      'HTTP 429', 'HTTP 503', 'timed out', 'missing key'])
def test_unavailability_moves_to_next_service_without_retry(failure):
    wrapper, calls = chain({'gemini':EngineConnectionError(failure), 'cloud':{'content':'ok'}})
    assert wrapper.generate([], 'gemini/test')['content'] == 'ok'
    assert [c[0] for c in calls] == ['gemini', 'cloud']


def test_empty_answer_switches_and_tool_only_answer_counts_as_success():
    tool_calls = [{'name':'probe','arguments':'{}','id':'c1'}]
    wrapper, calls = chain({'gemini':{}, 'cloud':{'content':'', 'tool_calls':tool_calls}})
    assert wrapper.generate([], 'gemini/test')['tool_calls'] == tool_calls
    assert len(calls) == 2


def test_cancellation_never_invokes_fallback():
    wrapper, calls = chain({'gemini':CancelledError('cancelled')})
    with pytest.raises(CancelledError):
        wrapper.generate([], 'gemini/test')
    assert len(calls) == 1
    controller = RunController()
    controller.cancel()
    calls.clear()
    with use_controller(controller), pytest.raises(CancelledError):
        wrapper.generate([], 'gemini/test')
    assert calls == []


def test_programming_errors_and_policy_blocks_are_not_retried():
    for error in (ValueError('bug'), EngineConnectionError('blocked by policy')):
        wrapper, calls = chain({'gemini':error})
        with pytest.raises(type(error)):
            wrapper.generate([], 'gemini/test')
        assert len(calls) == 1


def test_no_configured_cloud_skips_directly_to_local_then_mock():
    wrapper, calls = chain({'mock':{'content':'offline'}})
    wrapper.cloud = None
    assert wrapper.generate([], 'gemini/test')['content'] == 'offline'
    assert [c[0] for c in calls] == ['gemini', 'ollama', 'mock']


def test_failed_provider_text_is_not_retained_in_metadata():
    wrapper, _ = chain({'gemini':EngineConnectionError('secret-key-value'), 'cloud':{'content':'ok'}})
    assert 'secret-key-value' not in str(wrapper.generate([], 'gemini/test'))


def test_gemini_empty_response_is_distinct_from_policy_block():
    from ultimate_khorshid.engine.gemini import parse_response
    with pytest.raises(EngineConnectionError, match='empty response'):
        parse_response({})
    with pytest.raises(EngineConnectionError, match='blocked'):
        parse_response({'promptFeedback':{'blockReason':'SAFETY'}})
