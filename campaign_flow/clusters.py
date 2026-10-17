"""§5 Verified campaign clusters and the per-ticker control state.

Calls and puts are assessed separately WITHIN each expiration (never pooled across expirations). Only
ACCEPTED shocks count (eligible + premium rose). A cluster is either
  PAIR         a local pair of neighbouring qualifying strikes qualifies in each of two independent,
               non-overlapping completed window slots (matching boundaries); gap / event spot <= 2.5%, or
  SAME_STRIKE  one strike qualifies in three independent, non-overlapping completed windows.
Successive member windows end <= 420 s apart, the latest member is <= 300 s old, and the flow snapshot is
<= 60 s old. Adjacency follows the reference: neighbouring QUALIFYING strikes with a spacing limit; it does
not check for an unlisted strike in between, and there is no ATM-distance gate.

Control: calls clustered + puts not + independent bullish underlying confirmation → BULLISH_CONTROL (mirror
for puts). Both clustered → CONTESTED. Anything incomplete, stale or future cannot certify.
"""
from collections import defaultdict

from campaign_flow import settings as S

WATCH, BULL, BEAR, CONTESTED = 'WATCH', 'BULLISH_CONTROL', 'BEARISH_CONTROL', 'CONTESTED'


def _chain_to_latest(ends: list) -> list:
    """Indices of the run (sorted by end) that finishes at the latest element with gaps <= max gap."""
    if not ends:
        return []
    run = [len(ends) - 1]
    for i in range(len(ends) - 2, -1, -1):
        if ends[run[-1]] - ends[i] <= S.CLUSTER_MAX_END_GAP_S:
            run.append(i)
        else:
            break
    return sorted(run)


def _usable(items, right, now_ts, since_ts=None, zero_resemblance=False, start_at_or_after=None):
    out = []
    for it in items:
        w, q = it['w'], it['q']
        if not q.get('accepted') or w['contract']['right'] != right:
            continue
        if float(w['end']) > now_ts or now_ts - float(w['end']) > S.FLOW_LOOKBACK_S:
            continue
        if since_ts is not None and float(w['start']) < since_ts:
            continue
        if start_at_or_after is not None and float(w['start']) < start_at_or_after:
            continue
        if zero_resemblance and (it.get('res') or {}).get('resemblance', 0) > 0:
            continue
        out.append(it)
    return out


def _pair_ok(a: float, b: float, spot) -> bool:
    return bool(spot) and spot > 0 and abs(b - a) / float(spot) <= S.PAIR_MAX_GAP_FRAC


def _slot_pairs(slot_items):
    """Neighbouring qualifying strike pairs inside one matching window slot."""
    by_strike = {}
    for it in slot_items:
        by_strike.setdefault(float(it['w']['contract']['strike']), it)
    ks = sorted(by_strike)
    for a, b in zip(ks, ks[1:]):
        spot = by_strike[a]['w'].get('spot') or by_strike[b]['w'].get('spot')
        if _pair_ok(a, b, spot):
            yield (a, b), (by_strike[a], by_strike[b])


def find(items, right, now_ts, since_ts=None) -> list:
    """All active clusters for one right across expirations (each expiration separately)."""
    usable = _usable(items, right, now_ts, since_ts)
    by_exp = defaultdict(list)
    for it in usable:
        by_exp[str(it['w']['contract']['expiry'])].append(it)
    clusters = []
    for exp, its in sorted(by_exp.items()):
        by_strike = defaultdict(list)
        for it in its:
            by_strike[float(it['w']['contract']['strike'])].append(it)
        for k, ws in sorted(by_strike.items()):
            ws.sort(key=lambda it: float(it['w']['end']))
            run = [ws[i] for i in _chain_to_latest([float(it['w']['end']) for it in ws])]
            if len(run) >= 3 and now_ts - float(run[-1]['w']['end']) <= S.CLUSTER_MAX_AGE_S:
                clusters.append(_record('SAME_STRIKE', exp, right, [k], run))
        slots = defaultdict(list)
        for it in its:
            slots[(float(it['w']['start']), float(it['w']['end']))].append(it)
        pair_slots = defaultdict(list)
        for slot, sits in slots.items():
            for pair, members in _slot_pairs(sits):
                pair_slots[pair].append((slot, members))
        for pair, entries in sorted(pair_slots.items()):
            entries.sort(key=lambda e: e[0][1])
            run = [entries[i] for i in _chain_to_latest([e[0][1] for e in entries])]
            if len(run) >= 2 and now_ts - run[-1][0][1] <= S.CLUSTER_MAX_AGE_S:
                members = [m for _, ms in run for m in ms]
                clusters.append(_record('PAIR', exp, right, list(pair), members))
    return clusters


