"""سوئیت رگرسیون ایجنت — «این تسک‌ها باید همیشه پاس بشن».

آفلاین کامل (موتور mock). اجرا: khorshid eval  |  pytest evals/ -q
پروتکل WebArena/GAIA دستی در README بخش ارزیابی.
"""

import pytest

from ultimate_khorshid.core.config import KhorshidConfig
from ultimate_khorshid.runtime import KhorshidRuntime


@pytest.fixture()
def rt():
    return KhorshidRuntime(KhorshidConfig())


def test_calc(rt):
    r = rt.ask("حساب کن: 6*7", agent="computer")
    assert "42" in r.content


def test_file_write_read(rt, tmp_path):
    f = tmp_path / "note.txt"
    r = rt.ask(f"بنویس در {f}: سلام خورشید", agent="computer")
    assert r.tool_results and f.exists()
    r2 = rt.ask(f"بخوان فایل {f}", agent="computer")
    assert "سلام خورشید" in r2.content


def test_file_list(rt, tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("x")
    monkeypatch.chdir(tmp_path)
    r = rt.ask("لیست فایل‌ها را نشان بده", agent="computer")
    assert "a.txt" in r.content


def test_datetime_present(rt):
    r = rt.ask("ساعت چند است؟", agent="computer")
    assert any(y in r.content for y in ("1404", "1405", "2026", "2027", ":"))


def test_memory_semantic(tmp_path):
    from ultimate_khorshid.memory.store import SQLiteMemory
    m = SQLiteMemory(str(tmp_path / "mem.db"))
    m.add("رنگ موردعلاقه من آبی است")
    m.add("پایتخت فرانسه پاریس است")
    hits = m.search("پایتخت فرانسه کجاست؟", 3)
    assert hits and "پاریس" in hits[0].text


def test_todo_flow(rt):
    import re

    from ultimate_khorshid.core.types import ToolCall
    import json
    ex = rt.executor
    added = ex.execute(ToolCall(name="todo", arguments=json.dumps(
        {"action": "add", "text": "eval-task"})))
    assert added.success
    r = ex.execute(ToolCall(name="todo", arguments=json.dumps({"action": "list"})))
    assert "eval-task" in r.content
    nid = int(re.search(r"#(\d+)", added.content).group(1))
    ex.execute(ToolCall(name="todo", arguments=json.dumps(
        {"action": "done", "id": nid})))
    ex.execute(ToolCall(name="todo", arguments=json.dumps({"action": "clear"})))


def test_planner_two_steps(rt):
    r = rt.ask("حساب کن 3*3 و بعد حساب کن 4*4", agent="planner")
    assert "9" in r.content and "16" in r.content
    assert r.metadata.get("checkpoint_id")


def test_supervisor_delegates(rt):
    r = rt.ask("حساب کن 2*8 و بعد ساعت را بگو", agent="supervisor")
    assert "16" in r.content and "سوپروایزر" in r.content
    assert len(r.metadata.get("routes", [])) == 2


def test_strict_json_schema():
    from ultimate_khorshid.core.jsonx import parse_strict
    obj, errs = parse_strict('```json\n{"city": "تهران", "temp": 26}\n```',
                             {"type": "object", "required": ["city", "temp"],
                              "properties": {"city": {"type": "string"},
                                             "temp": {"type": "number"}}})
    assert errs == [] and obj["city"] == "تهران"


def test_sandbox_restricted_echo():
    from ultimate_khorshid.core.sandbox import run_python, run_shell
    rc, out, _, used = run_shell("echo hi", backend="off")
    assert rc == 0 and "hi" in out and used == "restricted"
    rc, out, _, _ = run_python("print(40+2)", backend="off")
    assert rc == 0 and "42" in out
