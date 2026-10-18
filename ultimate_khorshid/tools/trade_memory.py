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
    return {'position_id': ident, 'account': login, 'symbol': symbol,
            'strategy': next(iter(strategies)) if len(strategies) == 1 else 'unknown',
            'has_exit': bool(exits), 'closed_complete': not any(p in problems for p in (
                'position_still_open', 'missing_entry_exit_or_unsupported_reversal',
                'volume_history_unavailable', 'entry_exit_volume_mismatch')),
            'net': net, **totals, 'risk_cash': risk if positive(risk) else None,
            'normalized_reward': normalized, 'normalization': 'net / sum of entry-fill SL risk estimates; excludes guaranteed execution',
            'learning_eligible': normalized is not None, 'evidence_problems': sorted(set(problems)),
            'entry_contexts': linked, 'exit_reasons': [d.get('reason') for d in exits],
            'deal_tickets': [d['ticket'] for d in deals]}


class TradeMemory:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
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
            ''')

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=10)
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
        with self.connect() as con:
            con.execute('INSERT INTO intents VALUES (?,?,?,?,?)',
                        (snapshot['login'], ident, snapshot['symbol'], snapshot['period'], encode(context)))

    def record_decision(self, run, snapshot):
        with self.connect() as con:
            con.execute('INSERT OR IGNORE INTO decisions VALUES (?,?,?,?,?,?)',
                        (snapshot['login'],snapshot['symbol'],snapshot['period'],run['id'],
                         snapshot['bars'][-1]['time'],encode(run['entry_decision'])))

    def record_ack(self, login, ack):
        ident = ack.get('id')
        if not isinstance(ident, int) or isinstance(ident, bool):
            return
        with self.connect() as con:
            if con.execute('SELECT 1 FROM intents WHERE account=? AND request=?', (login, ident)).fetchone():
                con.execute('INSERT OR REPLACE INTO acknowledgements VALUES (?,?,?)', (login, ident, encode(ack)))

    def observe(self, snapshot):
        login, symbol = snapshot['login'], snapshot['symbol']
        with self.connect() as con:
            for d in snapshot.get('deals', []):
                if not isinstance(d.get('ticket'), int) or not isinstance(d.get('position_id'), int) or not math.isfinite(d['net']):
                    raise ValueError('Invalid deal observation')
                # Enrichment after installing the newer EA can fill old missing fields.
                old = con.execute('SELECT data FROM observations WHERE account=? AND ticket=?', (login, d['ticket'])).fetchone()
                merged = {**(json.loads(old[0]) if old else {}), **d}
                if old and not d.get('initial_risk'):
                    merged['initial_risk'] = json.loads(old[0]).get('initial_risk')
                con.execute('INSERT OR REPLACE INTO observations VALUES (?,?,?,?)', (login, d['ticket'], symbol, encode(merged)))

    def outcomes(self, snapshot):
        login, symbol = snapshot['login'], snapshot['symbol']
        with self.connect() as con:
            rows = con.execute('SELECT data FROM observations WHERE account=? AND symbol=?', (login, symbol)).fetchall()
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
        return result

    def summary(self, snapshot):
        outcomes = list(self.outcomes(snapshot).values())
        with self.connect() as con:
            decisions = con.execute('SELECT count(*) FROM decisions WHERE account=? AND symbol=? AND period=?',
                                   (snapshot['login'],snapshot['symbol'],snapshot['period'])).fetchone()[0]
        return {'decisions_recorded':decisions,'positions_observed': len(outcomes), 'closed_complete': sum(o['closed_complete'] for o in outcomes),
                'learning_eligible': sum(o['learning_eligible'] for o in outcomes),
                'latest_outcomes': outcomes[-10:], 'database': str(self.path)}
