"""Regression tests for shared permissions and deterministic configuration.

No microphones, GUI windows, broker calls, model downloads or external services.
"""
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ultimate_khorshid.core.config import KhorshidConfig
from ultimate_khorshid.core.types import ToolCall, ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolExecutor, ToolSpec


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    original = os.path.expanduser
    def expand(p):
        value = os.fspath(p)
        if value == "~":
            return str(tmp_path)
        return str(tmp_path / value[2:]) if value.startswith("~/") else original(p)
    monkeypatch.setattr(os.path, "expanduser", expand)
    for key in ("KHORSHID_CONFIG", "KHORSHID_ENGINE", "KHORSHID_MODEL", "KHORSHID_VOICE",
                "KHORSHID_AGENT", "KHORSHID_LANG", "KHORSHID_OPENAI_MODEL"):
        monkeypatch.delenv(key, raising=False)
    import ultimate_khorshid.core.config as C
    monkeypatch.setattr(C, "DEFAULT_CONFIG_PATHS", [tmp_path / "default.toml"])
    return tmp_path


class Probe(BaseTool):
    def __init__(self, name="file_write", confirmation=False):
        self.name, self.confirmation, self.calls = name, confirmation, []

    @property
    def spec(self):
        return ToolSpec(name=self.name, description="No-op test tool",
                        parameters={"type": "object"}, requires_confirmation=self.confirmation)

    def execute(self, **params):
        self.calls.append(params)
        return ToolResult(tool_name=self.name, content="ok")


@pytest.mark.parametrize("interactive", [True, False])
@pytest.mark.parametrize("approved", [True, False, None])
def test_nontrading_runs_without_callback_in_every_mode(interactive, approved):
    tool = Probe()
    callback = None if approved is None else Mock(return_value=approved)
    ex = ToolExecutor([tool], interactive=interactive, confirm_callback=callback)
    try:
        result = ex.execute(ToolCall(name=tool.name, arguments='{"path":"example.txt"}'))
        assert result.success
        assert tool.calls == [{"path": "example.txt"}]
        if callback:
            callback.assert_not_called()
        assert not result.metadata.get("approval_required")
    finally:
        ex.shutdown()


@pytest.mark.parametrize("allow_unconfirmed", [False, True])
def test_declared_custom_tool_does_not_prompt(allow_unconfirmed):
    tool = Probe(name="custom", confirmation=True)
    ex = ToolExecutor([tool], allow_unconfirmed=allow_unconfirmed)
    try:
        assert ex.execute(ToolCall(name="custom")).success
    finally:
        ex.shutdown()


@pytest.mark.parametrize("name,params,required", [
    ("git", {"action": "status"}, False), ("git", {"action": "push"}, True),
    ("http_request", {"method": "GET"}, False), ("http_request", {"method": "DELETE"}, True),
    ("mt5_demo", {"action": "status"}, False), ("mt5_demo", {"action": "start"}, True),
    ("mt5_demo", {"action": "stop"}, False), ("clipboard", {"action": "set"}, True),
    ("browser_click", {"ref": "0"}, True), ("calculator", {}, False),
    ("open_app", {"target": "فایرفاکس"}, False),
])
def test_action_policy(name, params, required):
    from ultimate_khorshid.security.permissions import approval_required, is_mutating
    spec = Probe(name).spec
    assert is_mutating(spec, params) is required
    assert approval_required(spec, params) is (required and name == "mt5_demo")


def test_large_nontrading_operation_is_not_blocked_by_dialog_limits():
    tool = Probe()
    callback = Mock(return_value=True)
    ex = ToolExecutor([tool], confirm_callback=callback)
    try:
        text = "x" * 500 + "END_OF_OPERATION"
        assert ex.execute(ToolCall(name=tool.name, arguments=json.dumps({"content": text}))).success
        assert ex.execute(ToolCall(name=tool.name, arguments=json.dumps({"content": "x" * 13000}))).success
        assert tool.calls == [{"content": text}, {"content": "x" * 13000}]
        callback.assert_not_called()
    finally:
        ex.shutdown()


def test_no_retry_of_nontrading_mutation_without_confirmation():
    tool = Probe()
    tool.execute = Mock(return_value=ToolResult(tool_name=tool.name, content="failed", success=False))
    ex = ToolExecutor([tool], confirm_callback=lambda _: True, retry_on_failure=True, max_retries=3)
    try:
        assert not ex.execute(ToolCall(name=tool.name)).success
        tool.execute.assert_called_once()
    finally:
        ex.shutdown()


