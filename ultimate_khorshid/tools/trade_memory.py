"""Durable decision/deal journal. Observes demo execution; never sends orders."""
import json
from contextlib import contextmanager
import math
from pathlib import Path
import sqlite3
import time


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def position_outcome(login, symbol, deals, open_ids, intents, currency):
    """Require matching entry/exit volume and contemporaneous entry-risk evidence."""
    entries = [d for d in deals if d.get('entry') == 0]
    exits = [d for d in deals if d.get('entry') in (1, 3)]
    ident = str(deals[0]['position_id'])
    problems = []
    if ident in open_ids:
        problems.append('position_still_open')
    if not entries or not exits or any(d.get('entry') not in (0, 1, 3) for d in deals):
        problems.append('missing_entry_exit_or_unsupported_reversal')
    if any(not positive(d.get('volume')) for d in deals):
        problems.append('volume_history_unavailable')
    elif not math.isclose(sum(d['volume'] for d in entries), sum(d['volume'] for d in exits), rel_tol=1e-8, abs_tol=1e-8):
        problems.append('entry_exit_volume_mismatch')
    strategies = {d.get('comment', '')[3:] for d in entries if d.get('comment', '').startswith('KH:')}
    if len(strategies) != 1:
        problems.append('entry_strategy_unavailable_or_mixed')
    risk = 0.0
    for d in entries:
        record = d.get('initial_risk') or {}
        if not (record.get('method') == 'entry_fill_sl_estimate' and record.get('login') == login
                and record.get('deal') == d['ticket'] and record.get('position_id') == d['position_id']
                and record.get('order') == d.get('order') and positive(record.get('cash'))
                and record.get('symbol') == symbol and record.get('entry_time') == d.get('time')
                and record.get('currency') == currency and positive(record.get('volume'))
                and positive(d.get('volume')) and math.isclose(record['volume'],d['volume'],rel_tol=1e-8,abs_tol=1e-8)
                and positive(record.get('price')) and record.get('price') == d.get('price')
                and positive(record.get('sl')) and isinstance(record.get('capture_lag_seconds'),int)
                and -5 <= record['capture_lag_seconds'] <= 60):
            problems.append('initial_risk_unavailable')
        else:
            risk += record['cash']
    costs_known = all(all(isinstance(d.get(k), (int, float)) and not isinstance(d[k], bool)
                          and math.isfinite(d[k]) for k in ('profit', 'commission', 'swap', 'fee')) for d in deals)
    if not costs_known:
        problems.append('cost_breakdown_unavailable')
    totals = {k: sum(d.get(k, 0) for d in deals) if costs_known else None for k in ('profit', 'commission', 'swap', 'fee')}
    net = sum(totals.values()) if costs_known else sum(d['net'] for d in deals)
    normalized = net / risk if not problems and positive(risk) else None
    if normalized is not None and not math.isfinite(normalized):
        problems.append('invalid_normalized_result'); normalized = None
    linked = [intents[str(d['order'])] for d in entries if str(d.get('order')) in intents]
    versions = {c.get('decision', {}).get('plan', {}).get('exit_policy_version') for c in linked}
    exit_policy = next(iter(versions)) if len(versions) == 1 and len(linked) == len(entries) else None
    return {'position_id': ident, 'account': login, 'symbol': symbol,
            'closed_time_server':max((d.get('time',0) for d in exits),default=None),
            'strategy': next(iter(strategies)) if len(strategies) == 1 else 'unknown',
            'has_exit': bool(exits), 'closed_complete': not any(p in problems for p in (
                'position_still_open', 'missing_entry_exit_or_unsupported_reversal',
                'volume_history_unavailable', 'entry_exit_volume_mismatch')),
            'net': net, **totals, 'risk_cash': risk if positive(risk) else None,
            'normalized_reward': normalized, 'normalization': 'net / sum of entry-fill SL risk estimates; excludes guaranteed execution',
            'learning_eligible': normalized is not None, 'evidence_problems': sorted(set(problems)),
            'entry_contexts': linked, 'exit_policy_version': exit_policy, 'exit_reasons': [d.get('reason') for d in exits],
            'deal_tickets': [d['ticket'] for d in deals]}


