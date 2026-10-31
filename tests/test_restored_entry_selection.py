import copy
import json

import pytest

from ultimate_khorshid.tools.demo_learning import Experience, NAMES
from ultimate_khorshid.tools import execution_policy as policy
from ultimate_khorshid.tools.mt5_entry_policy import decision


def learner(tmp_path, reward=-.01):
    exp=Experience(tmp_path/'experience.json');exp.set_regime('existing')
    stats=exp.stats[NAMES[0]]
    stats['verified_demo_n']=4
    stats['verified_demo_window']=[{'r':reward,'utc':i+1} for i in range(4)]
    return exp


def test_exploration_cannot_rescue_negative_evidence_and_history_is_preserved(tmp_path):
    exp=learner(tmp_path);before=copy.deepcopy(exp.data)
    result=exp.rank({NAMES[0]:[1]})
    details=result['score_details'][NAMES[0]]
    assert details['total_score']>0 and details['evidence_before_exploration']<0
    assert result['selected'] is None
    assert 'negative_evidence_before_exploration' in details['entry_rejection_reasons']
    assert exp.data==before
    exp.stats[NAMES[0]]['verified_demo_window']=[{'r':.1,'utc':i+1} for i in range(4)]
    assert exp.rank({NAMES[0]:[1]})['selected']==NAMES[0]


@pytest.mark.parametrize('evidence,eligible',[(-1e-14,False),(0,True),(1e-14,True)])
def test_unrounded_boundary_keeps_zero_eligible(tmp_path,evidence,eligible):
    exp=learner(tmp_path,evidence)
    assert (exp.rank({NAMES[0]:[1]})['selected'] is not None)==eligible


def test_context_is_checked_before_exploration_and_final_score_has_own_gate(tmp_path,monkeypatch):
    exp=learner(tmp_path,.01)
    class Context:
        def assess(self,*args):return {'adjustment':-.02,'paused':False}
    monkeypatch.setattr(exp,'contextual',lambda:Context())
    result=exp.rank({NAMES[0]:[1]},context={'trend':'range'})
    assert result['selected'] is None
    assert result['score_details'][NAMES[0]]['evidence_before_exploration']==pytest.approx(-.01)
    monkeypatch.setattr(exp,'score',lambda name,explore=True:-.01 if explore else .1)
    result=exp.rank({NAMES[0]:[1]})
    assert result['selected'] is None
    assert 'negative_final_score' in result['score_details'][NAMES[0]]['entry_rejection_reasons']


def test_negative_entry_evidence_does_not_block_opposing_signal_exit(tmp_path):
    exp=learner(tmp_path)
    signals={NAMES[0]:[-1]};selected=exp.rank(signals)['selected']
    snapshot={'positions':[{'ticket':9,'comment':'KH:'+NAMES[0],'direction':1,'bars_held':1,'progress_r':-.1}]}
    result=decision(snapshot,signals,1,selected)
    assert result['action']=='close_tickets' and result['tickets']==[9]


def test_persistent_entry_pause_keeps_ranking_learning_and_exit_permission(tmp_path,monkeypatch):
    from test_execution_policy import trial,snapshot,NOW
    data=trial(tmp_path);data['entries_paused']=True
    row=data['demo_trials'][0];row.update(selection_mode='adaptive_demo',strategies=[NAMES[0]])
    config=tmp_path/'configs/trading_execution.json';config.parent.mkdir();config.write_text(json.dumps(data))
    monkeypatch.setattr(policy,'fingerprint',lambda root:'reviewed-code')
    exp=learner(tmp_path,.1)
    result=policy.select(tmp_path,snapshot(),{NAMES[0]:[1]},now=NOW,learner=exp)
    assert result['status']=='entries_paused' and result['selected'] is None
    assert result['score_details'] and not result['allowed']
    assert policy.authorize(tmp_path,snapshot(),now=NOW)['allowed']
    assert policy.constrain({'action':'open'},tmp_path,snapshot(),NOW)['status']=='entries_paused'
    close={'action':'close_tickets','tickets':[9]}
    assert policy.constrain(close,tmp_path,snapshot(),NOW) is close
    # Flag is durable on disk; there is no timer or automatic expiry/resume.
    assert policy.load(tmp_path)['entries_paused'] is True
