"""
Hedge-flow read — DirectionalConfidence vs ConvexityDemandConfidence (addendum #13) — pure.

Not every call buyer is making a bullish stock bet; some are buying convexity/vol (e.g. long calls +
short stock). We can't know participant intent, but the *shape* of the move tells us something:

  • premium/IV being bid hard while the spot follow-through is weak  → CONVEXITY demand dominant
  • premium expanding WITH spot confirming in the trade's direction  → DIRECTIONAL dominant

Keeping the two confidences separate stops the engine from reading a pure vol/convexity bid as a
clean directional campaign. When convexity dominates directional, entry P(continue) is discounted.
"""
import config


def assess(*, iv_slope, spot_confirms, resp_event, delta) -> dict:
    """iv_slope: dIV/dt (None if unavailable). spot_confirms: bool (spot moved the trade's way).
    resp_event: premium response since event. delta: contract delta (|delta| small = far OTM convexity).
    Returns {read: DIRECTIONAL/CONVEXITY/NEUTRAL, directional_conf, convexity_conf, mult, reason}."""
    iv_rising = (iv_slope is not None and iv_slope > 0)
    resp = resp_event or 0.0
    absd = abs(float(delta)) if delta is not None else None

    directional = 0.0
    convexity = 0.0
    # directional evidence: spot confirms AND premium responded positively
    if spot_confirms and resp > 0:
        directional += 0.6
    if spot_confirms:
        directional += 0.2
    if absd is not None and absd >= 0.45:        # near/ITM — more directional than pure convexity
        directional += 0.2
    # convexity evidence: IV bid hard while spot doesn't confirm, esp. low-delta OTM
    if iv_rising and not spot_confirms:
        convexity += 0.6
    if iv_rising and resp > 0.1 and not spot_confirms:
        convexity += 0.2
    if absd is not None and absd <= 0.30:        # far OTM — convexity-leaning
        convexity += 0.2

    directional = round(min(1.0, directional), 3)
    convexity = round(min(1.0, convexity), 3)
    if convexity > directional + 0.2:
        return {'read': 'CONVEXITY', 'directional_conf': directional, 'convexity_conf': convexity,
                'mult': config.HEDGE_DISCOUNT,
                'reason': f'convexity/vol demand ({convexity:.2f}) > directional ({directional:.2f}) — IV bid, weak spot follow-through'}
    if directional > convexity + 0.2:
        return {'read': 'DIRECTIONAL', 'directional_conf': directional, 'convexity_conf': convexity,
                'mult': 1.0, 'reason': f'directional ({directional:.2f}) > convexity ({convexity:.2f})'}
    return {'read': 'NEUTRAL', 'directional_conf': directional, 'convexity_conf': convexity,
            'mult': 1.0, 'reason': 'directional/convexity balanced'}
