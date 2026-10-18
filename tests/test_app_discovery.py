"""App discovery must work for applications absent from the built-in aliases."""
import json
from unittest.mock import Mock

import pytest

from ultimate_khorshid.tools import app_launcher as apps
from ultimate_khorshid.tools.desktop import ListAppsTool, OpenAppTool


def app(name='PhotonBrush Studio', ident='org.example.PhotonBrush.desktop', **extra):
    return dict(id=ident, name=name, names=[name], path='/apps/'+ident, **extra)


@pytest.fixture
def installed(monkeypatch):
    records = [app(), app('Audio Forge', 'audio-forge.desktop')]
    monkeypatch.setattr(apps, 'catalog', lambda: records)
    monkeypatch.setattr(apps.shutil, 'which', lambda command: '/usr/bin/'+command)
    return records


def test_new_app_name_and_short_name_work_without_alias(installed):
    assert 'photonbrush' not in apps.ALIASES
    for name in ('PhotonBrush', 'PhotonBrush Studio', installed[0]['id']):
        assert apps.resolve(name)[0] == ['/usr/bin/gio', 'launch', installed[0]['path']]


def test_new_localized_name_comes_from_desktop_metadata(installed):
    installed[0]['names'].append('فوتون براش')
    assert apps.resolve('فوتون براش')[0][-1] == installed[0]['path']


def test_new_desktop_entries_are_discovered_with_localized_search_metadata(tmp_path, monkeypatch):
    user = tmp_path/'user'
    system = tmp_path/'system'
    monkeypatch.setenv('XDG_DATA_HOME', str(user))
    monkeypatch.setenv('XDG_DATA_DIRS', str(system))
    directory = user/'applications'
    directory.mkdir(parents=True)
    entry = directory/'org.example.UniquePaint.desktop'
    entry.write_text('[Desktop Entry]\nType=Application\nName=UniquePaint Studio\n'
        'Name[fa]=نگارخانه آزمایشی\nGenericName=Painting Tool\nKeywords=uniquepainting;\n'
        'Exec=/usr/bin/true\n', encoding='utf-8')
    found = next(a for a in apps.catalog() if a['id'] == entry.name)
    assert 'نگارخانه آزمایشی' in found['speech_names']
    assert 'Painting Tool' in found['generic_names']
    assert apps.find_apps('UniquePaint')[0]['id'] == entry.name
    assert apps.search_apps('uniquepainting')['apps'][0]['id'] == entry.name
    assert 'UniquePaint Studio' in apps.speech_vocabulary()


def test_partial_match_never_opens_an_arbitrary_similar_app(installed):
    installed.append(app('PhotonBrush Viewer', 'viewer.desktop'))
    with pytest.raises(apps.AppAmbiguousError):
        apps.resolve('PhotonBrush')
    with pytest.raises(apps.AppNotFoundError):
        apps.resolve('PhotnBrsh')


def test_display_name_match_takes_priority_over_unrelated_launcher_id(installed):
    installed.append(app('Unrelated Web Shortcut', 'photonbrush-web-shortcut.desktop'))
    assert apps.resolve('PhotonBrush')[0][-1] == installed[0]['path']


def test_catalog_and_speech_hints_pick_up_new_installations(installed):
    assert 'PhotonBrush Studio' in apps.speech_vocabulary()
    assert 'Nebula Notes' not in apps.speech_vocabulary()
    installed.append(app('Nebula Notes', 'notes.desktop'))
    assert 'Nebula Notes' in apps.speech_vocabulary()
    assert apps.resolve('Nebula')[0][-1] == '/apps/notes.desktop'


def test_generic_keywords_are_searchable_but_not_auto_launch_targets(installed):
    installed[0].update(keywords=['painting'], generic_names=['Image Editor'])
    assert apps.search_apps('painting')['apps'][0]['id'] == installed[0]['id']
    with pytest.raises(apps.AppNotFoundError):
        apps.resolve('painting')


def test_every_installed_app_can_be_seen_in_paginated_tool_output(monkeypatch):
    records = [app(f'Program {index:03}', f'p{index}.desktop') for index in range(135)]
    monkeypatch.setattr(apps, 'catalog', lambda: records)
    offset, seen = 0, []
    while offset is not None:
        result = ListAppsTool().execute(offset=offset)
        assert result.success and len(result.metadata['apps']) <= 20
        assert 'next_offset=' in result.content[:100]
        assert len(result.content) < 4000
        seen.extend(a['id'] for a in result.metadata['apps'])
        offset = result.metadata['next_offset']
    assert len(seen) == 135 and len(set(seen)) == 135


@pytest.mark.parametrize(('instance', 'command', 'expected'), [
    ('future-app', 'future-app', 'future-app'),
    ('future-app', 'viewer', 'future-app.viewer'),
    ('future-app_work', 'future-app', 'future-app_work'),
])
def test_any_snap_application_uses_its_installed_metadata(installed, instance, command, expected):
    installed[0].update(snap_instance=instance, snap_app=command)
    assert apps.resolve('PhotonBrush')[0] == ['/usr/bin/snap', 'run', expected]


def test_unmatched_app_returns_machine_readable_discovery_result(installed):
    result = OpenAppTool().execute(target='فوتونبراش')
    assert not result.success and result.metadata['app_error'] == 'app_not_found'


def test_unknown_persian_name_searches_real_catalog_then_opens_canonical_id(installed, monkeypatch):
    from ultimate_khorshid.agents.computer import ComputerAgent
    from ultimate_khorshid.agents.base import AgentContext
    from ultimate_khorshid.tools.base import ToolExecutor
    launched = []
    def launch(target):
        argv, _ = apps.resolve(target)
        launched.append(argv)
        return 'launch requested'
    monkeypatch.setattr(apps, 'launch', launch)
    class Engine:
        engine_id = 'mock'
        def __init__(self):
            self.calls = 0
        def generate(self, messages, model, **kwargs):
            self.calls += 1
            if self.calls == 1:
                system = next(m['content'] for m in messages if m['role'] == 'system')
                assert installed[0]['id'] in system and 'فوتونبراش' in system
                return {'content':'', 'tool_calls':[{'name':'open_app', 'id':'choose',
                    'arguments':json.dumps({'target':installed[0]['id']})}]}
            return {'content':'launch requested', 'tool_calls':[]}
    engine = Engine()
    executor = ToolExecutor([OpenAppTool(), ListAppsTool()])
    try:
        context = AgentContext()
        context.conversation.add('user', 'فوتونبراش رو باز کن')
        result = ComputerAgent(engine, 'mock', executor=executor).run(context)
        assert [r.tool_name for r in result.tool_results] == ['open_app','list_apps','open_app']
        assert launched == [['/usr/bin/gio','launch', installed[0]['path']]]
        assert result.tool_results[-1].success
    finally:
        executor.shutdown()


def test_launch_failure_is_not_misreported_as_missing_application(installed, monkeypatch):
    from ultimate_khorshid.agents import computer
    from ultimate_khorshid.agents.base import AgentContext
    from ultimate_khorshid.core.types import ToolResult
    executor = Mock()
    executor.execute.return_value = ToolResult(tool_name='open_app', success=False,
        content='launch failed', metadata={'app_error':'launch_failed'})
    worker = Mock(side_effect=AssertionError('must report actual startup failure'))
    monkeypatch.setattr(computer, 'OrchestratorAgent', worker)
    context = AgentContext(); context.conversation.add('user', 'PhotonBrush رو باز کن')
    result = computer.ComputerAgent(None, 'mock', executor=executor).run(context)
    assert result.content == 'launch failed'
    executor.execute.assert_called_once()
