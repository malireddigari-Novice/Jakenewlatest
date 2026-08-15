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


def _matched(a, b) -> bool:
    """Two leg sizes count as size-matched when within ±PKG_SIZE_TOL of each other."""
    if a <= 0 or b <= 0:
        return False
    return abs(a - b) / max(a, b) <= config.PKG_SIZE_TOL


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
        return {'label': 'OUTRIGHT_LIKELY', 'confidence': 0.0, 'leg': False,
                'discount': 1.0, 'reason': 'sub-floor leg — not resolvable'}
    opp = 'PUT' if side == 'CALL' else 'CALL'

    # Roll / calendar: same strike+side, size-matched, in a neighboring expiry.
    if cross_expiry_vol:
        vx = cross_expiry_vol.get((strike, side), 0) or 0
        if _matched(v0, vx):
            return {'label': 'ROLL_LIKELY', 'confidence': 0.7, 'leg': True,
                    'discount': config.PKG_DISCOUNT,
                    'reason': f'size-matched {v0:.0f}≈{vx:.0f} same strike in a neighboring expiry'}

    # Straddle / combo: same strike, opposite side, size-matched.
    vp = (vols_by_leg or {}).get((strike, opp), 0) or 0
    if _matched(v0, vp):
        return {'label': 'STRADDLE_COMBO_LIKELY', 'confidence': 0.6, 'leg': True,
                'discount': config.PKG_DISCOUNT,
                'reason': f'size-matched {v0:.0f}≈{vp:.0f} call+put on {strike:g} (volatility, not direction)'}

    # Vertical / ratio: an adjacent same-side strike within PKG_NEIGHBOR_STRIKES.
    neighbors = sorted(((k, v) for (k, s), v in (vols_by_leg or {}).items()
                        if s == side and k != strike and v and v >= config.PKG_MIN_LEG_CONTRACTS),
                       key=lambda kv: abs(kv[0] - strike))
    for k, v in neighbors[:config.PKG_NEIGHBOR_STRIKES * 2]:
        if _matched(v0, v):
            return {'label': 'VERTICAL_LIKELY', 'confidence': 0.55, 'leg': True,
                    'discount': config.PKG_DISCOUNT,
                    'reason': f'size-matched {v0:.0f}≈{v:.0f} adjacent same-side {strike:g}/{k:g} vertical'}
        if _ratio(v0, v) or _ratio(v, v0):
            return {'label': 'RATIO_LIKELY', 'confidence': 0.45, 'leg': True,
                    'discount': config.PKG_DISCOUNT,
                    'reason': f'~{max(v0, v)/max(1, min(v0, v)):.1f}:1 size ratio {strike:g}/{k:g} — ratio spread'}

    return {'label': 'OUTRIGHT_LIKELY', 'confidence': 0.0, 'leg': False,
            'discount': 1.0, 'reason': 'no size-matched co-print — reads outright'}
