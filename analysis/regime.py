"""
Regime context (addendum #17) — pure, I/O-free.

Opening clusters on CPI / FOMC / earnings / OpEx days, or in a high-volatility regime, do not mean
the same thing as on an ordinary session. Regime is a CONFIDENCE MODIFIER, never a hard gate — it must
not override pristine option information; it only makes the engine slightly more or less willing.

Event dates come from a config calendar (REGIME_EVENT_DATES, comma-separated ISO dates); the realized-
volatility proxy is passed in by the caller. Returns a multiplier applied to entry P(continue).
"""
import config


def assess(today, *, realized_vol=None, high_vol_threshold=None) -> dict:
    """today: ISO date str or date. realized_vol: optional current vol proxy (same units as threshold).
    Returns {regime, mult, reason}. mult defaults to 1.0 (neutral)."""
    day = str(today)[:10] if today is not None else None
    tags, mult = [], 1.0
    if day and day in set(config.REGIME_EVENT_DATES):
        tags.append('MACRO_EVENT')
        mult *= config.REGIME_EVENT_MULT
    if (realized_vol is not None and high_vol_threshold is not None
            and realized_vol >= high_vol_threshold):
        tags.append('HIGH_VOL')
        mult *= config.REGIME_HIGH_VOL_MULT
    return {'regime': '+'.join(tags) if tags else 'NORMAL', 'mult': round(mult, 3),
            'reason': ('ordinary session' if not tags else ' & '.join(tags) + ' — slightly more cautious')}
