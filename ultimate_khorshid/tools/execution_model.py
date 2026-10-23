"""Causal bid-OHLC execution approximation for screening and forward paper.

SL-first ordering, pessimistic intrabar trailing, proxy costs and fractional
volumes are explicit assumptions. This is not a tick/broker-exact simulator.
"""
from ultimate_khorshid.tools.exit_rules import (
    POLICY_VERSION, STOP_ATR, QUICK_TARGET_R, STAGED_TARGET_R, MAX_HOLD_BARS,
    failed_thesis, trailing_stop, finite,
)
from ultimate_khorshid.tools.entry_protections import assess


def new_book(equity=1.0):
    return {'equity': equity, 'peak_equity': equity, 'drawdown_pct': 0.0,
            'closed': 0, 'wins': 0, 'net_r': 0.0, 'gains_r': 0.0, 'losses_r': 0.0,
            'peak_r': 0.0, 'drawdown_r': 0.0, 'position': None,
            'exit_policy_version': POLICY_VERSION, 'recent_closes': []}


def step(book, bar, signal, atr, point, entry_ok=True, cost_multiplier=1.0,
         risk_fraction=.0025, profile=None, allow_entry=True, force_close=False, stop_atr=STOP_ATR):
    """One new closed candle, with the signal/ATR known BEFORE its open.

    Staged profiles must be timestamped before entry; unknown historical news
    uses the quick profile. A close never re-enters on the same candle.
    """
    if not finite(point) or point <= 0 or not finite(cost_multiplier) or cost_multiplier <= 0:
        raise ValueError('Positive finite point and cost multiplier required')
    if not finite(risk_fraction) or not 0 < risk_fraction <= .0025:
        raise ValueError('Paper risk cannot exceed the live per-entry ceiling')
    if not finite(stop_atr) or not .5<=stop_atr<=4:
        raise ValueError('Offline stop hypothesis must be between 0.5 and 4 ATR')
    parameters=book.setdefault('simulation_parameters',{'stop_atr':stop_atr})
    if parameters!={'stop_atr':stop_atr}:
        raise ValueError('Cannot change stop hypothesis inside an existing paper book')
    for key, value in new_book(book.get('equity', 1.0)).items():
        book.setdefault(key, value)
    if book['exit_policy_version'] != POLICY_VERSION:
        raise ValueError('Paper book policy mismatch; start a versioned book')
    spread = max(bar['spread']*point, 2*point)*cost_multiplier
    slip = 2*point*cost_multiplier
    events = []
    p = book.get('position')
    occupied = p is not None

    def mark_drawdown(price):
        if p is None:
            return
        days = max(0, (bar['time']-p['time'])/86400)
        reward = p['remaining']*(p['side']*(price-p['entry'])/p['distance']
                                 - .10*cost_multiplier-.02*cost_multiplier*days)
        marked = book['equity']+p['risk_cash']*reward
        book['drawdown_pct'] = max(book['drawdown_pct'], 100*(book['peak_equity']-marked)/book['peak_equity'])
        book['drawdown_r'] = max(book['drawdown_r'], book['peak_r']-(book['net_r']+p['realized_r']+reward))

    def realize(price, fraction, reason):
        nonlocal p
        fraction = min(p['remaining'], fraction)
        days = max(0, (bar['time']-p['time'])/86400)
        fill = price-p['side']*slip
        reward = fraction*(p['side']*(fill-p['entry'])/p['distance']
                           - .10*cost_multiplier-.02*cost_multiplier*days)
        net = p['risk_cash']*reward
        p['remaining'] = max(0.0, p['remaining']-fraction)
        p['realized_r'] += reward
        book['equity'] = max(0., book['equity']+net)
        book['peak_equity'] = max(book['peak_equity'], book['equity'])
        book['drawdown_pct'] = max(book['drawdown_pct'], 100*(book['peak_equity']-book['equity'])/book['peak_equity'])
        event = {'kind': 'partial' if p['remaining'] > 1e-9 else 'close',
                 'reason': reason, 'bar': bar['time'], 'entry_bar': p['time'],
                 'price': fill, 'fraction': fraction, 'leg_r': reward, 'net': net,
                 'exit_policy_version': POLICY_VERSION}
        if p['remaining'] <= 1e-9:
            total = p['realized_r']
            event['r'] = total
            event['net_total'] = p['risk_cash']*total
            book['closed'] += 1; book['wins'] += int(total > 0)
            book['net_r'] += total
            book['gains_r'] += max(0., total); book['losses_r'] += max(0., -total)
            book['peak_r'] = max(book['peak_r'], book['net_r'])
            book['drawdown_r'] = max(book['drawdown_r'], book['peak_r']-book['net_r'])
            book['last_close'] = {'reason': reason, 'reward_r': total, 'bar': bar['time']}
            period = bar.get('period_seconds', 0)
            book['recent_closes'].append({'account': 1, 'symbol': 'paper', 'position_id': p['time'],
                'closed_complete': True, 'closed_time_server': bar['time']+period,
                'net': total, 'exit_reasons': [4] if reason in ('stop','gap_stop','ambiguous_trailing_stop') else []})
            book['recent_closes'] = book['recent_closes'][-32:]
            p = None; book['position'] = None
        events.append(event)

    def hit(level, low, high, side, favorable=False):
        return (high >= level if side > 0 else low <= level) if favorable else (low <= level if side > 0 else high >= level)

    if p and force_close:
        realize(bar['close']+(spread if p['side'] < 0 else 0), p['remaining'], 'end_of_test')
        return events
    if p:
        p['bars'] += 1
        op = bar['open']+(spread if p['side'] < 0 else 0)
        # A gap through SL precedes the strategy's next-bar exit request.
        if p['side']*(op-p['stop']) <= 0:
            realize(op, p['remaining'], 'gap_stop')
        elif (signal == -p['side'] or p['bars'] >= MAX_HOLD_BARS
              or failed_thesis(signal, p['side'], p['bars'], p['side']*(op-p['entry'])/p['distance'])):
            realize(op, p['remaining'], 'opposite_signal_failed_thesis_or_timeout')
    period = bar.get('period_seconds')
    protection_clear = (assess({'login': 1, 'symbol': 'paper', 'generated_utc': bar['time'],
        'broker_utc_offset_seconds': 0, 'period_seconds': period},
        {str(i): row for i,row in enumerate(book['recent_closes'])})['allow_entry'] if period else True)
    if p is None and not occupied and protection_clear and allow_entry and entry_ok and signal in (-1, 1) and finite(atr) and atr > point*10:
        distance = stop_atr*atr
        if spread <= distance*.1:
            details = profile if isinstance(profile, dict) else {}
            strong = (details.get('mode') == 'staged' and finite(details.get('known_at_server'))
                      and details['known_at_server'] <= bar['time']
                      and finite(details.get('expires_server'))
                      and 30 <= details['expires_server']-bar['time'] <= 1800)
            entry = bar['open']+(spread if signal > 0 else 0)+signal*slip
            target_r = STAGED_TARGET_R if strong else QUICK_TARGET_R
            p = {'side': signal, 'entry': entry, 'distance': distance, 'stop': entry-signal*distance,
                 'target': entry+signal*target_r*distance, 'time': bar['time'], 'bars': 0,
                 'risk_cash': book['equity']*risk_fraction, 'remaining': 1.0, 'realized_r': 0.0,
                 'strong': strong, 'expiry': details.get('expires_server', 0) if strong else 0,
                 'partial_consumed': False, 'exit_policy_version': POLICY_VERSION}
            book['position'] = p
            events.append({'kind': 'open', 'bar': bar['time'], 'entry': entry,
                           'stop': p['stop'], 'target': p['target'], 'profile': 'staged' if strong else 'quick',
                           'exit_policy_version': POLICY_VERSION})
    if p is None:
        return events
    low, high, op = (bar[k]+(spread if p['side'] < 0 else 0) for k in ('low', 'high', 'open'))
    # Pessimistic: pre-existing stop is tested before any favorable excursion.
    if hit(p['stop'], low, high, p['side']):
        px = min(op, p['stop']) if p['side'] > 0 else max(op, p['stop'])
        mark_drawdown(px-p['side']*slip)
        realize(px, p['remaining'], 'stop')
        return events
    mark_drawdown(low if p['side'] > 0 else high)
    strong = p['strong'] and bar['time'] < p['expiry']
    # Expiry inside the candle is ambiguous: reduce to the quick profile now.
    if strong and bar.get('period_seconds') and bar['time']+bar['period_seconds'] > p['expiry']:
        strong = False
    if not strong:
        target = p['entry']+p['side']*QUICK_TARGET_R*p['distance']
        if hit(target, low, high, p['side'], True):
            realize(target, p['remaining'], 'quick_target')
        return events
    first = p['entry']+p['side']*p['distance']
    if not p['partial_consumed'] and hit(first, low, high, p['side'], True):
        p['partial_consumed'] = True
        realize(first, .5, 'first_target')
    if p is None:
        return events
    # The broker TP caps the excursion: never trail using a price beyond TP.
    best = min(high, p['target']) if p['side'] > 0 else max(low, p['target'])
    new_stop = trailing_stop(p['side'], p['entry'], best, p['distance'], p['stop'], point, point)
    if new_stop:
        p['stop'] = new_stop
        if hit(new_stop, low, high, p['side']):
            realize(new_stop, p['remaining'], 'ambiguous_trailing_stop')
            return events
    if hit(p['target'], low, high, p['side'], True):
        realize(p['target'], p['remaining'], 'final_target')
    return events


def metrics(book, initial=1.0):
    losses, gains = book['losses_r'], book['gains_r']
    return {'trades': book['closed'], 'return_pct': round((book['equity']/initial-1)*100, 5),
            'drawdown_pct': round(book['drawdown_pct'], 5),
            'profit_factor': round(gains/losses, 4) if losses else (999. if gains else 0.),
            'win_rate': round(book['wins']/book['closed'], 4) if book['closed'] else 0.,
            'net_r': round(book['net_r'], 6), 'open_positions': int(book['position'] is not None),
            'exit_policy_version': POLICY_VERSION}
