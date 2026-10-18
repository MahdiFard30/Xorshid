"""Persistent browser lifecycle and scoped YouTube controls, without network."""
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock
import sys

import pytest

from ultimate_khorshid.tools import browser
from ultimate_khorshid.agents.computer import direct_media_request


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    monkeypatch.setattr(browser, '_state', dict.fromkeys(browser._state))


def test_persistent_chromium_profile_and_closed_tab_reuse(monkeypatch, tmp_path):
    page=Mock(); page.is_closed.return_value=False
    context=Mock(pages=[page]); context.browser.is_connected.return_value=True
    chromium=Mock(); chromium.launch_persistent_context.return_value=context
    pw=Mock(chromium=chromium)
    manager=Mock(); manager.start.return_value=pw
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(sync_playwright=lambda:manager))
    monkeypatch.setattr(browser,'_chrome_executable',lambda:None)
    monkeypatch.setattr(browser,'_PROFILE_ROOT',tmp_path/'profile')
    assert browser._page() is page
    assert browser._page() is page
    args,kwargs=chromium.launch_persistent_context.call_args
    assert args==(str(tmp_path/'profile/chromium'),)
    assert 'channel' not in kwargs
    assert (tmp_path/'profile').stat().st_mode & 0o777==0o700
    page.is_closed.return_value=True
    assert browser._page() is context.new_page.return_value
    chromium.launch_persistent_context.assert_called_once()
    browser.close_browser()
    context.close.assert_called_once()
    pw.stop.assert_called_once()
    assert not any(browser._state.values())
    assert (tmp_path/'profile/chromium').is_dir()  # closing never deletes consent


def test_installed_chrome_uses_normal_startup_with_local_control(monkeypatch,tmp_path):
    listener=MagicMock()
    listener.__enter__.return_value.getsockname.return_value=('127.0.0.1',12345)
    monkeypatch.setattr(browser.socket,'socket',lambda:listener)
    process=Mock();process.poll.return_value=None
    launch=Mock(return_value=process)
    monkeypatch.setattr(browser.subprocess,'Popen',launch)
    pw=Mock();connected=Mock(contexts=[Mock()])
    pw.chromium.connect_over_cdp.return_value=connected
    result=browser._launch_chrome(pw,'/usr/bin/google-chrome',tmp_path,False)
    assert result==(connected,connected.contexts[0],process)
    args=launch.call_args.args[0]
    assert f'--user-data-dir={tmp_path}' in args
    assert '--remote-debugging-address=127.0.0.1' in args
    assert '--enable-automation' not in args and '--no-sandbox' not in args
    pw.chromium.connect_over_cdp.assert_called_once_with('http://127.0.0.1:12345',timeout=1000)


def test_closing_owned_chrome_sends_browser_close_and_reaps_only_its_process():
    owned=Mock();context=Mock();connected=Mock()
    browser._state.update(process=owned,context=context,browser=connected,pw=Mock())
    browser.close_browser()
    connected.new_browser_cdp_session.return_value.send.assert_called_once_with('Browser.close')
    owned.wait.assert_called_once_with(timeout=5)
    context.close.assert_not_called()
    assert not any(browser._state.values())


def test_no_active_video_control_never_launches_browser(monkeypatch):
    launch=Mock(side_effect=AssertionError('must not launch'))
    monkeypatch.setattr(browser,'_page',launch)
    for action in ('status','pause','resume','close','next'):
        assert not browser.YouTubeControlTool().execute(action=action).success
    launch.assert_not_called()


@pytest.fixture
def media_page():
    page=Mock(url='https://www.youtube.com/watch?v=test')
    page.is_closed.return_value=False
    page.evaluate.return_value={'playing':True,'advertisement':False,'player_error':'','media_error':None}
    browser._state.update(page=page,media_page=page)
    return page


def test_close_only_video_tab_not_browser_or_other_tabs(media_page):
    context=Mock(); browser._state['context']=context
    assert browser.YouTubeControlTool().execute(action='close').success
    media_page.close.assert_called_once()
    context.close.assert_not_called()
    assert browser._state['media_page'] is None


@pytest.mark.parametrize('action',['pause','resume','status'])
def test_control_existing_video(media_page,action):
    assert browser.YouTubeControlTool().execute(action=action).success
    if action!='status':
        media_page.locator.return_value.first.evaluate.assert_called_once()


def test_player_error_is_reported_not_playing(media_page):
    media_page.evaluate.return_value.update(player_error='Something went wrong')
    result=browser.YouTubeControlTool().execute(action='status')
    assert not result.success and not result.metadata['playing']
    assert 'Something went wrong' in result.content


