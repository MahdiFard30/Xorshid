"""Media routing and playback-state tests; no external site or real browser."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ultimate_khorshid.agents.computer import direct_app_request, direct_site_request
from ultimate_khorshid.tools import browser
from ultimate_khorshid.tools.base import ToolExecutor
from ultimate_khorshid.core.types import ToolCall


@pytest.mark.parametrize('text',[
    'تو یوتیوب قسمت اولو باز کن',
    'پایتخت هفت، قسمت هفتم توی یوتیوب برام باز کن',
    'یوتوب پایتخت قسمت هفتم رو باز کن',
    'فایل پی دی اف رو باز کن',
    'open youtube episode 7',
])
def test_media_requests_never_route_to_an_app_name(text):
    assert direct_app_request(text) is None


def test_actual_app_and_simple_site_shortcuts_still_work():
    assert direct_app_request('فایرفاکس رو باز کن')=='فایرفاکس'
    assert direct_site_request('یوتیوب رو باز کن')=='https://www.youtube.com/'
    assert direct_site_request('پایتخت هفت قسمت هفتم تو یوتیوب باز کن') is None


def video(title,ident='abc'):
    return {'title':title,'url':'https://www.youtube.com/watch?v='+ident,'index':0}


def test_matching_episode_and_season_not_first_wrong_result():
    wrong=video('پایتخت ۷ قسمت اول','wrong')
    earlier_season=video('پایتخت ۶ قسمت هفتم','old')
    right=video('پایتخت ۷ قسمت ۷ کامل','right')
    assert browser.choose_youtube_result('پایتخت هفت قسمت هفتم',[wrong,earlier_season,right])==right


@pytest.mark.parametrize('title',['پایتخت۷ قسمت۷','Paytakht 7 Episode 07','پایتخت هفت قسمت هفتم'])
def test_equivalent_title_numbers_and_scripts(title):
    assert browser.choose_youtube_result('پایتخت ۷ قسمت ۷',[video(title)])


@pytest.mark.parametrize('url',['https://example.com/watch?v=abc','https://www.youtube.com/shorts/abc',
                               'https://youtube.com.evil.test/watch?v=abc','javascript:alert(1)'])
def test_non_video_or_foreign_links_not_selected(url):
    assert browser.choose_youtube_result('پایتخت ۷ قسمت ۷',[dict(video('پایتخت ۷ قسمت ۷'),url=url)]) is None


def test_unlabelled_or_different_episode_is_not_guessed():
    assert browser.choose_youtube_result('پایتخت ۷ قسمت ۷',[video('پایتخت ۷ پشت صحنه')]) is None


class Empty:
    @property
    def first(self):return self
    def count(self):return 0
    def is_visible(self):return False


class Video:
    @property
    def first(self):return self
    def wait_for(self,**kwargs):pass
    def evaluate(self,script):return True


class Link:
    def __init__(self,page,index):self.page,self.index=page,index
    def get_attribute(self,name):
        return self.page.results[self.index]['title' if name=='title' else 'url']
    def inner_text(self):return self.get_attribute('title')
    def click(self,**kwargs):self.page.clicked.append(self.index)
    def wait_for(self,**kwargs):pass


class Links:
    def __init__(self,page):self.page=page
    @property
    def first(self):return Link(self.page,0)
    def count(self):return len(self.page.results)
    def nth(self,index):return Link(self.page,index)


class Page:
    def __init__(self,state):
        self.state=state
        self.url='https://www.youtube.com/watch?v=test'
        self.results=[video('پایتخت ۷ قسمت اول'),video('پایتخت ۷ قسمت ۷')]
        self.clicked=[];self.urls=[]
    def goto(self,url,**kwargs):self.urls.append(url)
    def get_by_role(self,*args,**kwargs):return Empty()
    def locator(self,selector):
        if selector.startswith('ytd-video-renderer'):return Links(self)
        if selector=='video':return Video()
        return Empty()
    def wait_for_load_state(self,*args,**kwargs):pass
    def wait_for_function(self,*args,**kwargs):pass
    def evaluate(self,script):return self.state
    def is_closed(self):return False


@pytest.fixture
def page(monkeypatch):
    page=Page({'playing':True,'advertisement':False})
    monkeypatch.setattr(browser,'_need',lambda:None)
    monkeypatch.setattr(browser,'_page',lambda **kwargs:page)
    return page


def test_full_tool_selects_correct_video_and_reports_verified_playback(page):
    result=browser.YouTubePlayTool().execute(query='پایتخت ۷ قسمت ۷')
    assert result.success and result.metadata['playing']
    assert page.clicked==[1]
    assert 'search_query=' in page.urls[0]


@pytest.mark.parametrize('state',[{'playing':False,'advertisement':False},{'playing':True,'advertisement':True}])
def test_open_page_or_ad_is_never_reported_as_episode_playing(page,state):
    page.state=state
    result=browser.YouTubePlayTool().execute(query='پایتخت ۷ قسمت ۷')
    assert result.metadata['playing'] is False
    assert 'هنوز تأیید نشده' in result.content


def test_no_matching_video_does_not_click_an_unrelated_episode(page):
    result=browser.YouTubePlayTool().execute(query='پایتخت ۷ قسمت ۹')
    assert not result.success and not page.clicked


def test_explicit_media_request_needs_no_repeated_local_approval(page):
    callback=Mock(side_effect=AssertionError('Must not ask twice for media playback'))
    executor=ToolExecutor([browser.YouTubePlayTool()],confirm_callback=callback)
    try:
        result=executor.execute(ToolCall(name='youtube_play',arguments='{"query":"پایتخت ۷ قسمت ۷"}'))
        assert result.success and result.metadata['playing']
        callback.assert_not_called()
    finally:executor.shutdown()


def test_computer_delegates_video_context_instead_of_open_app(monkeypatch):
    from ultimate_khorshid.agents import computer
    from ultimate_khorshid.agents.base import AgentContext,AgentResult
    captured=[]
    class Worker:
        def __init__(self,*args,**kwargs):pass
        def run(self,ctx):
            captured.append(ctx)
            return AgentResult(content='context delegated')
    monkeypatch.setattr(computer,'OrchestratorAgent',Worker)
    ctx=AgentContext();ctx.conversation.add('user','پایتخت هفت قسمت هفتم توی یوتیوب برام باز کن')
    result=computer.ComputerAgent(None,'mock').run(ctx)
    assert result.content=='context delegated' and captured==[ctx]
