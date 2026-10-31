import copy
import importlib.util
import json
from pathlib import Path

import pytest

from ultimate_khorshid.tools.learning_evidence import assess
from ultimate_khorshid.tools.demo_learning import Experience, NAMES
from ultimate_khorshid.tools.market_learning import ContextModel, describe


def stats(values, paper=()):
    return {'verified_demo_window':[{'r':v,'utc':i+1} for i,v in enumerate(values)],
            'paper_window':[{'r':v,'utc':100+i} for i,v in enumerate(paper)]}


@pytest.mark.parametrize('edge', [.0001, .001, .01, .05])
def test_tiny_positive_evidence_does_not_jump_to_full_size(edge):
    result=assess(stats([edge]*8))
    assert result['eligible'] and result['stage']=='adaptive_demo'
    assert .25<result['risk_multiplier']<.5


def test_risk_rises_smoothly_with_strength_and_can_reach_existing_full_size():
    values=[assess(stats([edge]*8))['risk_multiplier'] for edge in (.001,.01,.05,.1,1.)]
    assert values==sorted(values)
    assert len(set(values))==len(values)
    assert values[-1]==1.
    assert assess(stats([1.]*7))['risk_multiplier']==.25


def test_recent_losses_reduce_size_even_with_positive_lifetime_mean():
    data=stats([1.]*15+[-1.]*5);before=copy.deepcopy(data)
    result=assess(data)
    assert result['demo']['mean_r']>0 and result['recent_demo']['mean_r']==-1
    assert result['eligible'] and result['stage']=='adaptive_demo'
    assert result['risk_multiplier']==.25
    assert data==before


def test_existing_quarantine_and_shadow_retrial_are_not_changed():
    bad=assess(stats([-1.]*8))
    assert not bad['eligible'] and bad['risk_multiplier']==0
    recovered=assess(stats([-1.]*8, [1.]*20))
    assert recovered['eligible'] and recovered['stage']=='shadow_retrial'
    assert recovered['risk_multiplier']==.25


def test_sparse_context_remains_bounded_under_restored_nonnegative_entry_gate(tmp_path):
    from test_market_learning import bars, outcome
    learner=Experience(tmp_path/'experience.json');learner.data['account']=7
    context=describe(bars(),utc=100000,spread=.02)
    learner.contextual().observe({'1':outcome('1',reward=-1,context=context)})
    signals={NAMES[0]:[1],NAMES[1]:[1]}
    before=learner.rank(signals)
    after=learner.rank(signals,context=context)
    assert before['selected']==NAMES[0] and after['selected']==NAMES[1]
    detail=after['context_assessments'][NAMES[0]]
    assert detail['samples']==1 and detail['adjustment']==pytest.approx(-1/31)
    assert not detail['paused']
    # Oct 29 approval restores the pre-exploration nonnegative entry rule.
    assert not after['score_details'][NAMES[0]]['entry_score_eligible']
    assert learner.rank({NAMES[0]:[1]},context=context)['selected'] is None
    assert learner.contextual().assess(NAMES[0],context,-1)['adjustment']==0


def test_sparse_context_and_experience_survive_reopen(tmp_path):
    from test_market_learning import bars, outcome
    path=tmp_path/'experience.json';learner=Experience(path)
    learner.data['account']=7;learner.set_regime('existing-regime')
    context=describe(bars(),utc=100000,spread=.02)
    learner.contextual().observe({'1':outcome('1',reward=-1,context=context)})
    learner.reward(NAMES[0],'verified_demo',1,10);learner.save()
    restored=Experience(path);restored.set_regime('existing-regime')
    assert restored.stats[NAMES[0]]['verified_demo_n']==1
    assert restored.stats[NAMES[0]]['verified_demo_net']==10
    assert restored.contextual().assess(NAMES[0],context,1)['adjustment']<0


def test_explicit_code_bound_learning_continuation_does_not_weaken_authorization(tmp_path,monkeypatch):
    from test_execution_policy import trial, snapshot, NOW
    from ultimate_khorshid.tools import execution_policy as policy
    data=trial(tmp_path);row=data['demo_trials'][0];controls={'max_positions':1}
    original=policy.learning_identity(row,controls)
    old_source=row['source_sha256'];row.update(source_sha256='new-reviewed-code',
        learning_source_sha256=old_source,learning_source_for_sha256='new-reviewed-code')
    assert policy.learning_identity(row,controls)==original
    changed=copy.deepcopy(row);changed['scope']['account']=99
    assert policy.learning_identity(changed,controls)!=original
    changed=copy.deepcopy(row);changed['source_sha256']='another-code'
    assert policy.learning_identity(changed,controls)!=original
    assert policy.learning_identity(row,{'max_positions':2})!=original
    config=tmp_path/'configs/trading_execution.json';config.parent.mkdir();config.write_text(json.dumps(data))
    monkeypatch.setattr(policy,'fingerprint',lambda root:old_source)
    assert not policy.authorize(tmp_path,snapshot(),now=NOW)['allowed']
    monkeypatch.setattr(policy,'fingerprint',lambda root:'new-reviewed-code')
    assert policy.authorize(tmp_path,snapshot(),now=NOW)['allowed']
