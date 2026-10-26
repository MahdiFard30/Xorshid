"""Tool input constraints and protocol-preserving context budgets."""
import copy
from types import SimpleNamespace

import pytest

from ultimate_khorshid.core.context import (
    ContextBudgetError, make_summarizer, messages_tokens, trim_messages,
)
from ultimate_khorshid.core.jsonx import parse_strict, validate_schema
from ultimate_khorshid.core.types import ToolCall, ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolExecutor, ToolSpec


@pytest.mark.parametrize('value,schema', [
    (True, {'type': 'integer'}), (False, {'type': 'number'}),
    (float('nan'), {}), ({'extra': float('inf')}, {'type': 'object'}),
    (1.5, {'type': 'integer'}), (-1, {'minimum': 0}),
    (11, {'maximum': 10}), (0, {'exclusiveMinimum': 0}),
    (10, {'exclusiveMaximum': 10}), (.31, {'multipleOf': .1}),
    ('', {'minLength': 1}), ('abcd', {'maxLength': 3}),
    ('wrong', {'pattern': '^ok$'}), ([1], {'minItems': 2}),
    ([1, 2], {'maxItems': 1}), ([1, 1.0], {'uniqueItems': True}),
    ({'x': 1}, {'additionalProperties': False}),
    ({'x': 'bad'}, {'additionalProperties': {'type': 'integer'}}),
    (True, {'enum': [1]}), ({'x': True}, {'const': {'x': 1}}),
    ([], False), (1, {'$ref': '#/$defs/value'}),
    (3, {'oneOf': [{'type': 'integer'}, {'type': 'number'}]}),
    (None, {'anyOf': [{'type': 'string'}, {'type': 'number'}]}),
    (2, {'allOf': [{'minimum': 0}, {'maximum': 1}]}),
    ('secret', {'not': {'const': 'secret'}}),
])
def test_rejects_invalid_values(value, schema):
    assert validate_schema(value, schema)


@pytest.mark.parametrize('value,schema', [
    (1.0, {'type': 'integer'}), (None, {'type': ['string', 'null']}),
    (0, {'minimum': 0, 'exclusiveMaximum': 10}),
    (.3, {'multipleOf': .1}), (1e200, {'multipleOf': .1}),
    ([True, 1], {'uniqueItems': True}),
    ({'x': 2}, {'additionalProperties': {'type': 'integer'}}),
    (True, {'enum': [True]}), (None, True),
    ('x', {'oneOf': [{'type': 'string'}, {'type': 'number'}]}),
    (2, {'allOf': [{'minimum': 0}, {'maximum': 3}]}),
])
def test_accepts_valid_values_without_coercion(value, schema):
    assert validate_schema(value, schema) == []


def test_checks_array_members_after_fiftieth_and_reports_nested_path():
    obj = {'rows': [1] * 60 + ['bad']}
    schema = {'properties': {'rows': {'items': {'type': 'integer'}}}}
    errors = validate_schema(obj, schema)
    assert len(errors) == 1 and '$.rows[60]' in errors[0]


def test_false_root_schema_and_nonfinite_json_are_rejected():
    assert parse_strict('{}', False)[1]
    assert parse_strict('{"n": NaN}', {'type': 'object'})[1]


def test_invalid_tool_input_never_reaches_approval_or_execution():
    calls = []
    class Probe(BaseTool):
        @property
        def spec(self):
            return ToolSpec(name='schema_probe', description='test', requires_confirmation=True,
                            parameters={'type':'object', 'required':['n'],
                                        'properties':{'n':{'type':'integer', 'minimum':1, 'maximum':5}},
                                        'additionalProperties':False})
        def execute(self, **params):
            calls.append(params)
            return ToolResult(tool_name='schema_probe', content='ok')
    approvals = []
    executor = ToolExecutor([Probe()], confirm_callback=lambda msg: approvals.append(msg) or True)
    try:
        for arguments in ('{"n":true}', '{"n":0}', '{"n":6}', '{"n":2,"extra":1}'):
            assert not executor.execute(ToolCall(name='schema_probe', arguments=arguments)).success
        assert not calls and not approvals
        assert executor.execute(ToolCall(name='schema_probe', arguments='{"n":2}')).success
        assert calls == [{'n':2}] and not approvals
    finally:
        executor.shutdown()


def exchange(ident='c1', result='result', args='{}'):
    return [
        {'role':'assistant', 'content':'', 'tool_calls':[
            {'id':ident, 'type':'function', 'function':{'name':'probe', 'arguments':args}}]},
        {'role':'tool', 'tool_call_id':ident, 'name':'probe', 'content':result},
    ]


