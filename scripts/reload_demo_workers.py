"""Supervised code reload preserving broker exposure, run IDs and experience.

No stop marker is cleared or created. Only settled requests and fresh matching
leases may be handed over. The terminal's existing lease/SL controls remain on.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    from ultimate_khorshid.tools.mt5_multi import SYMBOLS,select,worker
    from ultimate_khorshid.tools.execution_policy import fingerprint
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--refresh-fingerprint',action='store_true')
    p.add_argument('--preserve-learning',action='store_true',help='Explicitly continue evidence for this approved code revision')
    p.add_argument('--pause-entries',action='store_true',help='User-approved entry-only pause; preserve active management and learning')
    a=p.parse_args()
    if a.preserve_learning and not a.refresh_fingerprint:p.error('--preserve-learning requires --refresh-fingerprint')
    backup=ROOT/'local-backups'/('worker-reload-'+str(time.time_ns()));backup.mkdir()
    config=ROOT/'configs/trading_execution.json';old=config.read_text();data=json.loads(old)
    (backup/'trading_execution.before.json').write_text(old)
    pids={}
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            args=(proc/'cmdline').read_bytes().split(b'\0')
            if b'ultimate_khorshid.tools.mt5_multi_worker' not in args or not ({b'run',b'resume'} & set(args)):continue
            env=(proc/'environ').read_bytes().split(b'\0')
            for sym in SYMBOLS:
                if ('KHORSHID_DEMO_SYMBOL='+sym).encode() in env:
                    if sym in pids:raise ValueError('Duplicate demo worker')
                    pids[sym]=int(proc.name)
        except (FileNotFoundError,ProcessLookupError):continue
    if set(pids)!=set(SYMBOLS):raise ValueError('All three workers must already be running')
    paused=set();result={}
    with (ROOT/'.khorshid-multi/controller.lock').open('a') as controller:
        fcntl.flock(controller,fcntl.LOCK_EX)
        try:
            for sym in SYMBOLS:
                select(sym);s=worker.snapshot()
                if not s['demo'] or (worker.files()/'khorshid_demo_stop.flag').exists():raise ValueError('Stopped or non-demo channel')
                os.kill(pids[sym],signal.SIGSTOP);paused.add(sym)
            for sym in SYMBOLS:
                select(sym);run=worker.state();lease=(worker.files()/'khorshid_demo_lease.tsv').read_text().split('\t')
                if not 0<=time.time()-int(lease[0])<5 or lease[2]!=run['id']:raise ValueError('Fresh session lease required')
                request=worker.files()/'khorshid_demo_request.tsv'
                if request.exists():
                    ident=int(request.read_text().split('\t')[0]);ack=json.loads((worker.files()/'khorshid_demo_ack.json').read_text())
                    if ack.get('id')!=ident:raise ValueError('Unsettled request; reload cancelled')
                (backup/(sym+'.state.before.json')).write_text(json.dumps(run,ensure_ascii=False,indent=2)+'\n')
            if a.refresh_fingerprint:
                from ultimate_khorshid.tools.execution_policy import learning_identity
                from ultimate_khorshid.tools.trading_controls import read
                controls=read(ROOT);new_source=fingerprint(ROOT)
                for row in data['demo_trials']:
                    previous_identity=learning_identity(row,controls)
                    if a.preserve_learning:
                        anchor=(row.get('learning_source_sha256') if row.get('learning_source_for_sha256')==row.get('source_sha256') else None) or row['source_sha256']
                        row.update(learning_source_sha256=anchor,learning_source_for_sha256=new_source)
                    row['source_sha256']=new_source
                    if a.preserve_learning and learning_identity(row,controls)!=previous_identity:
                        raise ValueError('Learning continuation identity mismatch; config not written')
            if a.pause_entries:
                data['enabled']=True
                data['entries_paused']=True
                data['entry_pause_reason']='User approved temporary entry pause and negative-score correction on 2026-10-29'
            if a.refresh_fingerprint or a.pause_entries:
                worker.atomic(config,json.dumps(data,ensure_ascii=False,indent=2)+'\n')
            started=time.time()
            for sym in SYMBOLS:
                select(sym);os.kill(pids[sym],signal.SIGKILL);paused.remove(sym)
                for _ in range(100):
                    if not worker.running():break
                    time.sleep(.01)
                else:raise RuntimeError('Old worker lock still held')
                env=os.environ.copy();env['KHORSHID_DEMO_SYMBOL']=sym
                with (worker.storage()/'runner.log').open('a') as log:
                    proc=subprocess.Popen([sys.executable,'-m','ultimate_khorshid.tools.mt5_multi_worker','resume'],
                        cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
                for _ in range(100):
                    if proc.poll() is not None:raise RuntimeError(sym+' failed; inspect runner.log')
                    state=worker.state()
                    if worker.running() and state.get('resumed_utc',0)>=started:
                        result[sym]={'pid':proc.pid,'run_id':state['id'],'resumed_utc':state['resumed_utc']};break
                    time.sleep(.02)
                else:raise RuntimeError(sym+' reload confirmation timed out')
            (backup/'handover.json').write_text(json.dumps(result,indent=2)+'\n')
        except BaseException:
            if a.pause_entries:
                # Old workers do not know entries_paused. Never let a failed
                # handover resume one with new-entry authorization enabled.
                data['enabled']=False
                data['entries_paused']=True
                worker.atomic(config,json.dumps(data,ensure_ascii=False,indent=2)+'\n')
            raise
        finally:
            for sym in paused:
                try:os.kill(pids[sym],signal.SIGCONT)
                except ProcessLookupError:pass
    print(json.dumps({'backup':str(backup),'workers':result}))

if __name__=='__main__':main()
