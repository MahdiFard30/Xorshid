"""No repeat permission prompts; trading policy and at-most-once writes remain."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ultimate_khorshid.core.types import ToolCall, ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolExecutor, ToolSpec


class Probe(BaseTool):
    def __init__(self, name, *, success=True):
        self.name = name
        self.calls = []
        self.success = success

    @property
    def spec(self):
        # Legacy extensions cannot reintroduce non-trading prompts.
        return ToolSpec(name=self.name, description='test', requires_confirmation=True,
                        parameters={'type': 'object'})

    def execute(self, **params):
        self.calls.append(params)
        return ToolResult(tool_name=self.name, content='done', success=self.success)


@pytest.mark.parametrize('name', [
    'browser_click', 'browser_type', 'browser_press', 'browser_check',
    'browser_select_option', 'mouse_click', 'type_text', 'key_press',
    'key_hotkey', 'vision_click', 'shell_exec', 'python_exec', 'file_delete',
    'file_write', 'file_edit', 'file_copy', 'file_move', 'git',
    'http_request', 'clipboard', 'custom_agent_tool',
])
def test_nontrading_actions_do_not_prompt_or_duplicate_failures(name):
    tool = Probe(name, success=False)
    callback = Mock(side_effect=AssertionError('No prompt expected'))
    executor = ToolExecutor([tool], confirm_callback=callback, retry_on_failure=True, max_retries=3)
    try:
        result = executor.execute(ToolCall(name=name))
        assert not result.success
        assert tool.calls == [{}]
        assert not result.metadata.get('approval_required')
        callback.assert_not_called()
    finally:
        executor.shutdown()


@pytest.mark.parametrize('name', ['shell_exec', 'python_exec', 'browser_click'])
def test_live_nontrading_bridge_runs_tools_without_dialogs(name):
    from ultimate_khorshid.interface.khorshid_gemini_live_runner import execute_tool
    tool = Probe(name)
    executor = ToolExecutor([tool])
    runtime = SimpleNamespace(executor=executor)
    try:
        catalog = execute_tool(runtime, 'khorshid_list_tools', {})['tools']
        assert catalog[0]['requires_confirmation'] is False
        result = execute_tool(runtime, 'khorshid_execute_tool', {
            'tool_name': name, 'arguments_json': '{}'})
        assert result['success'] and tool.calls == [{}]
    finally:
        executor.shutdown()


@pytest.mark.parametrize('action', ['start', 'stop'])
def test_live_trading_mutation_policy_is_unchanged(action):
    from ultimate_khorshid.interface.khorshid_gemini_live_runner import execute_tool
    tool = Probe('mt5_demo')
    executor = ToolExecutor([tool])
    try:
        result = execute_tool(SimpleNamespace(executor=executor), 'khorshid_execute_tool', {
            'tool_name': 'mt5_demo', 'arguments_json': json.dumps({'action': action})})
        assert not result['success']
        assert not tool.calls
    finally:
        executor.shutdown()


def test_explicit_cli_forget_does_not_prompt(monkeypatch, tmp_path):
    from ultimate_khorshid.cli import main
    from ultimate_khorshid.core.config import KhorshidConfig
    from ultimate_khorshid.core import config
    from ultimate_khorshid.memory import automatic, store
    cfg = KhorshidConfig()
    cfg.storage.db_path = str(tmp_path / 'memory.db')
    monkeypatch.setattr(config, 'load_config', lambda _: cfg)
    monkeypatch.setattr(store, 'get_memory', Mock())
    memory = Mock()
    monkeypatch.setattr(automatic, 'AutomaticMemory', Mock(return_value=memory))
    prompt = Mock(side_effect=AssertionError('No prompt expected'))
    monkeypatch.setattr(main, '_confirm', prompt)
    args = main.build_parser().parse_args(['memory', '--forget-all'])
    assert main.cmd_memory(args) == 0
    memory.clear.assert_called_once_with(everything=True)
    prompt.assert_not_called()


@pytest.mark.parametrize('install', [False, True])
def test_selected_setup_extras_do_not_ask_for_install_confirmation(monkeypatch, tmp_path, install):
    from ultimate_khorshid.cli import setup_wizard as wizard
    from ultimate_khorshid.core import settings
    monkeypatch.setattr(settings, 'settings_path', lambda: tmp_path / 'settings.json')
    prompt = Mock(side_effect=AssertionError('All choices supplied; no question expected'))
    monkeypatch.setattr(wizard, '_ask', prompt)
    pip = Mock(return_value=True)
    chromium = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(wizard, 'pip_install', pip)
    monkeypatch.setattr(wizard.subprocess, 'run', chromium)
    assert wizard.run_setup(engine='mock', extras='browser', hotkey='ctrl',
                            yes=False, base_dir=tmp_path, install=install) == 0
    prompt.assert_not_called()
    if install:
        pip.assert_called_once_with('browser')
        assert chromium.call_args.args[0][-3:] == ['playwright', 'install', 'chromium']
    else:
        pip.assert_not_called()
        chromium.assert_not_called()
