"""
Expiry-aware value + cross-expiry direction + overnight carry (spec §36, addendum #6/#8) — pure.

Three related reads that all treat *expiry* as an economic variable, not a fixed nearest-contract:

  • late_day_0dte_value (§36): a 0DTE at 10:00 and at 15:00 are different instruments.
        value = campaign_strength × activation × remaining_convexity − θ·theta_risk
    theta_risk ramps from 0 at LATE0DTE_START_MIN minutes after the open to ~1 near the close, so the
    burden of proof on a late 0DTE rises sharply. Non-0DTE contracts are unpenalised (value passthrough).

  • cross_expiry_direction (#8): if forward expiries' controlling side AGREES with the traded side the
    thesis is confirmed (small bonus); if they DISAGREE it is a conflict (penalty). Turns the existing
    shadow multi-expiry scan into a real directional input.

  • overnight_carry (#6): a restored campaign is not a blank slate at the open — classify it into
    CONTINUATION / OPENING_MONETIZATION / ROLL_FORWARD / REVERSAL from the opening read so the manager
    knows what it is looking at before discovering anything new.
"""
import config


def late_day_0dte_value(dte, minutes_since_open, *, strength, activation, remaining_convexity,
                        session_minutes: float = 390.0) -> dict:
    """LateDay0DTEValue with a time-of-day theta ramp. Only 0DTE (dte<=0) is penalised.
    strength / activation / remaining_convexity are 0..1. session_minutes is 210 on an early-close day
    (the ramp must reach 1 at the ACTUAL close). Returns {value, theta_risk, is_0dte}."""
    is_0dte = (dte is not None and dte <= 0)
    if not is_0dte:
        base = max(0.0, min(1.0, strength)) * max(0.0, min(1.0, activation)) * max(0.0, min(1.0, remaining_convexity))
        return {'value': round(base, 3), 'theta_risk': 0.0, 'is_0dte': False}
    span = max(1.0, (session_minutes - config.LATE0DTE_START_MIN))  # open→close minutes past the ramp start
    theta_risk = max(0.0, min(1.0, (minutes_since_open - config.LATE0DTE_START_MIN) / span))
    core = max(0.0, min(1.0, strength)) * max(0.0, min(1.0, activation)) * max(0.0, min(1.0, remaining_convexity))
    value = core - config.LATE0DTE_THETA_WEIGHT * theta_risk
    return {'value': round(value, 3), 'theta_risk': round(theta_risk, 3), 'is_0dte': True}


def late_day_0dte_ok(val) -> tuple:
    """Gate helper: a 0DTE below LATE0DTE_MIN_VALUE is a late lottery ticket — veto. Non-0DTE always OK."""
    if not val.get('is_0dte'):
        return True, 'not-0dte'
    if val['value'] < config.LATE0DTE_MIN_VALUE:
        return False, f"late-0DTE value {val['value']:.2f} < {config.LATE0DTE_MIN_VALUE} (theta_risk={val['theta_risk']:.2f})"
    return True, f"0DTE value {val['value']:.2f} ok"


def cross_expiry_direction(traded_side, expiry_rows) -> dict:
    """Do the FORWARD expiries agree with the traded side? expiry_rows: the summarize() 'rows'
    (each {key, share, side}). Uses the meaningful forward rows (share >= 0.05). Returns
    {'verdict': CONFIRM/CONFLICT/NEUTRAL, 'mult', 'bonus', 'reason'}."""
    fwd = [r for r in (expiry_rows or []) if (r.get('share') or 0) >= 0.05 and r.get('side')]
    if len(fwd) < 2:
        return {'verdict': 'NEUTRAL', 'mult': 1.0, 'bonus': 0.0, 'reason': 'insufficient forward structure'}
    agree = sum(1 for r in fwd if r['side'] == traded_side)
    disagree = sum(1 for r in fwd if r['side'] != traded_side)
    if agree > disagree:
        return {'verdict': 'CONFIRM', 'mult': 1.0, 'bonus': config.XEXP_CONFIRM_BONUS,
                'reason': f'{agree}/{len(fwd)} forward expiries also {traded_side}'}
    if disagree > agree:
        return {'verdict': 'CONFLICT', 'mult': config.XEXP_CONFLICT_PENALTY, 'bonus': 0.0,
                'reason': f'{disagree}/{len(fwd)} forward expiries oppose {traded_side}'}
    return {'verdict': 'NEUTRAL', 'mult': 1.0, 'bonus': 0.0, 'reason': 'forward expiries split'}


def overnight_carry(campaign, opening_side, opening_control, opening_rel_premium) -> str:
    """Classify a restored overnight campaign from the opening read (addendum #6).
    campaign: the inherited campaign dict (has 'side'). opening_* : this morning's first reads."""
    side = campaign.get('side')
    if opening_side and opening_side != side and (opening_control or 0) >= 0.6:
        return 'REVERSAL'                       # opposite side controls the open
    if (opening_rel_premium or 1.0) < 0.7 and opening_side == side:
        return 'OPENING_MONETIZATION'           # same side but premium gapped down — likely selling into the open
    if opening_side == side and (opening_control or 0) >= 0.55:
        return 'CONTINUATION'                   # same-side control persists overnight
    return 'ROLL_FORWARD'                       # neither clearly continues nor reverses — likely re-expressed
