"""Application names must survive transcription and resolve to installed apps."""
import base64
from unittest.mock import Mock

import pytest

from ultimate_khorshid.tools import app_launcher
from ultimate_khorshid.voice import engines


@pytest.fixture
def discord(monkeypatch):
    app = {'id': 'discord_discord.desktop', 'name': 'Discord',
           'names': ['Discord'], 'path': '/apps/discord_discord.desktop'}
    monkeypatch.setattr(app_launcher, 'catalog', lambda: [app])
    monkeypatch.setattr(app_launcher.shutil, 'which', lambda name: '/usr/bin/gio' if name == 'gio' else None)
    return app


@pytest.mark.parametrize('name', ['دیسکورد', 'دیس کورد', 'دیسکرد', 'Discord', 'discord_discord'])
def test_spoken_discord_names_resolve_to_actual_snap_launcher(discord, name):
    assert app_launcher.resolve(name) == (['/usr/bin/gio', 'launch', discord['path']], None)


def test_flatpak_discord_and_ambiguous_installations(discord, monkeypatch):
    flatpak = dict(discord, id='com.discordapp.Discord.desktop', path='/apps/flatpak.desktop')
    monkeypatch.setattr(app_launcher, 'catalog', lambda: [flatpak])
    assert app_launcher.resolve('دیسکورد')[0][-1] == flatpak['path']
    monkeypatch.setattr(app_launcher, 'catalog', lambda: [discord, flatpak])
    with pytest.raises(ValueError, match='چند برنامه'):
        app_launcher.resolve('دیسکورد')


def test_snap_discord_opens_without_empty_uri_handler_arguments(discord, monkeypatch):
    discord.update(snap_instance='discord', snap_app='discord')
    monkeypatch.setattr(app_launcher.shutil, 'which',
                        lambda name: '/usr/bin/snap' if name == 'snap' else '/usr/bin/gio')
    assert app_launcher.resolve('دیسکورد') == (['/usr/bin/snap', 'run', 'discord'], None)


def test_vocabulary_uses_installed_apps_without_inventing_other_apps(discord):
    words = app_launcher.speech_vocabulary()
    assert {'دیسکورد', 'Discord'} <= set(words)
    assert 'Telegram' not in words and len(words) == len(set(words))


@pytest.mark.parametrize('recognized', ['دیسکورد رو باز کن.', 'This quarter was', 'من افسردگی دارم'])
def test_stt_sends_name_hints_but_does_not_rewrite_transcription(discord, monkeypatch, tmp_path, recognized):
    wav = tmp_path / 'speech.wav'
    wav.write_bytes(b'fake-audio')
    post = Mock(return_value={'candidates': [{'content': {'parts': [{'text': recognized}]}}]})
    monkeypatch.setattr(engines, '_post', post)
    assert engines.GeminiSTT().transcribe(str(wav)) == recognized
    payload = post.call_args.args[1]
    parts = payload['contents'][0]['parts']
    assert 'Discord' in parts[0]['text'] and 'دیسکورد' in parts[0]['text']
    assert base64.b64decode(parts[1]['inlineData']['data']) == b'fake-audio'
    assert payload['generationConfig']['temperature'] == 0


def test_missing_desktop_catalog_does_not_break_transcription_hints(monkeypatch):
    monkeypatch.setattr(app_launcher, 'speech_vocabulary', Mock(side_effect=OSError('no desktop')))
    assert 'Output ONLY the transcription.' in engines.transcription_instruction()


def test_spoken_discord_command_executes_launcher_without_another_model_guess(discord, monkeypatch):
    import json
    from ultimate_khorshid.agents.base import AgentContext
    from ultimate_khorshid.agents.computer import ComputerAgent
    from ultimate_khorshid.core.types import ToolResult
    executor = Mock()
    executor.execute.return_value = ToolResult(tool_name='open_app', content='requested')
    context = AgentContext()
    context.conversation.add('user', 'دیسکورد رو باز کن.')
    assert ComputerAgent(None, 'mock', executor=executor).run(context).content == 'requested'
    call = executor.execute.call_args.args[0]
    assert call.name == 'open_app' and json.loads(call.arguments) == {'target': 'دیسکورد'}
    assert app_launcher.resolve(json.loads(call.arguments)['target'])[0][-1] == discord['path']
