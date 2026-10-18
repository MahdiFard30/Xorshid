import json
import os
from pathlib import Path
import urllib.error

import pytest

from ultimate_khorshid.cli import groq_setup as setup


@pytest.mark.parametrize('existing', ['', '[engine]\ndefault="gemini"\n',
    '# keep comment\n[engine]\ngroq_api_key="old"\n[engine.groq]\nmodel="selected-model"\napi_key="old"\n'])
def test_save_preserves_gemini_and_all_other_settings(tmp_path, existing):
    path = tmp_path/'config.toml'
    text = existing + '\n[engine.gemini]\napi_key="unchanged-gemini-key"\nmodel="selected-gemini"\n'
    path.write_text(text)
    setup.save_key(path, 'new-groq-key')
    data = setup.tomllib.loads(path.read_text())
    assert data['engine']['gemini'] == {'api_key':'unchanged-gemini-key','model':'selected-gemini'}
    assert data['engine']['groq']['api_key'] == 'new-groq-key'
    if 'groq_api_key' in data['engine']:
        assert data['engine']['groq_api_key'] == 'new-groq-key'
    if 'selected-model' in text:
        assert data['engine']['groq']['model'] == 'selected-model'
    assert path.stat().st_mode & 0o777 == 0o600


def test_bad_config_not_overwritten(tmp_path):
    path = tmp_path/'config.toml'
    path.write_text('invalid toml [')
    with pytest.raises(ValueError):
        setup.save_key(path, 'new-key')
    assert path.read_text() == 'invalid toml ['


@pytest.mark.parametrize('success', [True, False])
def test_interactive_entry_tests_before_save_and_never_prints_key(tmp_path, monkeypatch, capsys, success):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(setup.sys.stdin, 'isatty', lambda: True)
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    monkeypatch.setattr(setup.getpass, 'getpass', lambda prompt: 'hidden-test-key')
    target = tmp_path/'.ultimate-jarvis/config.toml'
    def check(key):
        assert key == 'hidden-test-key'
        assert not target.exists()
        if not success:
            raise urllib.error.HTTPError('https://api.groq.com', 401, 'no', {}, None)
    monkeypatch.setattr(setup, 'check_key', check)
    assert setup.main([]) == (0 if success else 1)
    assert target.exists() is success
    assert 'hidden-test-key' not in capsys.readouterr().out


def test_model_list_validation_uses_entered_key(monkeypatch):
    import io
    monkeypatch.setenv('GROQ_API_KEY', 'stale-key')
    sent = []
    def urlopen(request, **kwargs):
        sent.append(request)
        return io.BytesIO(json.dumps({'data':[{'id':'model'}]}).encode())
    monkeypatch.setattr(setup.urllib.request, 'urlopen', urlopen)
    setup.check_key('fresh-key')
    assert sent[0].get_header('Authorization') == 'Bearer fresh-key'
    assert sent[0].full_url == 'https://api.groq.com/openai/v1/models'
