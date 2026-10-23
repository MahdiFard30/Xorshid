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


def test_filter_applies_to_final_score_and_preserves_unapproved_weights(tmp_path,monkeypatch):
    learner=Experience(tmp_path/'experience.json')
    monkeypatch.setattr(learner,'score',lambda name,explore=True:.05 if explore else -.2)
    assert learner.rank({NAMES[0]:[1]})['selected']==NAMES[0]
    assert learner.rank({NAMES[0]:[1]},news_adjustments={NAMES[0]:-.1})['selected'] is None


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
