import hashlib
import importlib.util
import json
from pathlib import Path
import time

from ultimate_khorshid.tools.trade_memory import TradeMemory


def module():
    path=Path(__file__).resolve().parents[1]/'scripts/diagnose_trading.py'
    spec=importlib.util.spec_from_file_location('trading_diagnosis',path)
    loaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(loaded)
    return loaded


def test_diagnostic_does_not_change_runtime_databases_or_snapshots(tmp_path):
    root=tmp_path/'project';terminal=tmp_path/'terminal/MQL5/Files/khorshid_multi'
    sources=[]
    for symbol in ('XAUUSD','EURUSD','USDJPY'):
        folder=root/'.khorshid-multi'/symbol;folder.mkdir(parents=True)
        TradeMemory(folder/'trade_memory.sqlite')
        (folder/'state.json').write_text(json.dumps({'status':'running'}))
        channel=terminal/symbol;channel.mkdir(parents=True)
        s={'login':123,'symbol':symbol,'period':5,'currency':'USD','positions':[],
           'generated_utc':time.time(),'broker_utc_offset_seconds':7200,'deals':[]}
        (channel/'khorshid_demo_snapshot.json').write_text(json.dumps(s))
        sources.extend(folder.glob('*sqlite'));sources.append(folder/'state.json')
        sources.append(channel/'khorshid_demo_snapshot.json')
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    result=module().capture(root,terminal,tmp_path/'output')
    assert not result['orders_sent'] and not result['runtime_changed']
    assert before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    assert all(v['closed_in_window']['closed']==0 for v in result['symbols'].values())


def test_incomplete_positions_are_not_counted_as_wins():
    result=module().aggregate([
        {'closed_complete':False,'learning_eligible':False,'net':1000},
        {'closed_complete':True,'learning_eligible':True,'net':-10,'normalized_reward':-.5}])
    assert result['closed']==1 and result['wins']==0 and result['net']==-10
    assert result['mean_verified_r']==-.5 and result['incomplete']==1
