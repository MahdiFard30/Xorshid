"""Pure demo entry/exit policy. Broker-side risk limits remain authoritative."""

def weekly_gate(plan, snapshot):
    """Pause entry only; the EA handles timed liquidation without a worker."""
    if plan.get('action') != 'open':
        return plan
    if 'weekly_schedule_known' in snapshot and snapshot['weekly_schedule_known'] is not True:
        return {'status': 'waiting_for_trading_schedule', 'reason': 'Broker session schedule unavailable; entries paused'}
    if snapshot.get('weekly_close_paused') is True:
        return {'status': 'weekly_close_pause', 'reason': 'Weekly close: entries paused; executor handles robot exits'}
    return plan

def decision(snapshot, signals, atr, chosen):
    positions = snapshot['positions']
    exits = []
    for position in positions:
        strategy = position.get('comment', '')
        strategy = strategy[3:] if strategy.startswith('KH:') else ''
        direction = signals.get(strategy, [0])[-1]
        if direction == -position['direction'] or position['bars_held'] >= 24:
            exits.append(position['ticket'])
    if exits:
        return {'action': 'close_tickets', 'tickets': exits, 'reason': 'Exit signal for selected positions'}
    if not snapshot['algo_enabled']:
        return {'status': 'algo_disabled', 'reason': 'Enable Algo Trading'}
    if not 0 <= snapshot['tick_age_seconds'] <= 120:
        return {'status': 'market_closed_or_stale_quote', 'reason': 'No fresh quote'}
    if snapshot['blocking_positions'] or snapshot['total_orders']:
        return {'status': 'other_account_exposure', 'reason': 'Other exposure blocks entry'}
    if len(positions) >= snapshot['max_positions']:
        return {'status': 'managing_demo_position', 'reason': 'Position limit reached; monitoring exits'}
    if not 0 <= snapshot['bar_age_seconds'] <= snapshot['entry_window_seconds']:
        return {'status': 'waiting_for_next_bar', 'reason': 'Entry window passed; no late order sent'}
    direction = signals.get(chosen, [0])[-1] if chosen else 0
    if not direction:
        return {'status': 'waiting_for_entry_signal', 'reason': 'No entry signal on the latest closed candle'}
    if any(p['direction'] != direction for p in positions):
        return {'status': 'managing_demo_position', 'reason': 'Opposite entry blocked while position remains open'}
    if atr <= 0 or not snapshot['ask'] > snapshot['bid'] > 0 or snapshot['ask']-snapshot['bid'] > atr*.2:
        return {'status': 'spread_too_large', 'reason': 'Spread exceeds entry limit'}
    return {'action': 'open', 'direction': direction, 'strategy': chosen, 'reason': 'Fresh entry signal; executor checks shared risk budget'}
