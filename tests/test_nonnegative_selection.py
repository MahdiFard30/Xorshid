import json
import pytest
from ultimate_khorshid.tools.demo_learning import Experience,NAMES


@pytest.mark.parametrize('score',[-.02639,-1.,-1e-9])
def test_single_negative_candidate_cannot_force_entry_and_evidence_is_retained(tmp_path,monkeypatch,score):
    learner=Experience(tmp_path/'experience.json')
    monkeypatch.setattr(learner,'score',lambda *a,**k:score)
    signals={NAMES[0]:[1]}
    assert learner.choose(signals) is None
    d=learner.data['decisions'][-1]
    assert d['score_rejected']==[NAMES[0]] and NAMES[0] in d['candidates']
    assert d['score_details'][NAMES[0]]['unrounded_total_score']==score
    assert not d['score_details'][NAMES[0]]['entry_score_eligible']
    assert 'entry declined' in d['reason']
    reloaded=Experience(learner.path)
    assert reloaded.data['decisions'][-1]==d
    assert json.loads(learner.path.with_suffix('.jsonl').read_text().splitlines()[-1])['selected'] is None


def test_all_negative_candidates_abstain_but_zero_and_positive_remain_eligible(tmp_path,monkeypatch):
    learner=Experience(tmp_path/'experience.json');values={NAMES[0]:-.1,NAMES[1]:-.2}
    monkeypatch.setattr(learner,'score',lambda name,*args,**kwargs:values[name])
    signals={name:[1] for name in values}
    assert learner.rank(signals)['selected'] is None
    values[NAMES[1]]=0.
    assert learner.rank(signals)['selected']==NAMES[1]
    values[NAMES[0]]=.4
    assert learner.rank(signals)['selected']==NAMES[0]
    assert learner.rank({NAMES[0]:[0],NAMES[1]:[0]})['selected'] is None


def test_exploration_cannot_rescue_negative_evidence(tmp_path,monkeypatch):
    learner=Experience(tmp_path/'experience.json')
    monkeypatch.setattr(learner,'score',lambda name,explore=True:.05 if explore else -.2)
    result=learner.rank({NAMES[0]:[1]})
    assert result['selected'] is None
    assert result['candidates'][NAMES[0]]==.05
    assert result['evidence_rejected']==[NAMES[0]]
    detail=result['score_details'][NAMES[0]]
    assert detail['evidence_score']==-.2
    assert detail['exploration_bonus']==.25
    assert detail['entry_score_rejections']==['negative_evidence_without_exploration']
    assert learner.rank({NAMES[0]:[1]},news_adjustments={NAMES[0]:-.1})['selected'] is None


def test_evidence_gate_uses_unrounded_values_and_keeps_neutral_exploration(tmp_path,monkeypatch):
    learner=Experience(tmp_path/'experience.json')
    values={NAMES[0]:-1e-9,NAMES[1]:0.}
    monkeypatch.setattr(learner,'score',lambda name,explore=True:values[name]+(.5 if explore else 0))
    result=learner.rank({name:[1] for name in values})
    assert result['selected']==NAMES[1]
    assert result['score_details'][NAMES[0]]['experience_score']==0.
    assert not result['score_details'][NAMES[0]]['entry_score_eligible']
    assert result['score_details'][NAMES[1]]['entry_score_eligible']


def test_context_evidence_is_checked_before_exploration(tmp_path,monkeypatch):
    learner=Experience(tmp_path/'experience.json')
    monkeypatch.setattr(learner,'score',lambda name,explore=True:.6 if explore else .1)
    model=type('Context',(),{'assess':lambda self,*args:{'adjustment':-.2,'paused':False}})()
    monkeypatch.setattr(learner,'contextual',lambda:model)
    result=learner.rank({NAMES[0]:[1]},context={'trend':'range'})
    assert result['selected'] is None
    assert result['score_details'][NAMES[0]]['evidence_score']==pytest.approx(-.1)
    assert result['candidates'][NAMES[0]]==.4


def test_rejected_positive_total_survives_restart_and_can_recover_with_new_evidence(tmp_path):
    learner=Experience(tmp_path/'experience.json')
    learner.reward(NAMES[0],'verified_demo',-.1,-10)
    assert learner.score(NAMES[0])>0 and learner.score(NAMES[0],False)<0
    assert learner.choose({NAMES[0]:[1]}) is None
    restored=Experience(learner.path)
    assert restored.data['decisions'][-1]['evidence_rejected']==[NAMES[0]]
    assert restored.data['stats'][NAMES[0]]['verified_demo_net']==-10
    restored.reward(NAMES[0],'verified_demo',1,100)
    assert restored.choose({NAMES[0]:[1]})==NAMES[0]


def test_authorized_adaptive_execution_uses_real_negative_evidence(tmp_path,monkeypatch):
    from test_execution_policy import trial,snapshot,NOW
    from ultimate_khorshid.tools import execution_policy as policy
    monkeypatch.setattr(policy,'fingerprint',lambda root:'reviewed-code')
    data=trial(tmp_path);data['demo_trials'][0].update(selection_mode='adaptive_demo',strategies=[NAMES[0]])
    p=tmp_path/'configs/trading_execution.json';p.parent.mkdir();p.write_text(json.dumps(data))
    learner=Experience(tmp_path/'experience.json')
    for _ in range(3):learner.reward(NAMES[0],'verified_demo',-1,-10);learner.attempted(NAMES[0])
    before=json.loads(json.dumps(learner.data['stats']))
    result=policy.select(tmp_path,snapshot(),{NAMES[0]:[1]},now=NOW,learner=learner)
    assert result['allowed'] and result['selected'] is None and result['score_rejected']==[NAMES[0]]
    assert learner.data['stats']==before
    close={'action':'close_tickets','tickets':[42]}
    assert policy.constrain(close,tmp_path,snapshot(),NOW) is close