def test_app_launcher_cannot_resolve_arbitrary_commands(monkeypatch, tmp_path):
    from ultimate_khorshid.tools import app_launcher as A
    monkeypatch.setattr(A, "catalog", lambda: [])
    with pytest.raises(ValueError):
        A.resolve('sh -c "echo probe"')
    script = tmp_path / "run.py"
    script.write_text("print('never executed')")
    with pytest.raises(ValueError):
        A.resolve(str(script))


def test_installed_app_resolution_is_preserved(monkeypatch):
    from ultimate_khorshid.tools import app_launcher as A
    monkeypatch.setattr(A, "catalog", lambda: [{"id": "code.desktop", "name": "Code",
                        "names": ["Code"], "path": "/apps/code.desktop"}])
    monkeypatch.setattr(A.shutil, "which", lambda _: "/usr/bin/gio")
    assert A.resolve("code")[0] == ["/usr/bin/gio", "launch", "/apps/code.desktop"]


def test_direct_trading_obeys_approval_and_memory(isolated, monkeypatch):
    from ultimate_khorshid.runtime import KhorshidRuntime
    from ultimate_khorshid.tools.mt5_demo import MT5DemoTool
    from ultimate_khorshid.memory.automatic import AutomaticMemory
    execute = Mock(return_value=ToolResult(tool_name="mt5_demo", content="status ok"))
    monkeypatch.setattr(MT5DemoTool, "execute", execute)
    cfg = KhorshidConfig()
    cfg.storage.db_path = str(isolated / "memory.db")
    rt = KhorshidRuntime(cfg)
    try:
        denied = rt.ask("شروع تمرین دمو")
        assert not denied.tool_results[0].success
        execute.assert_not_called()
        status = rt.ask("وضعیت معاملات")
        assert status.content == "status ok"
        execute.assert_called_once_with(action="status")
        assert status.metadata["trace_id"]
        assert AutomaticMemory(cfg.storage.db_path).status()["turns"] == 2
    finally:
        rt.executor.shutdown()


def test_empty_tool_allowlist_blocks_direct_route(isolated, monkeypatch):
    from ultimate_khorshid.runtime import KhorshidRuntime
    from ultimate_khorshid.tools.mt5_demo import MT5DemoTool
    execute = Mock()
    monkeypatch.setattr(MT5DemoTool, "execute", execute)
    cfg = KhorshidConfig()
    cfg.agent.tools = ""
    rt = KhorshidRuntime(cfg)
    try:
        assert rt.tool_names == []
        result = rt.ask("وضعیت معاملات", memory=False)
        assert not result.tool_results[0].success
        execute.assert_not_called()
    finally:
        rt.executor.shutdown()


def test_settings_clear_and_environment_precedence(isolated, monkeypatch):
    from ultimate_khorshid.core import settings as S, config as C
    (isolated / "default.toml").write_text('[engine]\nvoice="Charon"\n')
    assert S.get_settings()["voice"] == ""
    assert C.load_config().engine.voice == "Charon"
    S.set_settings(engine="gemini", model="gemini/test-model", voice="Kore")
    assert C.load_config().intelligence.default_model == "gemini/test-model"
    monkeypatch.setenv("KHORSHID_MODEL", "ollama/local-model")
    monkeypatch.setenv("KHORSHID_VOICE", "Aoede")
    cfg = C.load_config()
    assert cfg.intelligence.default_model == "ollama/local-model"
    assert cfg.engine.default == "ollama" and cfg.engine.voice == "Aoede"
    monkeypatch.delenv("KHORSHID_MODEL")
    monkeypatch.delenv("KHORSHID_VOICE")
    S.set_settings(engine="", model="", voice="")
    cfg = C.load_config()
    assert cfg.intelligence.default_model == "mock/smart" and cfg.engine.voice == "Charon"


def test_engine_only_choice_selects_matching_model(isolated, monkeypatch):
    from ultimate_khorshid.core import settings as S, config as C
    S.set_settings(model="gemini/old")
    S.set_settings(engine="ollama")
    assert C.load_config().intelligence.default_model.startswith("ollama/")
    monkeypatch.setenv("KHORSHID_ENGINE", "mock")
    assert C.load_config().intelligence.default_model == "mock/smart"


def test_explicit_config_and_runtime_do_not_reapply_dashboard(isolated):
    from ultimate_khorshid.core import settings as S, config as C
    from ultimate_khorshid.runtime import KhorshidRuntime
    S.set_settings(model="gemini/override")
    path = isolated / "explicit.toml"
    path.write_text('[intelligence]\ndefault_model="mock/smart"\n')
    cfg = C.load_config(path)
    rt = KhorshidRuntime(cfg)
    try:
        assert rt.engine.engine_id == "mock"
    finally:
        rt.executor.shutdown()


