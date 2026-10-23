"""Pure demo entry/exit policy. Broker-side risk limits remain authoritative."""
from ultimate_khorshid.tools.exit_rules import failed_thesis, MAX_HOLD_BARS
import math


def first_positive_exit(snapshot):
    """Close on positive estimated position P/L after observed and reserved costs.

    Floating profit already uses the executable side of the spread. Exit fees
    are estimated from entry charges. Live swap, when absent from the snapshot,
    remains explicitly unknown; this is not guaranteed final net profit.
    """
    def finite(x):return type(x) in (int,float) and math.isfinite(x)
    if (snapshot.get('demo') is not True or snapshot.get('algo_enabled') is not True
            or not finite(snapshot.get('tick_age_seconds')) or not 0<=snapshot['tick_age_seconds']<=2):
        return None
    details=[]
    for p in snapshot.get('positions',[]):
        if not str(p.get('comment','')).startswith('KH:') or not finite(p.get('profit')):continue
        rows=[d for d in snapshot.get('deals',[]) if d.get('position_id')==p.get('identifier')]
        if not rows or not any(d.get('entry')==0 for d in rows):continue
        if any(d.get('entry') not in (0,1) or not all(finite(d.get(k)) for k in
                ('volume','profit','commission','swap','fee')) or d['volume']<=0 for d in rows):continue
        entries=[d for d in rows if d['entry']==0]
        volume=sum(d['volume'] for d in entries)
        remaining=volume-sum(d['volume'] for d in rows if d['entry']==1)
        if remaining<=0:continue
        # Positive rebates are never assumed to recur on exit.
        reserve=sum(max(0,-d['commission'])+max(0,-d['fee']) for d in entries)*remaining/volume
        observed=sum(sum(d[k] for k in ('profit','commission','swap','fee')) for d in rows)
        swap=p.get('swap')
        estimate=p['profit']+observed+(swap if finite(swap) else 0)-reserve
        if estimate<=0:continue
        details.append({'ticket':p['ticket'],'position_id':p['identifier'],
            'reason':'first_positive_estimated_net','floating_profit':p['profit'],
            'observed_deal_net':observed,'estimated_exit_charges':reserve,
            'live_swap':swap if finite(swap) else None,'live_swap_available':finite(swap),
            'estimated_net':estimate,'final_net_guaranteed':False})
    return {'action':'close_tickets','tickets':[d['ticket'] for d in details],'exit_details':details,
            'reason':'First positive estimated net after observed costs and estimated exit charges'} if details else None

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
    controls=snapshot.get('trading_controls',{})
    max_hold=controls.get('max_hold_bars',MAX_HOLD_BARS)
    positions = snapshot['positions']
    exits = []
    exit_details = []
    for position in positions:
        strategy = position.get('comment', '')
        strategy = strategy[3:] if strategy.startswith('KH:') else ''
        direction = signals.get(strategy, [0])[-1]
        # A failed entry thesis exits on a completed candle, before the full SL.
        # Sparse crossover signals alone do not trigger an immediate exit.
        progress = position.get('progress_r')
        failed = failed_thesis(direction, position['direction'], position['bars_held'], progress)
        if direction == -position['direction'] or position['bars_held'] >= max_hold or failed:
            exits.append(position['ticket'])
            exit_details.append({'ticket':position['ticket'],'strategy':strategy,'signal':direction,
                'progress_r':progress,'bars_held':position['bars_held'],
                'reason':'opposite_signal' if direction==-position['direction'] else 'holding_timeout'
                         if position['bars_held']>=max_hold else 'failed_thesis'})
    if exits:
        return {'action': 'close_tickets', 'tickets': exits, 'exit_details':exit_details,
                'reason': 'Opposite signal, failed thesis at half-risk, or holding timeout'}
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
    if atr <= 0 or not snapshot['ask'] >= snapshot['bid'] > 0 or snapshot['ask']-snapshot['bid'] > atr*controls.get('spread_atr_fraction',.1):
        return {'status': 'spread_too_large', 'reason': 'Spread exceeds entry limit'}
    return {'action': 'open', 'direction': direction, 'strategy': chosen, 'reason': 'Fresh entry signal; executor checks shared risk budget'}
