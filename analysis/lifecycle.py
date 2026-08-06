"""
Campaign lifecycle — the "event shape THROUGH TIME" layer (Morning-session research notes).

Raw volume, even the compact shape, is only a snapshot. The strongest institutional-accumulation
signatures are *temporal*: an option is accumulated in a compact burst, then the buying FADES
while the premium keeps appreciating (the inventory is already owned — the move becomes
self-sustaining). Weak campaigns fail the instant the buying stops. And genuine campaigns often
CONSOLIDATE — a shakeout that flushes weak hands — before the violent convexity expansion, so the
engine must not reject a brief dip that recovers (the NVDA-put case).

This module turns a contract's recent premium series (marks) and fresh-volume series into:
  • windowed_premium_response — response over 30/60/90/180/300s + max-favorable-excursion + the
    area under the premium curve (tolerates delayed convexity instead of judging the next bar),
  • shakeout_score — did the premium dip below the event price then recover above it?
  • self_sustainability — is the premium still rising WHILE the volume fades?
  • efficiency_trend — is premium-response efficiency rising, stable, or decaying across polls?
  • continuation_probability — a joint 0-1 estimate that the campaign continues.

All pure functions. Inputs are plain lists; everything degrades to a neutral value when the
series is too short (e.g. the 1-min backtest, where sub-minute windows collapse).
"""
import math

import config


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def _slope(ys: list) -> float:
    """Least-squares slope of ys against index 0..n-1 (0.0 for < 2 points)."""
    n = len(ys)
    if n < 2:
        return 0.0
    xbar = (n - 1) / 2.0
    ybar = sum(ys) / n
    num = sum((i - xbar) * (y - ybar) for i, y in enumerate(ys))
    den = sum((i - xbar) ** 2 for i in range(n))
    return num / den if den else 0.0


def windowed_premium_response(marks: list, event_price) -> dict:
    """
    marks: [(t, price), ...] oldest→newest (t = epoch seconds). event_price = the wave's birth
    price. Rather than judging only the latest bar, measure the premium's response across several
    trailing windows plus its best excursion and the area under the (normalised) premium curve —
    so a campaign that briefly consolidates is scored, not rejected.
    Returns {mfe, mae, auc, slope, r30, r60, r90, r180, r300, last}. Neutral zeros when empty.
    """
    out = {'mfe': 0.0, 'mae': 0.0, 'auc': 0.0, 'slope': 0.0,
           'r30': 0.0, 'r60': 0.0, 'r90': 0.0, 'r180': 0.0, 'r300': 0.0, 'last': 0.0}
    if not marks or not event_price or event_price <= 0:
        return out
    prices = [p for _, p in marks if p is not None]
    if not prices:
        return out
    rels = [p / event_price - 1.0 for p in prices]
    out['mfe'] = round(max(rels), 4)                 # max favourable excursion since the event
    out['mae'] = round(min(rels), 4)                 # max adverse excursion (worst dip)
    out['auc'] = round(sum(rels) / len(rels), 4)     # mean normalised premium (area under curve)
    out['slope'] = round(_slope(rels), 6)
    out['last'] = round(rels[-1], 4)
    now_t = marks[-1][0]
    for w, key in ((30, 'r30'), (60, 'r60'), (90, 'r90'), (180, 'r180'), (300, 'r300')):
        ref = None
        for t, p in marks:                            # first mark at/after now-w
            if p is not None and t >= now_t - w:
                ref = p
                break
        if ref and ref > 0:
            out[key] = round(prices[-1] / ref - 1.0, 4)
    return out


