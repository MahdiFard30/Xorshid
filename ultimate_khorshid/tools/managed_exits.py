"""Bounded demo exit profiles. News confirmation is evidence, not a forecast."""
import math
from ultimate_khorshid.tools.exit_rules import (
    POLICY_VERSION, STOP_ATR, SIZING_SCALE, QUICK_TARGET_R, STAGED_TARGET_R,
)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def opportunity(analysis, direction, now, period_seconds=900):
    """Require recent original release numbers AND a complete price reaction.

    A bounded tilt redistributes the existing budget; it never raises a cap.
    Expiry is recorded at entry and can never be extended for that position.
    """
    weak = {'mode': 'quick', 'weight_multiplier': 1.0, 'expires_utc': 0,
            'reason': 'No fresh corroborated continuation evidence'}
    if isinstance(analysis,dict) and analysis.get('execution_effects_enabled') is False:
        return {**weak,'reason':'News is report-only pending an independent comparison'}
    if (not isinstance(analysis, dict) or type(direction) is not int or direction not in (-1, 1)
            or not finite(now) or not finite(period_seconds) or period_seconds <= 0
            or analysis.get('version') != 1
            or analysis.get('release_data_status') != 'fresh'
            or analysis.get('conflicting_events')
            or analysis.get('confirmed_direction') != direction
            or not isinstance(analysis.get('schedule'), dict)
            or analysis['schedule'].get('allow_entry') is not True
            or not finite(analysis.get('updated_utc'))
            or not -5 <= now - analysis['updated_utc'] <= 15):
        return weak
    evidence = analysis.get('evidence')
    if not isinstance(evidence, list) or len(evidence) > 10:
        return weak
    expiries = []
    for event in evidence:
        if not isinstance(event, dict) or not isinstance(event.get('market_reaction'), dict):
            continue
        reaction = event.get('market_reaction', {})
        utc, observed = event.get('utc'), event.get('observed_utc')
        closed = reaction.get('last_closed_bar_utc')
        if (event.get('revision') == 0
                and event.get('interpretation') == 'provider_hypothesis_matches_observed_price'
                and event.get('potential_symbol_direction') == direction
                and finite(event.get('actual')) and finite(event.get('forecast'))
                and event['actual'] != event['forecast']
                and finite(utc) and 0 <= now - utc <= 3600
                and finite(observed) and -5 <= now - observed <= 300
                and reaction.get('status') == 'observed' and reaction.get('direction') == direction
                and finite(reaction.get('change_atr')) and abs(reaction['change_atr']) >= .25
                and reaction['change_atr'] * direction > 0
                and finite(closed) and utc < closed <= now
                and now - closed <= min(1800, period_seconds * 2)):
            expiries.append(min(utc + 3600, now + 1800))
    expiry = max(expiries, default=0)
    if expiry - now < 120:
        return weak
    return {'mode': 'staged', 'weight_multiplier': 1.5, 'expires_utc': expiry,
            'reason': 'Recent release hypothesis agrees with completed price reaction; bounded tilt'}


def entry_profile(plan, snapshot, analysis, now):
    if plan.get('action') != 'open':
        return plan
    fraction = plan.get('risk_fraction')
    if not finite(fraction) or fraction <= 0:
        return {'status': 'waiting_for_portfolio_allocation', 'reason': 'Missing sizing evidence'}
    evidence = opportunity(analysis, plan['direction'], now, snapshot.get('period_seconds', 900))
    return {**plan, 'reference_risk_fraction': fraction,
            'risk_fraction': math.floor(fraction * SIZING_SCALE * 1e10) / 1e10,
            'stop_atr': STOP_ATR, 'target_r': STAGED_TARGET_R if evidence['mode'] == 'staged' else QUICK_TARGET_R,
            'exit_profile': evidence['mode'], 'thesis_expires_utc': evidence['expires_utc'],
            'exit_policy_version': POLICY_VERSION}
