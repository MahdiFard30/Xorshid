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
    assert engines.GeminiSTT('gemini-3.5-flash-lite').transcribe(str(wav)) == recognized
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


@pytest.mark.parametrize('text',[
    'پنجره جدید از حافظه برام باز کن',
    'یه پنجره جدید باز کن',
    'فایل گزارش رو باز کن',
    'پوشه دانلود رو باز کن',
    'یه قطعه خیلی ناب از حافظ برام بخون',
    'شعر حافظ رو باز کن',
    'open a new window',
    'open the file',
])
def test_contextual_requests_do_not_execute_the_app_shortcut(text):
    from ultimate_khorshid.agents.computer import direct_app_request
    assert direct_app_request(text) is None


@pytest.mark.parametrize('text',['دیسکورد رو برام باز کن','دیسکورد برای من باز کن','دیسکورد رو باز کن'])
def test_app_shortcuts_remove_request_fillers(text):
    from ultimate_khorshid.agents.computer import direct_app_request
    assert direct_app_request(text)=='دیسکورد'


def test_stt_quality_model_is_independent_and_configurable(monkeypatch):
    monkeypatch.delenv('KHORSHID_STT_MODEL',raising=False)
    assert engines.GeminiSTT().model=='gemini-3.5-transcribe'
    monkeypatch.setenv('KHORSHID_STT_MODEL','gemini-3.5-flash-lite')
    assert engines.GeminiSTT().model=='gemini-3.5-flash-lite'
    assert engines.GeminiSTT('chosen-model').model=='chosen-model'


def test_transcription_prompt_does_not_bias_all_speech_toward_computer_commands(discord):
    hint=engines.transcription_instruction()
    assert 'poetry' in hint and 'Do not assume every utterance is an application command' in hint
    assert 'only when supported' in hint


def test_dedicated_recognizer_reads_only_completed_model_text(discord,monkeypatch,tmp_path):
    wav=tmp_path/'voice.wav';wav.write_bytes(b'fake-audio')
    post=Mock(return_value={'status':'completed','steps':[
        {'type':'thought','content':[{'type':'text','text':'do not use this'}]},
        {'type':'user_input','content':[{'type':'text','text':'input text'}]},
        {'type':'model_output','content':[{'type':'text','text':'یه قطعه از حافظ بخون.'}]}]})
    monkeypatch.setattr(engines,'_post_transcription',post)
    assert engines.GeminiSTT('gemini-3.5-transcribe').transcribe(str(wav))=='یه قطعه از حافظ بخون.'
    payload=post.call_args.args[0]
    assert payload['store'] is False
    assert payload['generation_config']['transcription_config']['mode']=={'type':'verbatim'}
    assert payload['generation_config']['transcription_config']['language_codes']==['fa-IR']
    assert 'Discord' in payload['generation_config']['transcription_config']['custom_vocabulary']
    assert base64.b64decode(payload['input'][0]['data'])==b'fake-audio'


@pytest.mark.parametrize('response',[{'status':'in_progress'}, {'status':'completed','steps':[]}])
def test_missing_or_partial_dedicated_transcript_uses_working_gemini_fallback(monkeypatch,tmp_path,response):
    wav=tmp_path/'voice.wav';wav.write_bytes(b'fake-audio')
    monkeypatch.delenv('KHORSHID_STT_MODEL',raising=False)
    monkeypatch.setattr(engines,'api_key',lambda:'fake')
    monkeypatch.setattr(engines,'_post_transcription',lambda payload:response)
    legacy=Mock(return_value={'candidates':[{'content':{'parts':[{'text':'حافظ بخون'}]}}]})
    monkeypatch.setattr(engines,'_post',legacy)
    assert engines.transcribe_file(str(wav),engine='gemini')=='حافظ بخون'
    assert legacy.call_args.args[0]=='gemini-3.5-flash-lite'
