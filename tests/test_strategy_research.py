import copy
import json

import pytest

from ultimate_khorshid.tools import strategy_research as research
from ultimate_khorshid.tools.demo_lab import CATALOG, simulate


def sample(n=1000):
    bars=[{'time':100000+i*900,'open':100+i*.01,'close':100+i*.01+.002,
           'high':100+i*.01+.03,'low':100+i*.01-.03,'spread':2} for i in range(n)]
    return {'login':7,'symbol':'EURUSD','period':15,'period_seconds':900,'point':.001,'bars':bars}


def metrics(trades=30, profit=2):
    return {'trades':trades,'return_pct':profit,'profit_factor':1.4,'drawdown_pct':1.,'win_rate':.6}


def fake_screen(monkeypatch):
    calls=[]
    def fake(bars,signal,atr,start,end,point,cost_multiplier=1.,entry_allowed=None):
        calls.append((start,end,entry_allowed))
        return metrics(profit=2 if entry_allowed else 1)
    monkeypatch.setattr(research,'simulate',fake)
    return calls


def test_generation_is_bounded_declarative_and_does_not_change_live_catalog():
    original=copy.deepcopy(CATALOG)
    definitions=research.hypotheses()
    assert len(definitions)==30 and len({d['id'] for d in definitions})==30
    assert CATALOG==original
    assert all(d['base'] in {c[0] for c in CATALOG} for d in definitions)
    assert all(d['filter'] in research.FILTERS for d in definitions)


def test_selection_is_frozen_before_holdout_and_only_one_candidate_is_tested(tmp_path,monkeypatch):
    calls=fake_screen(monkeypatch)
    result=research.StrategyLab(tmp_path).analyze(sample())
    assert result['status']=='ready_for_forward_paper'
    heldout=[c for c in calls if c[0]==800]
    assert len(heldout)==3  # Chosen candidate, cost stress, matched baseline; never 30 holdout searches.
    audit=json.loads((tmp_path/'experiments.jsonl').read_text())
    assert audit['candidate_before_holdout']==result['candidate_before_holdout']
    assert result['automatic_deployment'] is False
    assert result['independent_validation'] is False


def test_identical_experiment_cached_and_overlapping_holdout_not_reused(tmp_path,monkeypatch):
    calls=fake_screen(monkeypatch)
    lab=research.StrategyLab(tmp_path); first=lab.analyze(sample())
    count=len(calls)
    assert lab.analyze(sample())==first and len(calls)==count
    newer=sample();newer['bars'][-1]['high']+=.01
    result=lab.analyze(newer)
    assert result['overlaps_previous_holdout']
    assert result['status']=='overlapping_holdout_not_retested'
    assert len([c for c in calls if c[0]==800])==3


def test_holdout_changes_cannot_change_selected_candidate(tmp_path,monkeypatch):
    fake_screen(monkeypatch)
    original=sample(); changed=copy.deepcopy(original)
    for bar in changed['bars'][800:]:
        for key in ('open','close','high','low'):bar[key]*=2
    a=research.StrategyLab(tmp_path/'a').analyze(original)
    b=research.StrategyLab(tmp_path/'b').analyze(changed)
    assert a['candidate_before_holdout']==b['candidate_before_holdout']
    for key in a['results']:
        assert a['results'][key]['train']==b['results'][key]['train']
        assert a['results'][key]['validation']==b['results'][key]['validation']


def test_unqualified_candidates_never_reach_holdout(tmp_path,monkeypatch):
    monkeypatch.setattr(research,'simulate',lambda *a,**kw:metrics(trades=0,profit=-1))
    result=research.StrategyLab(tmp_path).analyze(sample())
    assert result['status']=='no_candidate' and 'holdout' not in result


def test_entry_filter_does_not_suppress_opposite_signal_exit():
    data=sample(70)['bars'];signals=[0]*70;atr=[.1]*70
    signals[60]=1;signals[61]=-1
    mask=[False]*70;mask[60]=True
    result=simulate(data,signals,atr,61,65,.001,entry_allowed=mask)
    assert result['trades']==1


def experiment():
    definition=research.hypotheses()[0]
    return {'status':'ready_for_forward_paper','experiment_id':'fixed',
            'scope':[7,'EURUSD',15],'candidate_before_holdout':definition['id'],
            'results':{definition['id']:{'definition':definition}}}


def test_forward_trial_starts_without_backfilling_and_gap_discards_unobserved_exposure(tmp_path):
    path=tmp_path/'forward.json';trial=research.ForwardTrial(path)
    first=trial.observe(sample(100),experiment(),now=100)
    assert first['baseline']['closed']==0 and first['challenger']['closed']==0
    assert first['baseline']['position'] is None
    # A missed candle cannot become a retrospective win or evidence for promotion.
    second=trial.observe(sample(103),experiment(),now=101)
    assert second['gaps']==1 and second['baseline']['closed']==0
    assert second['status']=='forward_observing'


def test_first_already_forming_bar_does_not_allow_a_retrospective_entry(tmp_path,monkeypatch):
    trial=research.ForwardTrial(tmp_path/'forward.json')
    trial.observe(sample(100),experiment(),now=100)
    monkeypatch.setattr(research,'indicators',lambda bars:({CATALOG[0][0]:[1]*len(bars)},[.1]*len(bars)))
    a=trial.observe(sample(101),experiment(),now=101)
    assert a['baseline']['position'] is None
    b=trial.observe(sample(102),experiment(),now=102)
    assert b['baseline']['position'] is not None


def test_forward_candidate_and_account_cannot_change_mid_trial(tmp_path):
    trial=research.ForwardTrial(tmp_path/'forward.json')
    trial.observe(sample(100),experiment(),now=100)
    other=experiment();other['experiment_id']='replacement'
    with pytest.raises(ValueError,match='frozen'):
        trial.observe(sample(101),other,now=101)
    other=sample(101);other['login']=999
    with pytest.raises(ValueError,match='mismatch'):
        trial.observe(other,experiment(),now=101)


def test_both_stop_and_target_uses_stop_first():
    book={'closed':0,'net_r':0.,'wins':0,'peak_r':0.,'drawdown_r':0.,'position':None}
    bar={'time':1000,'open':100.,'close':100.,'high':110.,'low':90.,'spread':2}
    research._book_step(book,bar,1,1.,.001,True)
    assert book['closed']==1 and book['net_r']<0
    assert book['last_close']['reason']=='stop'