def test_drops_old_turns_as_units_and_preserves_latest_user_and_exchange():
    system = {'role':'system', 'content':'instructions'}
    latest = [{'role':'user', 'content':'current request'}] + exchange('new')
    messages = [system, {'role':'user', 'content':'old ' * 1000}] + exchange('old') + latest
    budget = messages_tokens([system] + latest)
    out, dropped, used = trim_messages(messages, budget)
    assert out == [system] + latest
    assert dropped == 3
    assert used <= budget


def test_large_latest_tool_outputs_shorten_text_without_altering_protocol_or_input():
    latest = [{'role':'user', 'content':'keep my request'}] + exchange('first', 'x' * 5000)
    latest += exchange('second', 'y' * 5000)
    original = copy.deepcopy(latest)
    budget = messages_tokens([{**m, 'content':''} if m['role'] == 'tool' else m for m in latest]) + 90
    out, dropped, used = trim_messages(latest, budget)
    assert latest == original
    assert out[0] == latest[0]
    assert len(out) == len(latest) and dropped == 0 and used <= budget
    assert any('[trimmed]' in m.get('content', '') for m in out)
    assert [m.get('tool_calls') for m in out] == [m.get('tool_calls') for m in latest]
    assert [m.get('tool_call_id') for m in out] == [m.get('tool_call_id') for m in latest]


def test_long_single_user_message_is_actually_bounded():
    messages = [{'role':'user', 'content':'سلام دنیا ' * 1000}]
    out, dropped, used = trim_messages(messages, 80)
    assert used == messages_tokens(out) <= 80
    assert out[0]['content'].endswith('[trimmed]') and dropped == 0
    assert len(messages[0]['content']) > len(out[0]['content'])


def test_tool_arguments_count_and_cannot_be_truncated():
    messages = [{'role':'user', 'content':'do it'}] + exchange(args='x' * 10000)
    assert messages_tokens(messages) > 1000
    with pytest.raises(ContextBudgetError):
        trim_messages(messages, 100)
    assert messages[-2]['tool_calls'][0]['function']['arguments'] == 'x' * 10000


def test_system_budget_is_explicit_and_small_inputs_remain_unchanged():
    with pytest.raises(ContextBudgetError):
        trim_messages([{'role':'system', 'content':'x' * 1000}], 10)
    messages = [{'role':'system', 'content':'instructions'}, {'role':'user', 'content':'hello'}]
    assert trim_messages(messages, 1000)[0] == messages
    with pytest.raises(ContextBudgetError):
        trim_messages(messages, 0)


def test_summarizer_preserves_system_and_entire_latest_tool_turn():
    messages = [{'role':'system', 'content':'original instructions'},
                {'role':'user', 'content':'old request'}, {'role':'assistant', 'content':'old answer'},
                {'role':'user', 'content':'new request'}] + exchange()
    engine = SimpleNamespace(generate=lambda *args, **kwargs: {'content':'old history summary'})
    out = make_summarizer(engine, 'mock')(messages, keep_last=1)
    assert out[0] == messages[0]
    assert out[-3:] == messages[-3:]
    assert 'old history summary' in out[1]['content']


def test_failed_summary_preserves_original_history():
    def fail(*args, **kwargs): raise RuntimeError('offline')
    messages = [{'role':'user', 'content':'old'}, {'role':'assistant', 'content':'answer'},
                {'role':'user', 'content':'new'}]
    assert make_summarizer(SimpleNamespace(generate=fail), 'mock')(messages, 1) == messages


def test_empty_summary_preserves_original_history():
    messages = [{'role':'user', 'content':'old'}, {'role':'assistant', 'content':'answer'},
                {'role':'user', 'content':'new'}]
    engine = SimpleNamespace(generate=lambda *args, **kwargs: {'content':'  '})
    assert make_summarizer(engine, 'mock')(messages, 1) == messages


def test_multimodal_payload_is_preserved_or_explicitly_rejected():
    messages = [{'role':'user', 'content':[
        {'type':'text', 'text':'describe this'},
        {'type':'image_url', 'image_url':{'url':'data:image/png;base64,' + 'a' * 10000}},
    ]}]
    original = copy.deepcopy(messages)
    with pytest.raises(ContextBudgetError):
        trim_messages(messages, 100)
    assert messages == original
    assert trim_messages(messages, 10000)[0] == original


@pytest.mark.parametrize('schema', [{'type':{'bad':'type'}}, {'type':[]}, {'multipleOf':0}, {'pattern':'['}])
def test_malformed_constraints_produce_errors(schema):
    value = 'text' if 'pattern' in schema else 3
    assert validate_schema(value, schema)
