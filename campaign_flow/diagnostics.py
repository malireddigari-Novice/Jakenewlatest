"""§11 Auxiliary single-contract bar diagnostics (journal only; they never trigger an exit).

Over the last 20 completed chronological bars: total volume, largest-three-bar share, fraction of bars with
volume, latest bar's share and the latest close's position within the observed closing range. The last field
keeps its legacy name `value_percentile`, but it is a RANGE LOCATION, not the §3 exact-contract percentile,
and can never replace that entry gate.
"""


def bar_diagnostics(bars, now_ts: float, n: int = 20) -> dict:
    """bars: [{'end': epoch, 'volume': int, 'close': float}] completed bars. Empty → zeros; future or
    non-chronological bars are invalid."""
    zero = {'valid': True, 'total_volume': 0, 'top3_share': 0.0, 'active_frac': 0.0, 'latest_share': 0.0,
            'value_percentile': 0.0, 'n': 0}
    if not bars:
        return zero
    ends = [float(b['end']) for b in bars]
    if any(e > now_ts for e in ends):
        return {**zero, 'valid': False, 'reason': 'FUTURE_BAR'}
    if any(b <= a for a, b in zip(ends, ends[1:])):
        return {**zero, 'valid': False, 'reason': 'NONCHRONOLOGICAL_BARS'}
    last = bars[-n:]
    vols = [max(0, int(b.get('volume') or 0)) for b in last]
    tot = sum(vols)
    closes = [float(b['close']) for b in last if b.get('close') is not None]
    lo, hi = (min(closes), max(closes)) if closes else (0.0, 0.0)
    loc = 0.0 if hi == lo or not closes else (closes[-1] - lo) / (hi - lo)
    return {'valid': True, 'n': len(last), 'total_volume': tot,
            'top3_share': round(sum(sorted(vols, reverse=True)[:3]) / tot, 4) if tot else 0.0,
            'active_frac': round(sum(1 for v in vols if v > 0) / len(vols), 4),
            'latest_share': round(vols[-1] / tot, 4) if tot else 0.0,
            'value_percentile': round(loc, 4)}
