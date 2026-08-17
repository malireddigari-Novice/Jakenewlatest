"""
Premium-move decomposition (addendum #14) — pure, I/O-free.

A contract going $1 → $2 because spot moved is a different signal from one that doubled because IV
exploded. Decompose the observed premium change into what the greeks explain:

    ΔP ≈ delta·ΔS + ½·gamma·ΔS² + residual

where residual is everything the delta/gamma of the underlying move does NOT explain — dominated by
vega·ΔIV (and theta), i.e. the volatility/convexity component. OPRA gives delta, gamma, iv (no vega/
theta), so we attribute the spot-explained part precisely and label the rest as the IV/residual
component. Used to tag a move DELTA_DRIVEN vs IV_DRIVEN and to feed the hedge-flow read.
"""


def decompose(*, prev_mark, mark, delta, gamma, spot_prev, spot) -> dict:
    """Returns {dP, delta_contrib, gamma_contrib, residual, driver, iv_share} — driver is
    DELTA_DRIVEN / IV_DRIVEN / MIXED / UNKNOWN. Degrades to UNKNOWN when greeks/spot are missing."""
    if None in (prev_mark, mark, spot_prev, spot) or delta is None:
        return {'dP': None, 'delta_contrib': None, 'gamma_contrib': None, 'residual': None,
                'driver': 'UNKNOWN', 'iv_share': None, 'reason': 'insufficient greeks/spot'}
    dS = float(spot) - float(spot_prev)
    dP = float(mark) - float(prev_mark)
    delta_c = float(delta) * dS
    gamma_c = 0.5 * float(gamma) * dS * dS if gamma is not None else 0.0
    explained = delta_c + gamma_c
    # v3-audit item 13: this residual is NOT pure IV demand — it also carries theta, vega nonlinearity,
    # spread/quote noise, higher-order greeks and timestamp mismatch. Until vega/theta + synchronized
    # timestamps exist it is the UNEXPLAINED premium component, not "IV". Driver: SPOT vs UNEXPLAINED.
    unexplained = dP - explained
    denom = abs(dP) if abs(dP) > 1e-9 else 1e-9
    unexplained_share = max(0.0, min(1.0, abs(unexplained) / denom))
    spot_share = max(0.0, min(1.0, abs(explained) / denom))
    if spot_share >= 0.65:
        driver = 'SPOT_DRIVEN'
    elif unexplained_share >= 0.65:
        driver = 'UNEXPLAINED_DRIVEN'            # likely IV/vol, but not proven until greeks exist
    else:
        driver = 'MIXED'
    return {'dP': round(dP, 4), 'delta_contrib': round(delta_c, 4), 'gamma_contrib': round(gamma_c, 4),
            'unexplained_premium': round(unexplained, 4), 'unexplained_share': round(unexplained_share, 3),
            'driver': driver, 'spot_share': round(spot_share, 3),
            'reason': f'{driver} (spot {spot_share:.2f} / unexplained {unexplained_share:.2f})'}
