"""Offline integration tests; run with python -m unittest discover -s tests -p test_automatic_memory.py."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ultimate_khorshid.core.config import KhorshidConfig
from ultimate_khorshid.runtime import KhorshidRuntime
from ultimate_khorshid.memory.automatic import AutomaticMemory, scoped_path, extract_facts


class AutomaticMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = patch.object(Path, "home", return_value=self.root)
        self.home.start()
        original = os.path.expanduser
        self.expand = patch("os.path.expanduser", side_effect=lambda p: str(self.root / str(p)[2:]) if str(p).startswith("~/") else original(p))
        self.expand.start()
        self.settings = patch("ultimate_khorshid.core.settings.apply_to_config", side_effect=lambda c: c)
        self.settings.start()
        self.cfg = KhorshidConfig()
        self.cfg.storage.db_path = str(self.root / "custom.db")
        self.runtimes = []

    def tearDown(self):
        for rt in self.runtimes:
            rt.executor.shutdown()
        self.settings.stop()
        self.expand.stop()
        self.home.stop()
        self.tmp.cleanup()

    def runtime(self):
        rt = KhorshidRuntime(self.cfg)
        self.runtimes.append(rt)
        return rt

    def auto(self, scope="local"):
        return AutomaticMemory(scoped_path(self.cfg.storage.db_path, scope))

    def test_persistence_and_mock_recall_after_restart(self):
        self.runtime().ask("رنگ موردعلاقه من آبی است")
        result = self.runtime().ask("رنگ موردعلاقه من چیه؟")
        self.assertIn("آبی", result.content)
        self.assertEqual(self.auto().status()["turns"], 2)
        self.assertEqual(self.auto().status()["facts"], 1)

    def test_corrected_fact_replaces_old_value(self):
        self.runtime().ask("رنگ موردعلاقه من آبی است")
        self.runtime().ask("رنگ موردعلاقه من قرمز است")
        self.assertEqual(self.auto().facts(), ["رنگ موردعلاقه کاربر: قرمز"])

    def test_questions_and_quoted_examples_are_not_facts(self):
        self.assertEqual(list(extract_facts("اسم من چیه؟")), [])
        self.assertEqual(list(extract_facts('مثلاً اسم من علی است')), [])

    def test_actual_model_receives_previous_turn_and_experience(self):
        self.runtime().ask("حساب کن: 6*7")
        rt = self.runtime()
        captured = []
        def generate(messages, *a, **kw):
            captured.extend(messages)
            return {"content": "ok"}
        rt.engine.generate = generate
        rt.ask("حساب کن: 6*7", agent="simple")
        text = json.dumps(captured, ensure_ascii=False)
        self.assertIn("calculator", text)
        self.assertIn("tools_ok", text)
        self.assertIn("42", text)
        self.assertGreaterEqual(sum(m["role"] == "user" for m in captured), 2)

    def test_disabled_memory_writes_nothing(self):
        self.runtime().ask("اسم من علی است", memory=False)
        self.assertFalse(Path(self.cfg.storage.db_path).exists())

    def test_auto_write_can_be_disabled(self):
        self.cfg.agent.auto_memory = False
        self.runtime().ask("اسم من علی است")
        self.assertEqual(self.auto().status()["turns"], 0)

    def test_explicit_tools_use_configured_database(self):
        self.runtime().ask("به خاطر بسپار: پروژه من خورشید است")
        self.assertTrue(self.auto().store.search("خورشید"))
        self.assertFalse((self.root / ".ultimate-jarvis/memory.db").exists())

    def test_remote_scope_cannot_read_local_or_other_users(self):
        self.runtime().ask("به خاطر بسپار: local-private-note")
        self.runtime().ask("اسم من سارا است", memory_scope="telegram:1", session_id="1")
        self.assertEqual(self.auto("telegram:2").facts(), [])
        self.assertFalse(self.auto("telegram:1").store.search("local-private-note"))
        self.assertEqual(self.auto().facts(), [])

    def test_recent_turns_are_session_scoped(self):
        self.runtime().ask("سلام", session_id="one")
        self.assertEqual(self.auto().recent("two"), [])
        self.assertEqual(len(self.auto().recent("one")), 2)

    def test_error_is_not_remembered_as_success(self):
        rt = self.runtime()
        rt.engine.generate = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("offline"))
        with self.assertRaises(RuntimeError):
            rt.ask("درخواست آزمایشی", agent="simple")
        self.assertEqual(self.auto().recall("درخواست آزمایشی")[0]["outcome"], "error")

    def test_redaction_and_forget(self):
        self.runtime().ask("password: supersecretvalue", agent="simple")
        self.assertNotIn("supersecretvalue", json.dumps(self.auto().recent("local")))
        self.auto().clear(everything=True)
        self.assertEqual(self.auto().status()["turns"], 0)
        self.assertEqual(self.auto().facts(), [])

    def test_old_memory_survives_initialization(self):
        from ultimate_khorshid.memory.store import SQLiteMemory
        mem = SQLiteMemory(self.cfg.storage.db_path)
        mem.add("old-note")
        self.runtime().ask("سلام")
        self.assertTrue(self.auto().store.search("old-note"))


if __name__ == "__main__":
    unittest.main()
