"""Doctor diagnostics: no external API calls or real credentials."""
from argparse import Namespace
import errno
import hashlib
import json
import sqlite3
from types import SimpleNamespace
import urllib.error

import pytest

from ultimate_khorshid.cli import diagnostics, main
from ultimate_khorshid.core.config import KhorshidConfig, load_config


@pytest.fixture(autouse=True)
def isolated_secrets(monkeypatch,tmp_path):
    from ultimate_khorshid.core import vault
    from ultimate_khorshid.engine import groq
    monkeypatch.setattr(vault,'get_secret',lambda *a,**k:'')
    monkeypatch.setattr(groq,'KEY_FILE',tmp_path/'missing.key')
    for key in ('GEMINI_API_KEY','GOOGLE_API_KEY','OPENAI_API_KEY','GROQ_API_KEY'):
        monkeypatch.delenv(key,raising=False)


def test_credentials_use_nested_explicit_config_without_env(tmp_path):
    path=tmp_path/'config.toml'
    path.write_text('[engine.gemini]\napi_key="gemini-test-secret"\n[engine.groq]\napi_key="groq-test-secret"\n[engine.openai]\napi_key="openai-test-secret"\n')
    result=diagnostics.credentials(load_config(path))
    assert result=={'openai':True,'gemini':True,'groq':True}
    assert 'secret' not in json.dumps(result)


def test_credentials_use_runtime_vault(monkeypatch):
    from ultimate_khorshid.core import vault
    monkeypatch.setattr(vault,'get_secret',lambda name,*a:'secret' if name=='GOOGLE_API_KEY' else '')
    assert diagnostics.credentials(KhorshidConfig())=={'openai':False,'gemini':True,'groq':False}


def test_groq_legacy_key_file_is_recognized(tmp_path,monkeypatch):
    from ultimate_khorshid.engine import groq
    key=tmp_path/'legacy.key';key.write_text('groq-local-secret')
    monkeypatch.setattr(groq,'KEY_FILE',key)
    assert diagnostics.credentials(KhorshidConfig())['groq']


def test_ollama_uses_configured_host(monkeypatch):
    from ultimate_khorshid.engine import ollama
    seen=[]
    def health(self):
        seen.append(self.host)
        return {'ok':True,'models':['local-model']}
    monkeypatch.setattr(ollama.OllamaEngine,'health',health)
    cfg=KhorshidConfig();cfg.engine.ollama_host='http://127.0.0.1:12345'
    assert 'local-model' in diagnostics.ollama_status(cfg)
    assert seen==['http://127.0.0.1:12345']


def test_network_permission_error_not_reported_as_disconnected(monkeypatch):
    from ultimate_khorshid.engine import ollama
    def blocked(*a,**k):raise urllib.error.URLError(PermissionError(errno.EPERM,'blocked'))
    monkeypatch.setattr(ollama.urllib.request,'urlopen',blocked)
    state=diagnostics.ollama_status(KhorshidConfig())
    assert 'قطع‌بودن سرویس تأیید نشد' in state


def test_connection_failure_does_not_expose_url_credentials(monkeypatch):
    from ultimate_khorshid.engine import ollama
    monkeypatch.setattr(ollama.OllamaEngine,'health',lambda self:{'ok':False,'error':'secret-url-token'})
    assert 'secret-url-token' not in diagnostics.ollama_status(KhorshidConfig())


def test_memory_uses_requested_database_without_modification(tmp_path):
    file=tmp_path/'custom?#.sqlite'
    with sqlite3.connect(file) as con:
        con.execute('CREATE TABLE memories(id INTEGER,text TEXT)')
        con.executemany('INSERT INTO memories VALUES (?,?)',[(1,'private note'),(2,'another note')])
    before=hashlib.sha256(file.read_bytes()).hexdigest()
    result=diagnostics.memory_status(file)
    assert '2 رکورد' in result and 'private note' not in result
    assert hashlib.sha256(file.read_bytes()).hexdigest()==before


def test_missing_memory_is_not_created_or_marked_broken(tmp_path):
    file=tmp_path/'not-created/memory.sqlite'
    assert 'هنوز ایجاد نشده' in diagnostics.memory_status(file)
    assert not file.parent.exists()


def test_existing_database_without_manual_table_is_not_broken(tmp_path):
    file=tmp_path/'memory.sqlite'
    with sqlite3.connect(file) as con:con.execute('CREATE TABLE messages(id INTEGER)')
    assert 'جدول حافظهٔ دستی هنوز' in diagnostics.memory_status(file)


def test_live_env_file_and_session_only_state(tmp_path):
    pytest.importorskip('dotenv')
    assert diagnostics.live_credentials(tmp_path) is False
    (tmp_path/'.env').write_text('GEMINI_API_KEY="live-test-secret"\n')
    assert diagnostics.live_credentials(tmp_path) is True


def test_doctor_honors_config_and_never_prints_credentials(tmp_path,monkeypatch,capsys):
    path=tmp_path/'config.toml'
    path.write_text('[engine.gemini]\napi_key="hidden-gemini"\n[engine.groq]\napi_key="hidden-groq"\n[engine.openai]\napi_key="hidden-openai"\n[storage]\ndb_path="'+str(tmp_path/'missing.sqlite')+'"\n')
    monkeypatch.setattr(diagnostics,'ollama_status',lambda cfg:'offline fake check')
    monkeypatch.setattr(diagnostics,'live_credentials',lambda root:False)
    assert main.cmd_doctor(Namespace(config=str(path)))==0
    output=capsys.readouterr().out
    for provider in ('gemini','groq','openai'):
        assert provider+'_api_key: ✅ تنظیم شده' in output
        assert 'hidden-'+provider not in output
    assert 'اتصال آزمون نشد' in output and 'هنوز ایجاد نشده' in output
    assert not (tmp_path/'missing.sqlite').exists()