def shakeout_score(marks: list, event_price) -> float:
    """
    0-1: did the premium DIP below the event price (weak hands flushed) and then RECOVER above it?
    A campaign that consolidates before expanding deserves credit, not rejection. Score rises with
    both the depth of the dip and the strength of the recovery back through the event price.
    """
    if not marks or not event_price or event_price <= 0:
        return 0.0
    prices = [p for _, p in marks if p is not None]
    if len(prices) < 3:
        return 0.0
    trough = min(prices)
    trough_i = prices.index(trough)
    if trough_i == len(prices) - 1:                   # still falling — not a recovery
        return 0.0
    dip = max(0.0, (event_price - trough) / event_price)         # how far below the event it went
    recovery = max(0.0, (prices[-1] - trough) / event_price)     # how far it has climbed back
    if prices[-1] < event_price * (1.0 - config.SHAKEOUT_RESID_TOL):
        return 0.0                                    # never made it back near the event price
    return round(min(1.0, (min(dip, 0.5) / 0.5) * 0.5 + min(recovery, 0.5) / 0.5 * 0.5), 3)


def self_sustainability(vols: list, marks: list) -> float:
    """
    0-1: is the premium still appreciating WHILE the fresh buying fades? The signature of
    efficient accumulation — inventory already acquired, so the move no longer needs constant
    aggressive volume. High when recent volume has fallen well below the campaign's peak AND the
    recent premium slope is positive; low when the premium stalls/falls the moment volume drops.
    """
    prices = [p for _, p in marks if p is not None] if marks else []
    if len(prices) < 3 or not vols:
        return 0.0
    peak_vol = max(vols) or 1.0
    tail = max(1, len(vols) // 3)
    recent_vol = sum(vols[-tail:]) / tail
    vol_fade = max(0.0, min(1.0, 1.0 - recent_vol / peak_vol))   # 1 = volume has fully faded
    prem_slope = _slope(prices[-max(3, len(prices) // 3):])
    prem_rising = _sigmoid(prem_slope / (abs(prices[-1]) * 0.02 + 1e-9))   # slope normalised by ~2%
    return round(vol_fade * prem_rising, 3)


def efficiency_trend(eff_hist: list) -> dict:
    """
    Is premium-response EFFICIENCY (ΔP per unit flow) rising, stable, or decaying across recent
    polls? A campaign needing less incremental buying to keep rising is structurally healthier
    than one needing ever more just to hold price. Returns {slope, label} where label ∈
    {RISING, STABLE, DECAYING}. Neutral STABLE when history is too short.
    """
    if not eff_hist or len(eff_hist) < 3:
        return {'slope': 0.0, 'label': 'STABLE'}
    s = _slope(eff_hist[-config.EFF_TREND_WINDOW:])
    if s > config.EFF_TREND_EPS:
        label = 'RISING'
    elif s < -config.EFF_TREND_EPS:
        label = 'DECAYING'
    else:
        label = 'STABLE'
    return {'slope': round(s, 5), 'label': label}


def continuation_probability(*, self_sust=0.0, eff_slope=0.0, auc=0.0, control=0.6,
                             spot_confirms=True, shakeout=0.0) -> float:
    """
    Joint 0-1 probability the campaign CONTINUES — the P(continue) that expected-value entry
    timing needs. A weighted logistic: self-sustainability and a rising efficiency trend and a
    positive area-under-premium and strong control and spot confirmation all push it up; a
    recovered shakeout adds credit. Returns 0.5 (neutral) when the feature is disabled.
    """
    if not config.CONTINUATION_ENABLED:
        return 0.5
    logit = config.CONT_BIAS
    logit += config.CONT_W_SELFSUST * (self_sust or 0.0) * 2.0
    logit += config.CONT_W_EFFTREND * max(-1.0, min(1.0, (eff_slope or 0.0) * config.EFF_TREND_SCALE))
    logit += config.CONT_W_PERSIST * (1.0 if (auc or 0.0) > 0 else -0.6)
    logit += config.CONT_W_CONTROL * max(-1.0, min(1.0, ((control or 0.0) - 0.6) * 3.0))
    logit += config.CONT_W_SPOT * (0.5 if spot_confirms else -0.5)
    logit += config.CONT_W_SHAKEOUT * (shakeout or 0.0)
    return round(_sigmoid(logit), 3)
