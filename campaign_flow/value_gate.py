"""§3 Exact-contract premium value gate.

The event premium is compared ONLY with earlier marks of the same exact series (ticker, right, strike,
expiration, adjustment). A reference must be positive, valid, carry the same series key and be stamped
strictly before the event-window start. Fewer than VALUE_MIN_REFS references (or no reference timestamp)
leaves the value UNRESOLVED, which earns no buy attention. Other strikes/expirations are never substituted.

Low premium does not prove fair value or buyer-to-open; high premium does not prove a sale. The band is a
conservative eligibility rule, nothing more.
"""
from campaign_flow import settings as S
from campaign_flow.model import series_key

LOW, MIDDLE, HIGH, UNRESOLVED = 'LOW', 'MIDDLE', 'HIGH', 'UNRESOLVED'


def classify(contract: dict, event_premium, refs, window_start: float, price_basis: str = None) -> dict:
    """refs: iterable of {'series': series_key, 'ts': epoch, 'price': float, 'basis': str}.
    Returns the decision with its full provenance (sample count, latest ts, period, observed range)."""
    key = series_key(contract)
    valid, excluded = [], {'OTHER_SERIES': 0, 'NOT_BEFORE_WINDOW': 0, 'INVALID_PRICE': 0, 'BASIS_MISMATCH': 0}
    for r in refs or ():
        if tuple(r.get('series') or ()) != key:
            excluded['OTHER_SERIES'] += 1
            continue
        ts, px = r.get('ts'), r.get('price')
        if ts is None or not (float(ts) < float(window_start)):
            excluded['NOT_BEFORE_WINDOW'] += 1
            continue
        if px is None or not (float(px) > 0):
            excluded['INVALID_PRICE'] += 1
            continue
        if price_basis and r.get('basis') and r['basis'] != price_basis:
            excluded['BASIS_MISMATCH'] += 1
            continue
        valid.append((float(ts), float(px)))
    out = {'series': list(key), 'n': len(valid), 'excluded': excluded, 'price_basis': price_basis,
           'event_premium': event_premium, 'pct': None, 'band': UNRESOLVED, 'reasons': []}
    if valid:
        ts_list = [t for t, _ in valid]
        px_list = [p for _, p in valid]
        out.update(latest_ts=max(ts_list), period=[min(ts_list), max(ts_list)],
                   range=[min(px_list), max(px_list)])
    if event_premium is None or not (float(event_premium) > 0) or len(valid) < S.VALUE_MIN_REFS:
        out['reasons'].append('EXACT_CONTRACT_VALUE_HISTORY_MISSING')
        return out
    e = float(event_premium)
    below = sum(1 for _, p in valid if p < e)
    equal = sum(1 for _, p in valid if p == e)
    pct = (below + 0.5 * equal) / len(valid)
    out['pct'] = round(pct, 6)
    if pct <= S.VALUE_LOW_MAX:
        out['band'] = LOW
    elif pct >= S.VALUE_HIGH_MIN:
        out['band'] = HIGH
        out['reasons'].append('HIGH_VALUE_FLOW_SELL_OR_CLOSE_POSSIBLE')
    else:
        out['band'] = MIDDLE
        out['reasons'].append('PREMIUM_OUTSIDE_LOW_VALUE_BAND')
    return out