def test_broken_or_missing_config_does_not_fall_back(isolated):
    from ultimate_khorshid.core.config import load_config
    with pytest.raises(FileNotFoundError):
        load_config(isolated / "missing.toml")
    path = isolated / "broken.toml"
    path.write_text("invalid [toml")
    with pytest.raises(ValueError, match="Cannot read config"):
        load_config(path)


def test_home_config_has_priority_over_project_default():
    from ultimate_khorshid.core.config import DEFAULT_CONFIG_PATHS
    assert DEFAULT_CONFIG_PATHS[0].name == "config.toml"
    assert DEFAULT_CONFIG_PATHS[1] == Path("configs/default.toml")


def test_gui_confirmation_fail_closed(monkeypatch):
    from ultimate_khorshid.core import approval as A
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="approved\n"))
    monkeypatch.setattr(A.subprocess, "run", run)
    monkeypatch.delenv("KHORSHID_CONFIRM_GUI", raising=False)
    assert not A.desktop_confirm("test")
    run.assert_not_called()
    monkeypatch.setenv("KHORSHID_CONFIRM_GUI", "1")
    assert A.desktop_confirm("test")
    assert run.call_args.kwargs["input"] == json.dumps({"message": "test"}, ensure_ascii=False)
    run.return_value = SimpleNamespace(returncode=1, stdout="approved")
    assert not A.desktop_confirm("test")
    run.side_effect = A.subprocess.TimeoutExpired("dialog", 120)
    assert not A.desktop_confirm("test")


def test_live_tools_share_executor_policy(isolated):
    from ultimate_khorshid.interface.khorshid_gemini_live_runner import execute_tool
    probe = Probe()
    ex = ToolExecutor([probe])
    rt = SimpleNamespace(executor=ex)
    try:
        result = execute_tool(rt, "khorshid_execute_tool", {
            "tool_name": "file_write", "arguments_json": '{"path":"note.txt"}'})
        assert result["success"] and not result["approval_required"]
        assert probe.calls == [{"path": "note.txt"}]
    finally:
        ex.shutdown()


def test_remote_api_bind_is_rejected():
    from ultimate_khorshid.server.app import serve
    with pytest.raises(ValueError, match="loopback"):
        serve("0.0.0.0")


@pytest.mark.parametrize("approved", [False, True])
def test_real_file_write_through_agent_does_not_prompt(isolated, approved):
    from ultimate_khorshid.runtime import KhorshidRuntime
    cfg = KhorshidConfig()
    cfg.storage.db_path = str(isolated / "memory.db")
    path = isolated / "note.txt"
    callback = Mock(return_value=approved)
    rt = KhorshidRuntime(cfg, confirm_callback=callback)
    try:
        result = rt.ask(f"بنویس در {path}: سلام خورشید")
        assert path.exists()
        assert result.tool_results[0].success
        assert path.read_text() == "سلام خورشید"
        callback.assert_not_called()
    finally:
        rt.executor.shutdown()


def test_no_fallback_after_failed_mutation():
    tool = Probe()
    tool.execute = Mock(return_value=ToolResult(tool_name=tool.name, content="uncertain", success=False))
    fallback = Probe("other")
    ex = ToolExecutor([tool, fallback], confirm_callback=lambda _: True,
                      fallbacks={tool.name: fallback.name})
    try:
        assert not ex.execute(ToolCall(name=tool.name)).success
        assert not fallback.calls
    finally:
        ex.shutdown()


@pytest.mark.parametrize("body,length", [(b"[]", "2"), (b"{bad}", "5"), (b"", "-1"), (b"", "1000001")])
def test_api_rejects_invalid_bodies_without_reading_unbounded_data(body, length):
    import io
    from ultimate_khorshid.server.app import Handler
    fake = SimpleNamespace(headers={"Content-Length": length}, rfile=io.BytesIO(body))
    with pytest.raises(ValueError):
        Handler._body(fake)


@pytest.mark.parametrize("host,origin,content_type,allowed", [
    ("127.0.0.1:8899", None, "application/json", True),
    ("localhost:8899", "http://localhost:8899", "application/json", True),
    ("evil.example:8899", None, "application/json", False),
    ("127.0.0.1:8899", "https://evil.example", "application/json", False),
    ("127.0.0.1:8899", None, "text/plain", False),
])
def test_api_origin_boundary_without_opening_socket(host, origin, content_type, allowed):
    from ultimate_khorshid.server.app import Handler
    headers = {"Host": host, "Content-Type": content_type}
    if origin:
        headers["Origin"] = origin
    fake = SimpleNamespace(headers=headers, command="POST",
                           server=SimpleNamespace(server_port=8899), _send=Mock())
    assert Handler._local_request(fake) is allowed
    assert fake._send.called is (not allowed)