class TradeMemory:
    def __init__(self, path):
        self.path = Path(path)
        self.readonly = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        from ultimate_khorshid.tools.history_archive import Archive
        self.archive=Archive(self.path.with_suffix('.history.sqlite'))
        with self.connect() as con:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS intents(account INTEGER, request INTEGER, symbol TEXT,
                    period INTEGER, data TEXT, PRIMARY KEY(account,request));
                CREATE TABLE IF NOT EXISTS acknowledgements(account INTEGER, request INTEGER,
                    data TEXT, PRIMARY KEY(account,request));
                CREATE TABLE IF NOT EXISTS observations(account INTEGER, ticket INTEGER, symbol TEXT,
                    data TEXT, PRIMARY KEY(account,ticket));
                CREATE TABLE IF NOT EXISTS decisions(account INTEGER, symbol TEXT, period INTEGER,
                    run TEXT, bar INTEGER, data TEXT, PRIMARY KEY(account,symbol,period,run,bar));
                CREATE TABLE IF NOT EXISTS position_samples(account INTEGER, position TEXT, utc REAL,
                    profit REAL, swap REAL, risk REAL, progress REAL, data TEXT,
                    PRIMARY KEY(account,position,utc));
            ''')

    @classmethod
    def read_only(cls, path):
        journal=cls.__new__(cls)
        journal.path=Path(path)
        if not journal.path.is_file():
            raise FileNotFoundError(journal.path)
        journal.readonly=True
        return journal

    @contextmanager
    def connect(self):
        con = (sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro', uri=True, timeout=3)
               if self.readonly else sqlite3.connect(self.path, timeout=10))
        try:
            with con:
                yield con
        finally:
            con.close()

    def record_intent(self, run, snapshot, ident, action, direction, distance, target, strategy, tickets):
        # Persist BEFORE publishing the request. An intent is not proof of execution.
        bars = snapshot['bars'][-20:]
        context = {'request_id': ident, 'run_id': run['id'], 'recorded_utc': time.time(),
                   'action': action, 'direction': direction, 'strategy': strategy, 'tickets': list(tickets),
                   'signal_bar': bars[-1]['time'], 'sl_distance_requested': distance, 'tp_distance_requested': target,
                   'balance': snapshot['balance'], 'equity': snapshot['equity'], 'bid': snapshot['bid'], 'ask': snapshot['ask'],
                   'quote_age_seconds': snapshot['tick_age_seconds'], 'recent_closed_bars': bars,
                   'news': run.get('news_filter', {}), 'decision': run.get('entry_decision', {}),
                   'executor_instance': snapshot.get('executor_instance'), 'currency': snapshot['currency']}
        context.update(experiment_id=run.get('experiment_id'),code_revision=run.get('code_revision'),
                       learning_regime=run.get('learning_regime'))
        self.archive.save('order_intent',f"{snapshot['login']}:{ident}",context,
                          {'account':snapshot['login'],'symbol':snapshot['symbol'],'period':snapshot['period']})
        with self.connect() as con:
            con.execute('INSERT INTO intents VALUES (?,?,?,?,?)',
                        (snapshot['login'], ident, snapshot['symbol'], snapshot['period'], encode(context)))

    def record_decision(self, run, snapshot):
        identity=f"{snapshot['login']}:{snapshot['symbol']}:{snapshot['period']}:{run['id']}:{snapshot['bars'][-1]['time']}"
        labels={k:run.get(k) for k in ('experiment_id','code_revision','learning_regime')}
        labels.update(account=snapshot['login'],symbol=snapshot['symbol'],period=snapshot['period'])
        with self.connect() as con:
            old=con.execute('SELECT data FROM decisions WHERE account=? AND symbol=? AND period=? AND run=? AND bar=?',
                (snapshot['login'],snapshot['symbol'],snapshot['period'],run['id'],snapshot['bars'][-1]['time'])).fetchone()
            if old:self.archive.save('decision',identity,json.loads(old[0]),labels,seed=True)
            self.archive.save('decision',identity,run['entry_decision'],labels)
            con.execute('INSERT OR REPLACE INTO decisions VALUES (?,?,?,?,?,?)',
                        (snapshot['login'],snapshot['symbol'],snapshot['period'],run['id'],
                         snapshot['bars'][-1]['time'],encode(run['entry_decision'])))

    def record_ack(self, login, ack):
        ident = ack.get('id')
        if not isinstance(ident, int) or isinstance(ident, bool):
            self.archive.save('invalid_ack',str(login),ack,{'account':login})
            return
        with self.connect() as con:
            old=con.execute('SELECT data FROM acknowledgements WHERE account=? AND request=?',(login,ident)).fetchone()
            identity=f'{login}:{ident}'
            if old:self.archive.save('ack',identity,json.loads(old[0]),{'account':login},seed=True)
            self.archive.save('ack',identity,ack,{'account':login})
            if con.execute('SELECT 1 FROM intents WHERE account=? AND request=?', (login, ident)).fetchone():
                intent=json.loads(con.execute('SELECT data FROM intents WHERE account=? AND request=?',(login,ident)).fetchone()[0])
                self.archive.save('execution_latency',identity,{'ack':ack,'intent_utc':intent.get('recorded_utc'),
                    'broker_ack_utc':ack.get('utc'),'broker_ack_delay_seconds':
                    ack['utc']-intent['recorded_utc'] if isinstance(ack.get('utc'),(int,float)) else None},
                    {'account':login,'symbol':intent.get('symbol'),'experiment_id':intent.get('experiment_id')})
                con.execute('INSERT OR REPLACE INTO acknowledgements VALUES (?,?,?)', (login, ident, encode(ack)))

    def observe(self, snapshot):
        login, symbol = snapshot['login'], snapshot['symbol']
        self.archive.save('terminal_state',f'{login}:{symbol}',
            {k:snapshot.get(k) for k in ('connected','algo_enabled','halted','note','controls_revision')},
            {'account':login,'symbol':symbol,'period':snapshot.get('period')})
        with self.connect() as con:
            for p in snapshot.get('positions',[]):
                if not isinstance(p.get('profit'),(int,float)) or 'generated_utc' not in snapshot:continue
                con.execute('INSERT OR IGNORE INTO position_samples VALUES(?,?,?,?,?,?,?,?)',
                    (login,str(p['identifier']),snapshot['generated_utc'],p['profit'],p.get('swap'),
                     p.get('sl_risk_cash'),p.get('progress_r'),encode(p)))
            for d in snapshot.get('deals', []):
                if not isinstance(d.get('ticket'), int) or not isinstance(d.get('position_id'), int) or not math.isfinite(d['net']):
                    self.archive.save('invalid_deal',f'{login}:{symbol}',d,{'account':login,'symbol':symbol})
                    raise ValueError('Invalid deal observation')
                # Enrichment after installing the newer EA can fill old missing fields.
                old = con.execute('SELECT data FROM observations WHERE account=? AND ticket=?', (login, d['ticket'])).fetchone()
                merged = {**(json.loads(old[0]) if old else {}), **d}
                if old and not d.get('initial_risk'):
                    merged['initial_risk'] = json.loads(old[0]).get('initial_risk')
                identity=f"{login}:{d['ticket']}"
                if not old or json.loads(old[0])!=merged:
                    if old:self.archive.save('deal',identity,json.loads(old[0]),{'account':login,'symbol':symbol},seed=True)
                    self.archive.save('deal',identity,merged,{'account':login,'symbol':symbol})
                con.execute('INSERT OR REPLACE INTO observations VALUES (?,?,?,?)', (login, d['ticket'], symbol, encode(merged)))

    def outcomes(self, snapshot):
        login, symbol = snapshot['login'], snapshot['symbol']
        with self.connect() as con:
            rows = con.execute('SELECT data FROM observations WHERE account=? AND symbol=?', (login, symbol)).fetchall()
            sample_metrics={}
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='position_samples'").fetchone():
                sample_metrics={str(row[0]):row[1:] for row in con.execute(
                    'SELECT position,count(*),min(utc),max(utc),min(profit),max(profit),min(progress),max(progress) FROM position_samples WHERE account=? GROUP BY position',
                    (login,)).fetchall()}
            matches = con.execute('''SELECT i.data,a.data FROM intents i JOIN acknowledgements a
                ON i.account=a.account AND i.request=a.request WHERE i.account=? AND i.symbol=? AND i.period=?''',
                                  (login, symbol, snapshot['period'])).fetchall()
        intents = {}
        for raw, ack_raw in matches:
            ack = json.loads(ack_raw)
            context=json.loads(raw)
            if context.get('action')=='open' and ack.get('status') in ('executed', 'not_confirmed') and positive(ack.get('order')):
                intents[str(ack['order'])] = context
        groups = {}
        for row in rows:
            deal = json.loads(row[0]); groups.setdefault(str(deal['position_id']), []).append(deal)
        open_ids = {str(p['identifier']) for p in snapshot['positions']}
        result = {}
        for ident, deals in groups.items():
            outcome = position_outcome(login, symbol, sorted(deals, key=lambda d: (d.get('time', 0), d['ticket'])), open_ids, intents, snapshot['currency'])
            # Only an exact order/request link may attribute a result to this timeframe.
            linked_entries = len(outcome['entry_contexts'])
            entry_count = sum(d.get('entry') == 0 for d in deals)
            outcome['learning_eligible'] &= entry_count > 0 and linked_entries == entry_count
            if linked_entries != entry_count or not entry_count:
                outcome['evidence_problems'].append('entry_decision_link_unavailable')
            result[ident] = outcome
            contexts=outcome['entry_contexts']
            regimes={c.get('learning_regime') or c.get('decision',{}).get('learning_regime') for c in contexts}
            experiments={c.get('experiment_id') or c.get('decision',{}).get('experiment_id') for c in contexts}
            outcome['learning_regime']=next(iter(regimes)) if len(regimes)==1 else None
            outcome['experiment_id']=next(iter(experiments)) if len(experiments)==1 else None
            outcome['code_revisions']=sorted({c['code_revision'] for c in contexts if c.get('code_revision')})
            samples=sample_metrics.get(ident,(0,None,None,None,None,None,None))
            outcome['observed_path']={'samples':samples[0],'first_utc':samples[1],'last_utc':samples[2],
                'min_floating_profit':samples[3],'max_floating_profit':samples[4],
                'min_progress_r':samples[5],'max_progress_r':samples[6],
                'coverage':'observed snapshots only; not all market ticks'}
        return result

    def summary(self, snapshot):
        outcomes = list(self.outcomes(snapshot).values())
        with self.connect() as con:
            decisions = con.execute('SELECT count(*) FROM decisions WHERE account=? AND symbol=? AND period=?',
                                   (snapshot['login'],snapshot['symbol'],snapshot['period'])).fetchone()[0]
        return {'decisions_recorded':decisions,'positions_observed': len(outcomes), 'closed_complete': sum(o['closed_complete'] for o in outcomes),
                'learning_eligible': sum(o['learning_eligible'] for o in outcomes),
                'latest_outcomes': outcomes[-10:], 'database': str(self.path)}
