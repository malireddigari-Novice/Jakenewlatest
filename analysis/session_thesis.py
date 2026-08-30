"""
Intraday vs overnight session-thesis classification (handoff Priority 6) — pure, I/O-free.

A 0/1-DTE campaign carries an implicit horizon that the engine must make explicit at the close:

    INTRADAY  — an opening-drive / intraday-momentum thesis. It has no reason to survive the bell; the
                position is flat by EOD (paper flattens regardless) and the campaign memory does NOT
                carry. This is the DEFAULT for a late-session campaign absent positive evidence.
    OVERNIGHT — a durable directional accumulation whose thesis extends past the close. It may justify
                carrying the CAMPAIGN MEMORY forward (not the position), but ONLY with independent late-
                day confirmation: same-side control still held into the close, no distribution in
                progress, and value retained (not extended/matured out).

We classify the THESIS, not the position — the position is flattened at EOD either way. The label is
stamped on the serialized campaign so carry_forward / next-open inheritance treats an overnight thesis
as inherited context and an intraday one as spent.
"""
import config


def classify(ev: dict) -> dict:
    """Classify a campaign's session thesis at (or near) the close.
    ev keys: minutes_to_close(float), dte(int), control(0-1 same-side, late day), dist_prob(0-1),
    value_state(str), spot_confirms(bool). Returns {thesis, carry(bool), reasons}."""
    reasons = []
    if not config.SESSION_THESIS_ENABLED:
        return {'thesis': 'UNKNOWN', 'carry': False, 'reasons': ['disabled']}

    late_day = (ev.get('minutes_to_close') is None
                or ev.get('minutes_to_close') <= config.SESSION_THESIS_LATEDAY_MIN)
    if not late_day:
        # too early to call an overnight thesis — a mid-session read is intraday by construction.
        return {'thesis': 'INTRADAY', 'carry': False, 'reasons': ['not_late_day']}

    if (ev.get('control') or 0.0) < config.OVERNIGHT_MIN_CONTROL:
        reasons.append('control_not_held_into_close')
    if (ev.get('dist_prob') or 0.0) > config.OVERNIGHT_MAX_DIST_PROB:
        reasons.append('distribution_in_progress')
    if ev.get('value_state') in ('EXTENDED', 'MATURE'):
        reasons.append('value_' + str(ev.get('value_state')).lower())
    if not ev.get('spot_confirms'):
        reasons.append('spot_not_confirming_into_close')

    if reasons:
        return {'thesis': 'INTRADAY', 'carry': False, 'reasons': reasons}
    return {'thesis': 'OVERNIGHT', 'carry': True,
            'reasons': ['same_side_control_held', 'no_distribution', 'value_retained', 'spot_confirms']}
