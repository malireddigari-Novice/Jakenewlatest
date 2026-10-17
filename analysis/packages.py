"""
Package / Leg / Roll Resolver (addendum #7-8) — pure, I/O-free.

A fantastic-looking single-strike print can be one leg of a vertical / calendar / roll / ratio /
straddle. `BUY 10,000 335C / SELL 10,000 340C` looked at through 335C alone reads as massive bullish
accumulation, but economically it is a capped-risk vertical — still perhaps bullish, but very
different from outright long calls. Worse, `SELL 330C / BUY 335C` may just be a roll.

We cannot see buy/sell tags or complex-order flags in the snapshot, so we resolve by SIZE-MATCHED
CO-PRINTS on the surface within a poll (the strongest freely-available package tell):

  • adjacent same-side strikes, size-matched  → VERTICAL_LIKELY
  • same strike, call + put, size-matched      → STRADDLE/COMBO_LIKELY
  • same side, ~PKG_RATIO:1 size ratio         → RATIO_LIKELY
  • same strike/side, equal size, other expiry → ROLL/CALENDAR_LIKELY   (only when cross-expiry given)
  • no size-match                              → OUTRIGHT_LIKELY

The output is per traded contract: is it plausibly a package leg, and how confident. The engine
DISCOUNTS a leg-looking contract's directional weight (it is not clean outright flow) and, behind
PKG_VETO, can hard-reject it. Conservative by construction: only clear size-matches flag.
"""
import config

RULE_VERSION = 'pkg-snapshot-v2'


def _matched(a, b) -> bool:
    """Two leg sizes count as size-matched when within ±PKG_SIZE_TOL of each other."""
    if a <= 0 or b <= 0:
        return False
    return abs(a - b) / max(a, b) <= config.PKG_SIZE_TOL


def leg_ratio(a, b) -> str | None:
    """Leg sizes reduced to their greatest-common-divisor ratio — 4,000 vs 7,000 is "4:7", never 1:1.
    Sizes are first rounded to PKG_RATIO_LOT contracts so split-fill noise does not explode the ratio."""
    from math import gcd
    lot = max(1, config.PKG_RATIO_LOT)
    x, y = int(round((a or 0) / lot)), int(round((b or 0) / lot))
    if x <= 0 or y <= 0:
        return None
    g = gcd(x, y)
    return f"{x // g}:{y // g}"


def _ratio(a, b) -> bool:
    if b <= 0:
        return False
    r = a / b
    return config.PKG_RATIO_LO <= r <= config.PKG_RATIO_HI


