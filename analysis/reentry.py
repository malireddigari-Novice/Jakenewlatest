"""
Re-entry after a COOLING exit (handoff Priority 4) — pure, I/O-free.

The daily one-ENTER-per-side lock exists so noise can't churn a slot. But it must not permanently forbid
a legitimate return: a campaign that took profit or trailed off (COOLED) can reaccelerate the SAME side
later in the session, and passing on that reacceleration because "we already traded this today" leaves
convexity on the table. This module owns the two-part decision:

    1. was the exit a COOLING exit?   (re-eligible)  vs terminal (failure/reversal/distribution/stop)
    2. has the side genuinely REACCELERATED?         (fresh event, control re-seized, value ok, spot ok)

Only when BOTH hold — and the slot is under its per-session re-entry cap — is a re-entry authorized.
Until reacceleration confirms, a cooled slot sits in REACCELERATION_WATCH (visible, not tradeable).
Terminal exits are never re-eligible: re-buying a thesis that failed/reversed/distributed is the exact
mistake this guards against. This directs a re-entry; the candidate still passes every normal entry gate.
"""
import config


def is_cooling_exit(exit_category) -> bool:
    """A COOLING exit rested/realised the campaign (re-eligible); a terminal one invalidated it."""
    return exit_category in config.REENTRY_ELIGIBLE_CATEGORIES


def reaccel_confirmed(ev: dict) -> dict:
    """Is the cooled side genuinely reaccelerating (not merely un-dead)? Needs a FRESH abnormality, the
    same-side control re-seized, still-favourable value, positive premium acceleration, and spot
    confirming. ev keys: authorized(bool, from the absolute gate), abnormal(bool), control(0-1),
    accel(float), value_state(str), spot_confirms(bool). Returns {confirmed, reasons}."""
    reasons = []
    if not ev.get('authorized'):
        reasons.append('weak_absolute_signal')
    if not ev.get('abnormal'):
        reasons.append('no_fresh_abnormality')
    if (ev.get('control') or 0.0) < config.REENTRY_MIN_CONTROL:
        reasons.append('control_not_reseized')
    if (ev.get('accel') or 0.0) <= config.REENTRY_MIN_ACCEL:
        reasons.append('not_accelerating')
    if ev.get('value_state') in ('EXTENDED', 'MATURE'):
        reasons.append('value_' + str(ev.get('value_state')).lower())
    if not ev.get('spot_confirms'):
        reasons.append('spot_not_confirming')
    return {'confirmed': not reasons, 'reasons': reasons}


def can_reenter(slot_state: dict, exit_category: str, ev: dict) -> dict:
    """Authorize a re-entry on a slot that was already ENTERED (and exited) this session.
    slot_state: {'count': int, 'category': str} recorded at the cooling exit (None if never cooled).
    Returns {'allow', 'reason', 'watch'(bool), 'detail'}. `watch`=True means REACCELERATION_WATCH:
    eligible but reacceleration not yet confirmed (surface it, don't trade it)."""
    if not config.REENTRY_ENABLED:
        return {'allow': False, 'reason': 'reentry_disabled', 'watch': False}
    if not slot_state:
        return {'allow': False, 'reason': 'slot_not_cooled', 'watch': False}
    if not is_cooling_exit(exit_category or slot_state.get('category')):
        return {'allow': False, 'reason': 'terminal_exit_not_re_eligible', 'watch': False}
    if (slot_state.get('count') or 0) >= config.REENTRY_MAX_PER_SLOT:
        return {'allow': False, 'reason': 'reentry_cap_reached', 'watch': False}
    rc = reaccel_confirmed(ev or {})
    if not rc['confirmed']:
        return {'allow': False, 'reason': 'reaccel_not_confirmed', 'watch': True, 'detail': rc['reasons']}
    return {'allow': True, 'reason': 'reaccel_confirmed_after_cooling', 'watch': False, 'detail': rc}
