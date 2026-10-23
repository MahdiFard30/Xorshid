"""Pure versioned rules shared by live planning and causal paper execution.

The native equivalents in RestartPolicy.mqh are checked against these in tests.
"""
import math

POLICY_VERSION = 2
STOP_ATR = 1.0
SIZING_SCALE = STOP_ATR / 2.0
QUICK_TARGET_R = 1.0
STAGED_TARGET_R = 2.0
MAX_HOLD_BARS = 24


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def exit_action(progress, strong, consumed, net, buffer):
    if not all(finite(x) for x in (progress, net, buffer)) or buffer < 0 or net <= buffer:
        return 0
    if not strong:
        return 1 if progress >= QUICK_TARGET_R else 0
    if progress >= STAGED_TARGET_R:
        return 1
    return 2 if progress >= 1 and not consumed else 0


def trailing_stop(side, entry, price, distance, old, tick, minimum):
    if (side not in (-1, 1) or not all(finite(x) for x in (entry, price, distance, old, tick, minimum))
            or min(entry, price, distance, tick) <= 0 or old < 0 or minimum < 0
            or side * (price-entry) < distance):
        return 0.0
    wanted = price-side*distance*.5
    if side*(wanted-entry) < 0:
        wanted = entry
    wanted = (math.floor(wanted/tick) if side > 0 else math.ceil(wanted/tick))*tick
    if side*(price-wanted) < minimum or (old > 0 and side*(wanted-old) <= tick*.5):
        return 0.0
    return wanted


def failed_thesis(signal, side, held, progress):
    return finite(progress) and progress <= -.5 and held >= 2 and signal != side


def outcome_policy(outcome):
    contexts = outcome.get('entry_contexts', [])
    versions = {c.get('decision', {}).get('plan', {}).get('exit_policy_version') for c in contexts}
    return next(iter(versions)) if len(versions) == 1 else None