def _record(kind, exp, right, strikes, members) -> dict:
    res = [(it.get('res') or {}).get('resemblance', 0.0) for it in members]
    amb = [it['w']['id'] for it in members if (it.get('res') or {}).get('resemblance', 0) > 0]
    return {'kind': kind, 'expiry': exp, 'right': right, 'strikes': strikes,
            'members': [it['w']['id'] for it in members],
            'member_ends': [float(it['w']['end']) for it in members],
            'first_start': min(float(it['w']['start']) for it in members),
            'latest_end': max(float(it['w']['end']) for it in members),
            'resemblance_max': max(res) if res else 0.0, 'ambiguous_members': amb,
            'last_ambiguous_end': max((float(it['w']['end']) for it in members
                                       if (it.get('res') or {}).get('resemblance', 0) > 0), default=None),
            'adjacency_rule': S.ADJACENCY_RULE}


def coverage_reasons(snapshot: dict, now_ts: float, expiries=None) -> list:
    r = []
    av = snapshot.get('available_ts')
    if av is None or float(av) > now_ts:
        r.append('FUTURE_OR_UNTIMED_SNAPSHOT')
    elif now_ts - float(av) > S.SNAPSHOT_MAX_AGE_S:
        r.append('STALE_FLOW_SNAPSHOT')
    cov = snapshot.get('coverage') or {}
    if not cov.get('strikes_complete'):
        r.append('INCOMPLETE_STRIKE_COVERAGE')
    covered = set(str(e) for e in (cov.get('expirations') or []))
    rights = cov.get('rights') or {}
    need = set(str(e) for e in (expiries or covered))
    if (not covered or not need <= covered or not cov.get('trade_quote_synced')
            or any(set(rights.get(e) or []) != {'C', 'P'} for e in need)):
        r.append('INCOMPLETE_TRADE_QUOTE_OR_EXPIRY_COVERAGE')
    return r


def underlying(snapshot: dict) -> dict:
    """Independent underlying confirmation flags; a bare boolean without upstream evidence does not count."""
    u = snapshot.get('underlying') or {}
    ev = u.get('evidence') or {}
    if not ev.get('rule') or ev.get('value') is None:
        return {'bullish': False, 'bearish': False, 'reason': 'UNDERLYING_CONFIRMATION_EVIDENCE_MISSING'}
    return {'bullish': bool(u.get('bullish')), 'bearish': bool(u.get('bearish')), 'reason': None}


def assess(snapshot: dict, items, now_ts: float, since_ts: float = None) -> dict:
    """Control state for one ticker from its full flow snapshot and evaluated windows."""
    calls = find(items, 'C', now_ts, since_ts)
    puts = find(items, 'P', now_ts, since_ts)
    exps = sorted({c['expiry'] for c in calls + puts})
    reasons = coverage_reasons(snapshot, now_ts, exps or None)
    u = underlying(snapshot)
    out = {'calls_clustered': bool(calls), 'puts_clustered': bool(puts), 'clusters': {'C': calls, 'P': puts},
           'certifiable': not reasons, 'underlying': u, 'reasons': list(reasons), 'state': WATCH}
    if calls and puts:
        out['state'] = CONTESTED
        out['reasons'].append('CONTESTED_BOTH_SIDES_CLUSTERING')
        return out
    if not calls and not puts:
        out['reasons'].append('NO_VERIFIED_CLUSTER')
        return out
    if reasons:
        return out
    if calls:
        if u['bullish']:
            out['state'] = BULL
        else:
            out['reasons'].append(u['reason'] or 'UNDERLYING_NOT_CONFIRMED')
    else:
        if u['bearish']:
            out['state'] = BEAR
        else:
            out['reasons'].append(u['reason'] or 'UNDERLYING_NOT_CONFIRMED')
    return out


def followthrough(items, cluster: dict, now_ts: float) -> dict:
    """§12.4: an opposite cluster with turnover overlap needs later, independent, UNMATCHED follow-through:
    a qualifying local pair in one later window slot, or one strike in two later windows <= 7 min apart.
    Later windows must start at/after the last ambiguous window ended and have zero resemblance."""
    last = cluster.get('last_ambiguous_end')
    if last is None:
        return {'needed': False, 'satisfied': True, 'last_ambiguous_end': None, 'evidence': []}
    later = [it for it in _usable(items, cluster['right'], now_ts, zero_resemblance=True,
                                  start_at_or_after=last)
             if str(it['w']['contract']['expiry']) == cluster['expiry']]
    ev = []
    slots = defaultdict(list)
    for it in later:
        slots[(float(it['w']['start']), float(it['w']['end']))].append(it)
    for slot, sits in sorted(slots.items()):
        for pair, _ in _slot_pairs(sits):
            ev.append({'kind': 'LATER_PAIR', 'strikes': list(pair), 'slot': list(slot)})
    by_strike = defaultdict(list)
    for it in later:
        by_strike[float(it['w']['contract']['strike'])].append(float(it['w']['end']))
    for k, ends in sorted(by_strike.items()):
        ends.sort()
        if any(b - a <= S.FOLLOWTHROUGH_MAX_GAP_S for a, b in zip(ends, ends[1:])):
            ev.append({'kind': 'LATER_SAME_STRIKE', 'strikes': [k]})
    return {'needed': True, 'satisfied': bool(ev), 'last_ambiguous_end': last, 'evidence': ev}