def resolve(strike, side, vols_by_leg, spot, *, cross_expiry_vol=None) -> dict:
    """Classify the package context of one traded (strike, side).
    vols_by_leg : {(k, s): fresh_vol} for the current poll/expiry (both sides).
    cross_expiry_vol : optional {(k, s): fresh_vol} for a NEIGHBORING expiry (enables ROLL/CALENDAR).
    Returns {label, confidence(0-1), leg, discount, reason}. leg=True means 'likely a spread leg'."""
    v0 = (vols_by_leg or {}).get((strike, side), 0) or 0
    if v0 < config.PKG_MIN_LEG_CONTRACTS:
        return _out({'OUTRIGHT': 1.0}, 'sub-floor leg — not resolvable')
    opp = 'PUT' if side == 'CALL' else 'CALL'

    # v3-review item 14: without complex-order condition codes a size/time-matched co-print is only a
    # PROBABLE package (two similar clips can be coincidental in a liquid Mag-7 name). Emit PROBABILITIES
    # and hard-veto only when the complex probability is overwhelming (engine: PKG_VETO_MIN_CONF).
    p = {'OUTRIGHT': 0.0, 'ROLL': 0.0, 'CALENDAR': 0.0, 'STRADDLE': 0.0, 'VERTICAL': 0.0, 'RATIO': 0.0}

    if cross_expiry_vol:
        vx = cross_expiry_vol.get((strike, side), 0) or 0
        if _matched(v0, vx):
            p['ROLL'] += 0.7
    vp = (vols_by_leg or {}).get((strike, opp), 0) or 0
    if _matched(v0, vp):
        p['STRADDLE'] += 0.6
    neighbors = sorted(((k, v) for (k, s), v in (vols_by_leg or {}).items()
                        if s == side and k != strike and v and v >= config.PKG_MIN_LEG_CONTRACTS),
                       key=lambda kv: abs(kv[0] - strike))
    partner = None                                    # (strike, side, vol) of the co-print behind the top read
    if p['ROLL'] and cross_expiry_vol:
        partner = (strike, side, cross_expiry_vol.get((strike, side), 0) or 0)
    if p['STRADDLE']:
        partner = (strike, opp, vp)
    for k, v in neighbors[:config.PKG_NEIGHBOR_STRIKES * 2]:
        if _matched(v0, v):
            p['VERTICAL'] = max(p['VERTICAL'], 0.55)
            partner = partner or (k, side, v)
        elif _ratio(v0, v) or _ratio(v, v0):
            p['RATIO'] = max(p['RATIO'], 0.45)
            partner = partner or (k, side, v)
    complex_prob = min(1.0, p['ROLL'] + p['STRADDLE'] + p['VERTICAL'] + p['RATIO'])
    p['OUTRIGHT'] = round(1.0 - complex_prob, 3)
    top = max((k for k in p if k != 'OUTRIGHT'), key=lambda k: p[k])
    if complex_prob <= 0:
        return _out({'OUTRIGHT': 1.0}, 'no size-matched co-print — reads outright')
    label = {'ROLL': 'ROLL_LIKELY', 'STRADDLE': 'STRADDLE_COMBO_LIKELY',
             'VERTICAL': 'VERTICAL_LIKELY', 'RATIO': 'RATIO_LIKELY',
             'CALENDAR': 'CALENDAR_LIKELY'}[top]
    # discount scales with how confident we are it is NOT outright
    disc = 1.0 - (1.0 - config.PKG_DISCOUNT) * complex_prob
    # Flow handoff §5: association from time/size alone is the WEAKEST grade — the snapshot feed has no
    # complex-order condition codes, venue or ms timestamps. Leg sides, the debit/credit and any stock
    # leg are UNKNOWN; this is a package CANDIDATE, never a known structure or a net cashflow.
    return {'label': label, 'confidence': round(complex_prob, 3), 'complex_prob': round(complex_prob, 3),
            'association': 'TIME_SIZE_ONLY', 'net_side': 'UNKNOWN', 'net_cashflow': 'UNKNOWN',
            'partner': ({'strike': partner[0], 'side': partner[1], 'contracts': partner[2]} if partner else None),
            'ratio': leg_ratio(v0, partner[2]) if partner else None,
            'rule_version': RULE_VERSION,
            'probs': {k: round(v, 3) for k, v in p.items()},
            'leg': complex_prob >= config.PKG_VETO_MIN_CONF, 'discount': round(disc, 3),
            'reason': f'{label} p={complex_prob:.2f} (outright {p["OUTRIGHT"]:.2f}) — probabilistic, no condition codes'}


def _out(probs, reason):
    full = {'OUTRIGHT': 0.0, 'ROLL': 0.0, 'CALENDAR': 0.0, 'STRADDLE': 0.0, 'VERTICAL': 0.0, 'RATIO': 0.0}
    full.update(probs)
    return {'label': 'OUTRIGHT_LIKELY', 'confidence': 0.0, 'complex_prob': 0.0, 'probs': full,
            'association': None, 'net_side': 'UNKNOWN', 'net_cashflow': 'UNKNOWN', 'partner': None,
            'ratio': None, 'rule_version': RULE_VERSION, 'leg': False, 'discount': 1.0, 'reason': reason}
