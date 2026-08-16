"""
Expiry selector (v3-review item 10) — detect the campaign first, THEN choose the expression. Pure.

The base engine trades the nearest expiry; a late-0DTE veto is not the same thing as *choosing* an
expiry. Once a campaign is detected, this ranks the candidate expirations (0DTE / 1DTE / next-listed /
weekly) on the economics of expressing THIS campaign:

    score = remaining_convexity_fit                 (does the horizon match the thesis?)
          + event_information_share                 (where is the campaign's own flow concentrated?)
          + cross_expiry_agreement                  (forward control agrees with the side)
          − theta_burden                            (0DTE late-day theta is punishing)
          − illiquidity                             (wide spread / thin quotes hurt expression)

Default SHADOW (logs the recommended expiry); execution still uses the nearest expiry until wired.
This makes the campaign→expiry→strike order explicit rather than nearest-expiry-hardcoded.
"""
import config


def _theta_burden(dte, minutes_since_open):
    """0DTE late in the day is the worst theta; longer DTE is progressively immune."""
    if dte is None:
        return 0.3
    if dte <= 0:
        return max(0.0, min(1.0, minutes_since_open / 390.0))   # ramps 0→1 across the session
    if dte == 1:
        return 0.25
    return max(0.0, 0.15 - 0.02 * dte)


def score_expiry(row, *, traded_side, minutes_since_open, campaign_horizon='INTRADAY') -> dict:
    """row: {'dte', 'share', 'side', 'spread_pct'(opt)} for one expiry of this ticker/side.
    campaign_horizon: 'INTRADAY' prefers near expiries; 'MULTIDAY' rewards forward ones."""
    dte = row.get('dte')
    share = row.get('share') or 0.0
    theta = _theta_burden(dte, minutes_since_open)
    illiq = max(0.0, min(1.0, (row.get('spread_pct') or 0.0)))
    # remaining-convexity fit: intraday theses want DTE 0-1; multiday want ≥2.
    if campaign_horizon == 'MULTIDAY':
        conv = 0.4 if (dte is not None and dte <= 0) else min(1.0, 0.6 + 0.1 * (dte or 0))
    else:
        conv = 1.0 if (dte is not None and dte <= 1) else max(0.2, 1.0 - 0.15 * (dte or 0))
    agree = 0.15 if row.get('side') == traded_side else 0.0
    score = conv + share + agree - config.LATE0DTE_THETA_WEIGHT * theta - 0.3 * illiq
    return {'dte': dte, 'score': round(score, 3), 'theta': round(theta, 3), 'conv': round(conv, 3),
            'share': round(share, 3), 'illiquidity': round(illiq, 3)}


def select(rows, *, traded_side, minutes_since_open, campaign_horizon='INTRADAY') -> dict:
    """rows: per-expiry structure for this ticker/side (from the multi-expiry scan), each with a 'dte'.
    Returns {'best_dte', 'ranked':[...], 'reason'} — the expiry that best expresses the campaign."""
    scored = [score_expiry(r, traded_side=traded_side, minutes_since_open=minutes_since_open,
                           campaign_horizon=campaign_horizon) for r in (rows or []) if r.get('dte') is not None]
    if not scored:
        return {'best_dte': None, 'ranked': [], 'reason': 'no expiry structure — default nearest'}
    scored.sort(key=lambda s: -s['score'])
    best = scored[0]
    return {'best_dte': best['dte'], 'ranked': scored,
            'reason': f"DTE {best['dte']} best expresses the {campaign_horizon.lower()} campaign "
                      f"(score {best['score']}, theta {best['theta']}, share {best['share']})"}
