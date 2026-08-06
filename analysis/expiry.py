"""
Multi-expiration structure (spec §8-9, §24-25, §28) — pure, I/O-free functions.

Institutions express a thesis across expirations, not just the nearest one: 0DTE urgency, a
current-week Friday forward position, or both at once. Collapsing every expiration into one
ticker-level pool (as the base engine does) hides that structure — e.g. NVDA 0DTE puts while
Friday calls build. This module takes per-expiry side masses and derives the expiry-level view:
per-expiry share and controlling side, the near→forward migration of capital over time, and a
structural classification. The engine supplies the masses (from `mass.compute_masses` run per
expiry) and the prior forward-share for the migration slope; nothing here does any I/O.

Phase 3 is SHADOW: the engine logs this view but still trades the nearest expiry. Turning it into
an entry input is a later step, gated behind its own flag once validated.
"""
import config


def control_side(masses: dict):
    """(side, strength 0-1) of a single expiry's fresh mass. None side when there is no mass."""
    cm = masses.get('call_mass', 0.0) or 0.0
    pm = masses.get('put_mass', 0.0) or 0.0
    tot = cm + pm
    if tot <= 0:
        return None, 0.0
    return ('CALL', cm / tot) if cm >= pm else ('PUT', pm / tot)


def expiry_rows(by_expiry: dict, dte_by: dict = None):
    """[{key, dte, mass, share, side, control, fresh}] sorted near→forward, plus the total mass.
    `by_expiry`: {expiry_key: masses_dict}; `dte_by`: {expiry_key: days_to_expiry}."""
    dte_by = dte_by or {}
    total = sum((m.get('call_mass', 0.0) or 0.0) + (m.get('put_mass', 0.0) or 0.0)
                for m in by_expiry.values()) or config.WAVE_EPS
    rows = []
    for k, m in by_expiry.items():
        mass = (m.get('call_mass', 0.0) or 0.0) + (m.get('put_mass', 0.0) or 0.0)
        side, strength = control_side(m)
        rows.append({'key': k, 'dte': dte_by.get(k), 'mass': round(mass), 'share': round(mass / total, 4),
                     'side': side, 'control': round(strength, 3), 'fresh': m.get('fresh', True)})
    rows.sort(key=lambda r: (r['dte'] if r['dte'] is not None else 999))
    return rows, round(total)


def forward_share(rows) -> float:
    """Fraction of mass sitting in forward (dte>=1) expiries — the near→forward balance."""
    tot = sum(r['mass'] for r in rows) or 1.0
    fwd = sum(r['mass'] for r in rows if (r['dte'] or 0) >= 1)
    return round(fwd / tot, 4)


def migration_label(slope):
    """Direction of the forward-share change over the window (spec §28). slope = Δ forward_share."""
    if slope is None:
        return None
    if slope >= config.EXPIRY_MIGRATION_SLOPE:
        return 'FORWARD_MIGRATION'          # capital moving to a later expiry (rising time horizon)
    if slope <= -config.EXPIRY_MIGRATION_SLOPE:
        return 'NEAR_MIGRATION'             # capital pulling into the near expiry (urgency rising)
    return 'STABLE'


def classify(rows) -> str:
    """Structural classification (subset of spec §8) from the meaningful expiries' sides.
    Answers the ticker-level 'how is this thesis distributed across time?' question."""
    meaningful = [r for r in rows if r['share'] >= config.EXPIRY_MEANINGFUL_SHARE and r['mass'] > 0]
    if not meaningful:
        return 'NONE'
    if len(meaningful) == 1:
        r = meaningful[0]
        return 'FORWARD_POSITIONING' if (r['dte'] or 0) >= 1 else 'SAME_DAY_ACCUMULATION'
    near, forward = meaningful[0], meaningful[-1]
    if near['side'] and forward['side']:
        if near['side'] == forward['side']:
            # same side owns near AND forward → a coherent multi-expiry campaign
            return 'SAME_SIDE_MULTI_EXPIRY_CONTROL'
        # opposite sides near vs forward — the near expiry may be hedging the forward thesis
        return 'NEAR_TERM_PUT_FORWARD_CALL' if near['side'] == 'PUT' else 'NEAR_TERM_CALL_FORWARD_PUT'
    return 'EXPIRY_CONTEST'


def summarize(by_expiry: dict, dte_by: dict = None, prev_forward_share=None) -> dict:
    """One-shot view for the engine: rows, total, classification, forward-share + migration."""
    rows, total = expiry_rows(by_expiry, dte_by)
    fwd = forward_share(rows)
    slope = (fwd - prev_forward_share) if prev_forward_share is not None else None
    return {'rows': rows, 'total': total, 'classification': classify(rows),
            'forward_share': fwd, 'migration_slope': (round(slope, 4) if slope is not None else None),
            'migration': migration_label(slope)}
