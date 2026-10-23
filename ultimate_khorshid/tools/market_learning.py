"""Causal market descriptions and evidence-based, bounded strategy selection.

No broker calls, position sizing, generated Python, or model-weight updates.
Context belongs to entry time; closing-market conditions never replace it.
"""
import json
from contextlib import contextmanager
import math
from pathlib import Path
import sqlite3
from statistics import mean, median
import time

VERSION = 1
MIN_SAMPLES = 20
PAUSE_SAMPLES = 30


def describe(bars, utc=None, spread=None):
    if len(bars) < 20:
        return None
    recent = bars[-80:]
    for bar in recent:
        if any(type(bar.get(k)) not in (int, float) or not math.isfinite(bar[k])
               for k in ('time', 'open', 'high', 'low', 'close')):
            return None
        if (bar['low'] <= 0 or bar['high'] < max(bar['open'], bar['close'])
                or bar['low'] > min(bar['open'], bar['close'])):
            return None
    if any(a['time'] >= b['time'] for a, b in zip(recent, recent[1:])):
        return None
    closes = [b['close'] for b in recent]
    moves = [abs(b-a) for a, b in zip(closes[-20:], closes[-19:])]
    change = closes[-1]-closes[-20]
    efficiency = abs(change)/sum(moves) if sum(moves) else 0.
    trend = ('up' if change > 0 else 'down') if efficiency >= .35 else 'range'
    tr = [max(b['high']-b['low'], abs(b['high']-closes[max(i-1, 0)]),
              abs(b['low']-closes[max(i-1, 0)])) for i, b in enumerate(recent)]
    atr = mean(tr[-14:])
    reference = median(tr[:-14]) if len(tr) >= 40 else None
    ratio = atr/reference if reference and reference > 0 else None
    volatility = ('high' if ratio > 1.5 else 'low' if ratio < .7 else 'normal') if ratio else 'unknown'
    spread_ratio = spread/atr if type(spread) in (float, int) and math.isfinite(spread) and spread >= 0 and atr > 0 else None
    spread_band = ('wide' if spread_ratio > .15 else 'normal' if spread_ratio > .05 else 'tight') if spread_ratio is not None else 'unknown'
    session = f'utc_{int(utc)//21600%4}' if type(utc) in (int, float) and math.isfinite(utc) and utc > 0 else 'unknown'
    return {'version': VERSION, 'signal_bar': recent[-1]['time'], 'trend': trend,
            'volatility': volatility, 'session': session, 'spread_band': spread_band,
            'efficiency': round(efficiency, 6), 'atr': atr, 'volatility_ratio': ratio,
            'clock': 'UTC' if session != 'unknown' else 'unknown'}


def entry_context(outcome):
    entries = outcome.get('entry_contexts') or []
    if not entries:
        return None
    contexts = []
    directions = set()
    for entry in entries:
        if (entry.get('action') != 'open' or entry.get('direction') not in (-1, 1)
                or entry.get('strategy') != outcome.get('strategy')):
            return None
        directions.add(entry['direction'])
        context = (entry.get('decision') or {}).get('market_context')
        if not context:
            spread = entry.get('ask', 0)-entry.get('bid', 0)
            context = describe(entry.get('recent_closed_bars') or [], entry.get('recorded_utc'), spread)
        if (not context or context.get('version') != VERSION
                or context.get('trend') not in ('up','down','range')
                or context.get('volatility') not in ('high','low','normal','unknown')
                or context.get('session') not in ('utc_0','utc_1','utc_2','utc_3','unknown')
                or context.get('spread_band') not in ('wide','normal','tight','unknown')):
            return None
        contexts.append(context)
    keys = ('trend', 'volatility', 'session', 'spread_band')
    if len(directions) != 1 or any(any(c.get(k) != contexts[0].get(k) for k in keys) for c in contexts):
        return None
    return contexts[0], directions.pop()


