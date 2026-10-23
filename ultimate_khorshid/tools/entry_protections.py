"""Read-only entry guards computed from durable broker position outcomes.

No daily stop is cleared, no exit is delayed, and restarting cannot reset a lock.
Times stay in broker-server seconds, matching deal timestamps.
"""
from ultimate_khorshid.tools.exit_rules import finite

COOLDOWN_BARS = 1
STOP_WINDOW_BARS = 8
STOP_LOCK_BARS = 4
SYMBOL_STOP_LIMIT = 2
ACCOUNT_STOP_LIMIT = 3


def assess(snapshot, outcomes, global_scope=False):
    controls=snapshot.get('trading_controls',{})
    cooldown=controls.get('cooldown_bars',COOLDOWN_BARS)
    cluster=controls.get('stop_cluster_enabled',True)
    if not cooldown and not cluster:
        return {'allow_entry':True,'version':1,'blocked_until_server':None,
                'reason':'Cooldown and stop-cluster pause disabled by user','stop_count':0,
                'stop_limit':None,'clock':'broker_server'}
    period, offset = snapshot.get('period_seconds'), snapshot.get('broker_utc_offset_seconds')
    generated = snapshot.get('generated_utc')
    base = {'allow_entry': False, 'version': 1, 'blocked_until_server': None,
            'reason': 'Protection clock unavailable', 'stop_count': 0}
    if (not finite(period) or not 0 < period <= 86400 or not finite(offset) or abs(offset) > 14*3600
            or not finite(generated) or generated+offset <= 0):
        return base
    now = generated+offset
    rows = [o for o in outcomes.values()
            if o.get('account') == snapshot['login']
            and (global_scope or o.get('symbol') == snapshot['symbol'])
            and o.get('closed_complete') is True and finite(o.get('closed_time_server'))
            and 0 < o['closed_time_server'] <= now and finite(o.get('net'))]
    stops = [o for o in rows if o['net'] < 0 and 4 in o.get('exit_reasons', [])
             and o['closed_time_server'] >= now-controls.get('stop_window_bars',STOP_WINDOW_BARS)*period]
    # Deduplicate by account+position, including callers that merge symbol maps.
    stops = list({(o['account'], str(o['position_id'])): o for o in stops}.values())
    limit = controls.get('account_stop_limit',ACCOUNT_STOP_LIMIT) if global_scope else controls.get('symbol_stop_limit',SYMBOL_STOP_LIMIT)
    until, reason = 0., 'Entry protections clear'
    if not global_scope and rows:
        until = max(o['closed_time_server'] for o in rows)+cooldown*period
        reason = 'Cooldown after a completed position'
    if cluster and len(stops) >= limit:
        lock = max(o['closed_time_server'] for o in stops)+controls.get('stop_lock_bars',STOP_LOCK_BARS)*period
        if lock > until:
            until, reason = lock, 'Recent losing stop-loss cluster'
    return {**base, 'allow_entry': now >= until, 'blocked_until_server': until if now < until else None,
            'reason': reason if now < until else 'Entry protections clear', 'stop_count': len(stops),
            'stop_limit': limit, 'clock': 'broker_server', 'evaluated_server': now}


def constrain(plan, snapshot, outcomes):
    if plan.get('action') != 'open':
        return plan
    guard = assess(snapshot, outcomes)
    if not guard['allow_entry']:
        return {'status': 'entry_protection_pause', 'reason': guard['reason'], 'entry_protection': guard}
    return {**plan, 'entry_protection': guard}
