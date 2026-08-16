"""
Data-quality / quote-sync validation (addendum #11-12) — pure, I/O-free.

"A 4,000-contract one-minute anomaly means nothing if the system counted a correction or a bad
quote." Before event detection, validate each contract snapshot. A structurally bad snapshot is
dropped from event detection; a stale/wide quote does not disqualify the print but REDUCES aggressor /
premium-acceptance confidence (a print at $2.00 means different things at 1.95×2.00 vs 2.00×2.20).

We cannot see OPRA trade-condition codes in the snapshot feed, so this covers what IS observable:
crossed/locked/zero/negative quotes, absurd marks, untrustworthy (too-wide) spreads, and quote
staleness via quote_ts. Returns a verdict + a 0..1 confidence the downstream reads should apply.
"""
import config
from datetime import datetime


def _quote_age_s(quote_ts, now):
    if not quote_ts:
        return None
    try:
        return (now - datetime.fromisoformat(quote_ts)).total_seconds()
    except Exception:
        return None


def validate(snap: dict, now=None) -> dict:
    """snap: one contract snapshot {bid, ask, mark, volume, quote_ts, ...}.
    Returns {ok(bool, structurally usable), drop(bool), confidence(0..1), flags[list], reason}."""
    bid, ask, mark = snap.get('bid'), snap.get('ask'), snap.get('mark')
    flags, conf = [], 1.0

    if mark is None or mark <= 0:
        return {'ok': False, 'drop': True, 'confidence': 0.0, 'flags': ['NO_MARK'], 'reason': 'no/zero mark'}
    if bid is not None and ask is not None:
        if bid < 0 or ask < 0:
            return {'ok': False, 'drop': True, 'confidence': 0.0, 'flags': ['NEGATIVE_QUOTE'],
                    'reason': 'negative quote'}
        if ask > 0 and bid > ask:
            flags.append('CROSSED')             # bid>ask — crossed/locked, quote untrustworthy
            conf *= 0.3
        mid = 0.5 * (bid + ask)
        if mid > 0:
            spread = (ask - bid) / mid
            if spread > config.DQ_MAX_SPREAD_PCT:
                flags.append('WIDE_SPREAD')
                conf *= 0.5
        # mark should sit within [bid, ask] (allow a small epsilon); otherwise it's a stale/bad mark
        if ask > 0 and not (bid - 1e-6 <= mark <= ask + 1e-6):
            flags.append('MARK_OUT_OF_BOOK')
            conf *= 0.6

    age = _quote_age_s(snap.get('quote_ts'), now) if now else None
    if age is not None and age > config.DQ_STALE_QUOTE_S:
        flags.append('STALE_QUOTE')
        conf *= 0.5

    drop = config.DQ_DROP_ENABLED and ('CROSSED' in flags or 'NEGATIVE_QUOTE' in flags)
    ok = not drop
    conf = round(max(0.0, min(1.0, conf)), 3)
    return {'ok': ok, 'drop': drop, 'confidence': conf, 'flags': flags,
            'reason': ('clean' if not flags else ','.join(flags)), 'quote_age_s': age}
