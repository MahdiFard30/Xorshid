"""Smoke tests — بدون نیاز به اینترنت/API."""



def _rt():
    from ultimate_khorshid.core.config import KhorshidConfig
    from ultimate_khorshid.runtime import KhorshidRuntime
    return KhorshidRuntime(KhorshidConfig())


def test_registries():
    from ultimate_khorshid.runtime import list_agents, list_tools
    assert len(list_agents()) >= 8
    assert len(list_tools()) >= 18
    assert "computer" in list_agents()
    assert "shell_exec" in list_tools()


def test_calculator():
    from ultimate_khorshid.core.types import ToolCall
    rt = _rt()
    r = rt.executor.execute(ToolCall(name="calculator", arguments='{"expression": "2**10"}'))
    assert r.success and "1024" in r.content


def test_files(tmp_path):
    from ultimate_khorshid.core.types import ToolCall
    import json
    rt = _rt()
    fp = str(tmp_path / "a.txt")
    r = rt.executor.execute(ToolCall(name="file_write", arguments=json.dumps({"path": fp, "content": "سلام"})))
    assert r.success
    r = rt.executor.execute(ToolCall(name="file_read", arguments=json.dumps({"path": fp})))
    assert r.success and "سلام" in r.content


def test_mock_chat():
    rt = _rt()
    assert "خورشید" in rt.ask("سلام", agent="simple").content


def test_mock_tool_use():
    rt = _rt()
    r = rt.ask("حساب کن: 7*6")
    assert "42" in r.content


def test_memory(tmp_path):
    from ultimate_khorshid.memory.store import SQLiteMemory
    m = SQLiteMemory(db_path=str(tmp_path / "m.db"))
    m.add("تست فارسی حافظه")
    assert m.search("حافظه")


def test_all_agents_instantiate():
    from ultimate_khorshid.runtime import list_agents
    rt = _rt()
    for a in list_agents():
        rt.build_agent(a)