class ContextModel:
    def __init__(self, path, account):
        self.path, self.account = Path(path), account
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS outcomes(
                account INTEGER, position TEXT, strategy TEXT, direction INTEGER,
                trend TEXT, bucket TEXT, reward REAL, net REAL, context TEXT, recorded REAL,
                PRIMARY KEY(account,position))''')

    @contextmanager
    def connect(self):
        con=sqlite3.connect(self.path, timeout=.1)
        try:
            with con:
                yield con
        finally:
            con.close()

    @staticmethod
    def bucket(context):
        return '|'.join(context.get(k, 'unknown') for k in ('trend','volatility','session','spread_band'))

    def observe(self, groups, open_ids=()):
        inserted = 0
        open_ids = {str(i) for i in open_ids}
        with self.connect() as con:
            for ident, outcome in groups.items():
                reward = outcome.get('normalized_reward')
                if (outcome.get('account') != self.account or str(ident) in open_ids
                        or outcome.get('learning_eligible') is not True or outcome.get('closed_complete') is not True
                        or type(reward) not in (int, float) or not math.isfinite(reward)):
                    continue
                linked = entry_context(outcome)
                if not linked:
                    continue
                context, direction = linked
                # Clipping bounds the influence of exceptional fills, not reported net P/L.
                result = con.execute('INSERT OR IGNORE INTO outcomes VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (self.account, str(ident), outcome['strategy'], direction, context['trend'], self.bucket(context),
                     max(-3., min(3., reward)), outcome['net'], json.dumps(context, allow_nan=False), time.time()))
                inserted += result.rowcount
        return inserted

    def assess(self, strategy, context, direction):
        with self.connect() as con:
            rows = con.execute('''SELECT reward FROM outcomes WHERE account=? AND strategy=?
                AND direction=? AND bucket=? ORDER BY recorded DESC LIMIT 100''',
                (self.account, strategy, direction, self.bucket(context))).fetchall()
            scope = 'full_context'
            if len(rows) < MIN_SAMPLES:
                rows = con.execute('''SELECT reward FROM outcomes WHERE account=? AND strategy=?
                    AND direction=? AND trend=? ORDER BY recorded DESC LIMIT 100''',
                    (self.account, strategy, direction, context['trend'])).fetchall()
                scope = 'trend_and_direction'
        values = [r[0] for r in rows]
        n = len(values)
        average = mean(values) if n else 0.
        se = math.sqrt(sum((v-average)**2 for v in values)/(n-1)/n) if n > 1 else None
        # This is a conservative operational heuristic, not an IID statistical proof.
        upper = average+1.96*se if se is not None else None
        pause = n >= PAUSE_SAMPLES and upper < 0 and mean(values[:20]) < 0
        adjustment = max(-.5, min(.5, average*n/(n+30))) if n >= MIN_SAMPLES else 0.
        return {'samples': n, 'scope': scope, 'mean_r': average, 'upper_mean_r_heuristic': upper,
                'adjustment': adjustment, 'paused': pause,
                'reason': 'persistent_negative_context_evidence' if pause else
                          'insufficient_context_evidence' if n < MIN_SAMPLES else 'context_adjustment'}

    @staticmethod
    def summary(path, account):
        path = Path(path)
        if not path.is_file():
            return {'version':VERSION, 'verified_context_results':0, 'minimum_samples':MIN_SAMPLES}
        con=sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=3)
        try:
            count = con.execute('SELECT count(*) FROM outcomes WHERE account=?', (account,)).fetchone()[0]
            rows = con.execute('''SELECT strategy,trend,direction,count(*),avg(reward)
                FROM outcomes WHERE account=? GROUP BY strategy,trend,direction ORDER BY count(*) DESC''', (account,)).fetchall()
        finally:
            con.close()
        return {'version':VERSION, 'verified_context_results':count, 'minimum_samples':MIN_SAMPLES,
                'buckets':[dict(zip(('strategy','trend','direction','samples','mean_r'), row)) for row in rows],
                'note':'Entry-time verified demo evidence; sparse contexts retain baseline selection. No volume increases.'}