def test_next_waits_for_actual_navigation(media_page):
    result=browser.YouTubeControlTool().execute(action='next')
    assert result.success
    media_page.locator.assert_called_with('.ytp-next-button')
    media_page.wait_for_function.assert_called_once()


def test_controls_do_not_touch_unrelated_site(media_page):
    media_page.url='https://example.com/watch?v=test'
    assert not browser.YouTubeControlTool().execute(action='close').success
    media_page.close.assert_not_called()


def test_unavailable_next_video_is_not_claimed_as_opened(media_page):
    media_page.locator.return_value.first.count.return_value=0
    result=browser.YouTubeControlTool().execute(action='next')
    assert not result.success
    media_page.wait_for_function.assert_not_called()


@pytest.mark.parametrize(('text','tool','params'),[
    ('یوتیوب رو باز کن','browser_open',{'url':'https://www.youtube.com/'}),
    ('ویدیو رو ببند','youtube_control',{'action':'close'}),
    ('بزن بعدی','youtube_control',{'action':'next'}),
    ('صدا رو کم کن','youtube_control',{'action':'volume_down'}),
    ('صدا رو قطع کن','youtube_control',{'action':'mute'}),
])
def test_computer_uses_controlled_browser_for_shortcuts(text,tool,params):
    import json
    from ultimate_khorshid.agents.base import AgentContext
    from ultimate_khorshid.agents.computer import ComputerAgent
    from ultimate_khorshid.core.types import ToolResult
    executor=Mock()
    executor.execute.return_value=ToolResult(tool_name=tool,content='done')
    ctx=AgentContext();ctx.conversation.add('user',text)
    agent=ComputerAgent(None,'mock',executor=executor)
    result=agent.run(ctx)
    call=executor.execute.call_args.args[0]
    assert call.name==tool and json.loads(call.arguments)==params
    assert result.content=='done'


@pytest.mark.parametrize('action', ['volume_down','volume_up','mute','unmute','set_volume'])
def test_video_volume_controls_pass_validated_arguments_and_report_state(media_page, action):
    media_page.evaluate.side_effect = [True, {'volume':35,'muted':action=='mute','playing':True}]
    params={'action':action}
    if action=='set_volume': params['volume']=35
    result=browser.YouTubeControlTool().execute(**params)
    assert result.success
    assert result.metadata['volume']==35
    assert result.metadata['muted']==(action=='mute')
    args=media_page.evaluate.call_args_list[0].args[1]
    assert args=={'action':action,'volume':params.get('volume'),'step':15}


@pytest.mark.parametrize('params', [
    {'action':'set_volume'}, {'action':'set_volume','volume':101},
    {'action':'set_volume','volume':True}, {'action':'set_volume','volume':'50'},
    {'action':'volume_up','step':0}, {'action':'volume_down','step':False},
])
def test_invalid_volume_does_not_touch_browser(media_page, params):
    assert not browser.YouTubeControlTool().execute(**params).success
    media_page.evaluate.assert_not_called()


def test_missing_video_does_not_claim_volume_changed(media_page):
    media_page.evaluate.return_value=False
    assert not browser.YouTubeControlTool().execute(action='mute').success


@pytest.mark.parametrize('text', ['صدات رو کم کن','صدا رو قطع نکن','صدا رو کم کن و بزن بعدی'])
def test_ambiguous_or_negative_sound_requests_use_agent_context(text):
    assert direct_media_request(text) is None


@pytest.mark.parametrize(('text','action'),[
    ('ویدیو رو ببند','close'),('بزن بعدی','next'),('پخش رو نگه دار','pause'),
    ('ویدیو رو ادامه بده','resume'),('قسمت بعدی رو پخش کن',None),
    ('ویدیو رو نبند',None),('اگر ویدیو رو ببند چی میشه؟',None),('فایل بعدی رو ببند',None)])
def test_media_shortcuts_are_single_explicit_actions(text,action):
    assert direct_media_request(text)==action


def test_consent_only_on_youtube_and_rejects_optional_cookies(media_page):
    browser._youtube_consent(media_page)
    media_page.get_by_role.return_value.first.click.assert_called_once()
    pattern=media_page.get_by_role.call_args.kwargs['name']
    assert pattern.fullmatch('Reject all') and pattern.fullmatch('Avvisa alla')
    assert not pattern.fullmatch('Accept all')
    media_page.reset_mock()
    media_page.url='https://example.com'
    browser._youtube_consent(media_page)
    media_page.get_by_role.assert_not_called()
