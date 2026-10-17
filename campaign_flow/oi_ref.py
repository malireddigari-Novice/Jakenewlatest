"""§9/§10 Daily OI reference: freeze the nearest expiration before the open, pin the regular opening price,
derive nearby call-resistance / put-support nodes, and describe OI zones for confirmed clusters.

OI is a daily LOCATION reference: it never filters the scanner, never gates entries or exits, counts both
long and short open positions, and does not label any print opening or closing.

Chain record (append-only): {ticker, session, rows: [{expiry, right, strike, oi}], published_ts,
available_ts, source_id, complete (verified by the adapter), both_sides}.
"""
from datetime import date

from campaign_flow import calendar_ny as cal
from campaign_flow import settings as S


def freeze(chains, ticker: str, session: date, invoked_ts: float) -> dict:
    """Freeze for one ticker/session. Allowed from the cutoff up to (excluding) the regular open; a delayed
    invocation still applies the ORIGINAL cutoff. Missing/incomplete → an explicit empty record."""
    b = cal.bounds(session)
    cutoff = cal.oi_cutoff(session)
    base = {'ticker': ticker, 'session': session.isoformat(), 'cutoff_ts': cutoff, 'invoked_ts': invoked_ts,
            'expiry': None, 'rows': [], 'source_id': None, 'published_ts': None, 'missing': True}
    if not b:
        return {**base, 'reason': 'NOT_A_TRADING_DAY'}
    if invoked_ts < cutoff:
        return {**base, 'reason': 'BEFORE_CUTOFF'}
    if invoked_ts >= b[0]:
        return {**base, 'reason': 'MISSED_OPEN_OI_CONTEXT_MISSING'}
    ok = [c for c in chains
          if c['ticker'] == ticker and c.get('complete') and c.get('both_sides')
          and c.get('published_ts') is not None and float(c['published_ts']) <= cutoff
          and c.get('available_ts') is not None and float(c['available_ts']) <= max(cutoff, invoked_ts)]
    if not ok:
        return {**base, 'reason': 'NO_COMPLETE_CHAIN_PUBLISHED_BY_CUTOFF'}
    chain = max(ok, key=lambda c: (float(c['published_ts']), float(c['available_ts'])))
    exps = sorted({str(r['expiry']) for r in chain['rows'] if str(r['expiry']) >= session.isoformat()})
    if not exps:
        return {**base, 'reason': 'NO_UNEXPIRED_EXPIRATION'}
    nearest = exps[0]                                  # never a later expiry for having more OI
    rows = [dict(r) for r in chain['rows'] if str(r['expiry']) == nearest]
    return {**base, 'expiry': nearest, 'rows': rows, 'source_id': chain.get('source_id'),
            'published_ts': chain['published_ts'], 'missing': False, 'reason': None}


def pin_open(existing: dict, record: dict) -> dict:
    """The first recorded regular-session opening price is immutable for the session."""
    return existing if existing else dict(record)


def levels(frozen: dict, opening: dict, as_of_ts: float = None) -> dict:
    """Nearby OI nodes around the FIXED opening price. Not visible before the opening price was known."""
    empty = {'call_resistance': [], 'put_support': [], 'reason': None}
    if not frozen or frozen.get('missing'):
        return {**empty, 'reason': 'OI_CONTEXT_MISSING'}
    if not opening or opening.get('price') is None:
        return {**empty, 'reason': 'OPENING_PRICE_MISSING'}
    if as_of_ts is not None and float(opening['available_ts']) > float(as_of_ts):
        return {**empty, 'reason': 'OPENING_PRICE_NOT_YET_KNOWN'}
    px = float(opening['price'])

    def pick(right, cond):
        elig = [r for r in frozen['rows'] if r['right'] == right and (r.get('oi') or 0) > 0 and cond(float(r['strike']))]
        strip = sorted(elig, key=lambda r: (abs(float(r['strike']) - px), float(r['strike'])))[:S.OI_STRIP]
        top = sorted(strip, key=lambda r: (-r['oi'], abs(float(r['strike']) - px), float(r['strike'])))[:S.OI_LEVELS]
        return [{'strike': float(r['strike']), 'oi': r['oi']} for r in top]

    return {'call_resistance': pick('C', lambda k: k >= px), 'put_support': pick('P', lambda k: k <= px),
            'reason': None, 'opening_price': px, 'expiry': frozen['expiry']}


def zone(frozen: dict, cluster: dict) -> dict:
    """Descriptive OI zone for a confirmed cluster in the FROZEN expiration only (journal, never a card)."""
    if not frozen or frozen.get('missing'):
        return {'zone': None, 'reason': 'OI_CONTEXT_MISSING'}
    if str(cluster['expiry']) != str(frozen['expiry']):
        return {'zone': None, 'reason': 'CLUSTER_NOT_IN_FROZEN_EXPIRATION'}
    if frozen.get('published_ts') is None or float(frozen['published_ts']) >= float(cluster['first_start']):
        return {'zone': None, 'reason': 'OI_NOT_PUBLISHED_BEFORE_CLUSTER'}
    side = [r for r in frozen['rows'] if r['right'] == cluster['right']]
    strikes = [float(r['strike']) for r in side]
    if len(strikes) != len(set(strikes)):
        return {'zone': None, 'reason': 'DUPLICATED_CHAIN_ROWS'}
    for r in (frozen['rows']):
        if r['right'] not in ('C', 'P'):
            return {'zone': None, 'reason': 'INVALID_CHAIN_ROWS'}
    if any(len({float(r['strike']) for r in frozen['rows'] if r['right'] == rt}) < 2 for rt in ('C', 'P')):
        return {'zone': None, 'reason': 'INSUFFICIENT_CHAIN'}
    ks = sorted(strikes)
    active = sorted(float(k) for k in cluster['strikes'])
    if any(k not in ks for k in active):
        return {'zone': None, 'reason': 'ACTIVE_STRIKE_NOT_LISTED'}
    oi = {float(r['strike']): r.get('oi') for r in side}

    def cell(i):
        k = ks[i]
        lo = (ks[i - 1] + k) / 2 if i > 0 else k - (ks[1] - ks[0]) / 2
        hi = (ks[i + 1] + k) / 2 if i < len(ks) - 1 else k + (ks[-1] - ks[-2]) / 2
        return lo, hi

    idx = [ks.index(k) for k in active]
    zones, run = [], [idx[0]]
    for i in idx[1:]:
        if i == run[-1] + 1:
            run.append(i)
        else:
            zones.append(run)
            run = [i]
    zones.append(run)
    out = [{'lower': cell(r[0])[0], 'upper': cell(r[-1])[1], 'strikes': [ks[i] for i in r],
            'oi': {ks[i]: oi.get(ks[i]) for i in r}} for r in zones]
    return {'zone': out, 'reason': None, 'expiry': frozen['expiry'], 'right': cluster['right'],
            'oi_published_ts': frozen['published_ts'], 'cluster_windows': cluster['member_ends']}
