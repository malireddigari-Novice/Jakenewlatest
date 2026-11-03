"""Replay one recorded campaign-flow session (cf_obs/<session>.jsonl) into a FRESH journal and report where
every candidate evaluation stops. Nothing touches the live journal, the broker or Discord (SHADOW, SimBroker).

    python cf_replay.py 2026-10-19                    # replay with receipt-time stamps (the fix)
    python cf_replay.py 2026-10-19 --as-recorded      # control: original stamps (reproduces the live result)
    python cf_replay.py 2026-10-19 --evidence 8       # timestamp evidence for N live-rejected candidates

TIMESTAMPS. A poll recorded after the timing fix carries `timing.recv_ts` (local receipt of the ticker's last
response) and its `ts` already equals it. A poll recorded BEFORE the fix (`timing` absent) was stamped at the
poll-cycle start, before any ticker was fetched. Its receipt time was not recorded, so the replay re-stamps it
conservatively:

    available_ts = min(next cycle start - 1 ms,  max(cycle start, newest quote/trade time in the poll) + PAD)

The newest quote in a snapshot is ~the server time of the request (a liquid chain always has a quote in the
last second), PAD covers the response time, and nothing can have arrived after the next cycle began. Original
values stay on the observation (`timing.poll_start_ts`, basis RESTAMPED_NEWEST_QUOTE_PLUS_PAD). Quotes that
lead the re-stamped time still fail QUOTE_FUTURE_DATED; stale quotes still fail QUOTE_STALE.
"""
import argparse
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict

os.environ['CF_MODE'] = 'SHADOW'
os.environ.setdefault('CF_DISCORD_ENABLED', 'false')
from campaign_flow import settings as S
from campaign_flow.executor import SimBroker
from campaign_flow.journal import Journal
from campaign_flow.pipeline import Pipeline

PAD_S = 1.0
ATTACHED = ('listing', 'value_refs', 'baseline', 'turnover')     # emitted by on_poll just before its poll

# Gate families, in pipeline order. Each evaluation is scored on EVERY family (not just the first that fails),
# so clearing one blocker shows what the next one is.
COVERAGE = {'INCOMPLETE_TRADE_QUOTE_OR_EXPIRY_COVERAGE', 'INCOMPLETE_STRIKE_COVERAGE', 'STALE_FLOW_SNAPSHOT',
            'FUTURE_OR_UNTIMED_SNAPSHOT', 'FUTURE_EVIDENCE'}
CLUSTERING = {'CONTESTED_BOTH_SIDES_CLUSTERING', 'NO_VERIFIED_CLUSTER'}
LIQUIDITY = {'SPREAD_TOO_WIDE', 'ASK_SIZE_TOO_SMALL', 'INVALID_QUOTE', 'QUOTE_STALE', 'QUOTE_MISSING',
             'QUOTE_FUTURE_DATED'}
EXPIRY = {'EXPIRES_BEFORE_PLANNED_END_PLUS_BUFFER', 'PLANNED_END_AFTER_EXPIRY_LIQUIDATION', 'WRONG_RIGHT_FOR_THESIS',
          'ADJUSTED_CONTRACT_MULTIPLIER_UNVERIFIED'}
RISK = {'NONPOSITIVE_PLANNED_QUANTITY', 'INSUFFICIENT_RESERVED_PREMIUM_CAPACITY', 'DAILY_ENTRY_PROPOSAL_CAP',
        'OPPOSITE_CAMPAIGN_OPEN_ROTATION_PATH_ONLY', 'ROTATION_SOURCE_NOT_FULLY_CLOSED', 'ROTATION_DIRECTION_MISMATCH',
        'PLANNED_END_NOT_IN_FUTURE', 'INVALID_HORIZON'}
PREMIUM = {'EXACT_CONTRACT_VALUE_HISTORY_MISSING', 'PREMIUM_OUTSIDE_LOW_VALUE_BAND', 'BASIS_MISMATCH', 'INVALID_PRICE',
           'HIGH_VALUE_FLOW_SELL_OR_CLOSE_POSSIBLE'}
CONCENTRATION = {'BELOW_MIN_CONTRACTS', 'BELOW_MIN_PRINTS', 'BELOW_VOLUME_SURPRISE', 'COMPARABLE_BASELINE_MISSING',
                 'NEAR_ASK_BELOW_MIN', 'NEAR_ASK_CLASSIFICATION_UNAVAILABLE', 'MISSING_EVENT_SHAPE_EXCLUDED',
                 'PERSISTENT_OR_DIFFUSE_BACKGROUND_EXCLUDED', 'KNOWN_COMPLEX_LEG_CONTAMINATION',
                 'WINDOW_LONGER_THAN_MAX', 'PRINT_COUNT_UNAVAILABLE', 'MISSING_EXPIRATION'}


def load(path):
    obs = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            try:
                obs.append(json.loads(line))
            except ValueError:
                continue                                # a torn last line from a crash
    return obs


def _newest(ob):
    """Newest quote/trade time in the poll that is not after the next cycle (an obviously bad stamp)."""
    out = None
    for c in ob['contracts'].values():
        for k in ('quote_ts', 'trade_ts'):
            v = c.get(k)
            if v is not None and (out is None or v > out):
                out = v
    return out


def restamp(obs):
    """Re-stamp polls recorded before the timing fix (see module doc). Returns (obs, per-poll rows)."""
    starts = sorted({o['ts'] for o in obs if o['kind'] == 'poll' and not o.get('timing')})
    nxt = {a: b for a, b in zip(starts, starts[1:])}
    out, pending, rows = [], [], []
    for o in obs:
        if o['kind'] in ATTACHED and not o.get('timing'):
            pending.append(o)
            continue
        if o['kind'] == 'poll' and not o.get('timing'):
            start = o['ts']
            newest = _newest(o)
            upper = nxt.get(start, start + 120.0) - 0.001
            est = min(upper, max(start, newest if newest is not None and newest <= upper + 60 else start) + PAD_S)
            o = {**o, 'ts': est, 'timing': {'poll_start_ts': start, 'recv_ts': None, 'estimated_available_ts': est,
                                            'basis': 'RESTAMPED_NEWEST_QUOTE_PLUS_PAD', 'pad_s': PAD_S}}
            rows.append({'ticker': o['ticker'], 'start': start, 'est': est, 'newest': newest})
            for p in pending:
                out.append({**p, 'ts': est} if p['ts'] == start else p)
            pending = []
            out.append(o)
            continue
        out.extend(pending)
        pending = []
        out.append(o)
    out.extend(pending)
    out.sort(key=lambda o: o['ts'])                      # stable: on_poll's attached rows stay before their poll
    return out, rows


def run(obs, path):
    j = Journal(path)
    p = Pipeline(j, SimBroker())
    for ob in obs:
        p.feed(ob)
    return j


def families(rec):
    """Every gate family this evaluation fails (assessed independently)."""
    a = rec.get('assessment') or {}
    rs = set(rec.get('reasons') or []) | set(a.get('reasons') or [])
    fam = set()
    if rs & COVERAGE:
        fam.add('coverage')
    if rs & CLUSTERING:
        fam.add('repeated clustering')
    u = a.get('underlying') or {}
    want = 'bullish' if rec['direction'] == 'BULLISH' else 'bearish'
    if not u.get(want):
        fam.add('underlying confirmation')
    cj = [set(x['reasons']) for x in rec.get('contract_journal') or []]
    ok = [r for r in cj if not r]
    if cj and not ok:                                    # an empty journal = no contract was evaluated
        if all(r & LIQUIDITY for r in cj):
            fam.add('contract liquidity')
        if all(r & EXPIRY for r in cj):
            fam.add('expiry')
    if rs & RISK:
        fam.add('risk')
    return fam


ORDER = ('coverage', 'repeated clustering', 'underlying confirmation', 'contract liquidity', 'expiry', 'risk')


def report(j, label):
    watch, props = j.logs('CANDIDATE_WATCH'), j.logs('PROPOSAL')
    rot = [r for r in watch if r.get('source_campaign_id')]       # rotation re-checks of a closed campaign
    watch = [r for r in watch if not r.get('source_campaign_id')]
    evals = watch + props
    print(f"\n=== {label} ===")
    wins, rej = j.logs('WINDOW'), j.logs('WINDOW_REJECTED')
    print(f"windows with volume {len(wins)}   invalid windows {len(rej)} "
          f"{dict(Counter(r for x in rej for r in x['reasons']).most_common(4))}")
    el = [w for w in wins if w['qual']['eligible']]
    acc = [w for w in el if w['qual']['accepted']]
    prem = sum(1 for w in wins if set(w['qual']['reasons']) & PREMIUM)
    conc = sum(1 for w in wins if set(w['qual']['reasons']) & CONCENTRATION)
    print(f"  premium history fails {prem}   concentration fails {conc}   eligible shocks {len(el)}   "
          f"accepted (premium rose) {len(acc)}")
    uniq = {(r['ticker'], r['direction'], tuple(sorted(m for cl in (r['assessment']['clusters'].get('C', [])
                                                                    + r['assessment']['clusters'].get('P', []))
                                                       for m in cl['members'][:1])))
            for r in evals}
    print(f"candidate evaluations {len(evals)}  (unique ticker/direction/cluster-anchor {len(uniq)})  "
          f"-> WATCH {len(watch)}  PROPOSE {len(props)}")
    if rot:
        print(f"  (+{len(rot)} rotation re-checks of closed campaigns, reported separately: "
              f"{dict(Counter(x for r in rot for x in r['reasons']).most_common(3))})")
    caps = Counter(x for r in watch for x in r['reasons'] if x in RISK)
    if caps:
        print(f"  risk/cap reasons: {dict(caps)}")
    fam = [families(r) for r in watch]
    passed_cov = [f for f in fam if 'coverage' not in f]
    print(f"  pass coverage: {len(passed_cov)} of {len(watch)} WATCH evaluations")
    print("  fails each gate (an evaluation can fail several):")
    for g in ORDER:
        print(f"    {g:<26} {sum(1 for f in fam if g in f)}")
    first = Counter(next((g for g in ORDER if g in f), 'none of the listed gates') for f in fam)
    print("  first gate it stops at (pipeline order):")
    for g in ORDER + ('none of the listed gates',):
        if first.get(g):
            print(f"    {g:<26} {first[g]}")
    nxt = Counter(next((g for g in ORDER if g in f), 'PASS') for f in passed_cov)
    if passed_cov:
        print("  of those passing coverage, where they stop next:", dict(nxt))
    cj = Counter(x for r in watch for c in r.get('contract_journal') or [] for x in c['reasons'])
    print(f"  contract-level reasons: {dict(cj.most_common(8))}")
    by = defaultdict(Counter)
    for r in watch:
        by[r['ticker']][r['direction']] += 1
    print(f"  by ticker: {{{', '.join(f'{t}: {dict(v)}' for t, v in sorted(by.items()))}}}")
    for p in props:
        print(f"  PROPOSAL {p['ticker']} {p['direction']} {p['contract']['occ']} x{p['qty']} @ {p['indicative_ask']}")
    tm = j.logs('QUOTE_TIMING')
    if tm:
        print(f"  QUOTE_TIMING rows (quotes leading decision time > {S.QUOTE_CLOCK_TOL_S}s): {len(tm)}")
    return evals


def evidence(obs, live_journal, n):
    """For N live-rejected candidates: poll start, quote event time, receipt (estimated), snapshot and decision."""
    from datetime import datetime
    import pytz
    ct = pytz.timezone('America/Chicago')
    f = lambda t: datetime.fromtimestamp(t, ct).strftime('%H:%M:%S.%f')[:-3] if t else '-'
    polls = {(o['ticker'], o['ts']): o for o in obs if o['kind'] == 'poll'}
    _, rows = restamp([dict(o) for o in obs])
    est = {(r['ticker'], r['start']): r['est'] for r in rows}
    cycle = defaultdict(list)
    for r in rows:
        cycle[r['start']].append(r)
    j = Journal(live_journal)
    recs = [r for r in j.logs('CANDIDATE_WATCH') if any('QUOTE_FUTURE_DATED' in c['reasons']
                                                        for c in r.get('contract_journal') or [])]
    step = max(1, len(recs) // n)
    print(f"\nTIMESTAMP EVIDENCE - {len(recs)} live candidates had QUOTE_FUTURE_DATED; {min(n, len(recs))} sampled "
          f"(times CT)")
    print(f"{'ticker':<6} {'cycle start':<13} {'#':>1} {'quote event':<13} {'lead s':>7} {'est. receipt':<13} "
          f"{'snapshot':<13} {'decision':<13} newest-in-poll - cycle start")
    for r in recs[::step][:n]:
        occ = r['contract_journal'][0]['occ']
        po = polls.get((r['ticker'], r['ts']))
        q = (po or {}).get('contracts', {}).get(occ, {}).get('quote_ts')
        order = sorted(cycle.get(r['ts'], []), key=lambda x: x['est'])
        idx = next((i for i, x in enumerate(order) if x['ticker'] == r['ticker']), None)
        e = est.get((r['ticker'], r['ts']))
        print(f"{r['ticker']:<6} {f(r['ts']):<13} {idx if idx is not None else '?':>1} {f(q):<13} "
              f"{(q - r['ts']) if q else 0:>+7.2f} {f(e):<13} {f(r['ts']):<13} {f(r['ts']):<13} "
              f"{(e - PAD_S - r['ts']) if e else 0:+.2f}s")
    lead = [(o['ticker'], c['quote_ts'] - o['ts']) for o in obs if o['kind'] == 'poll' and not o.get('timing')
            for c in o['contracts'].values() if c.get('quote_ts') is not None]
    pos = sorted(x for _, x in lead if x > 0)
    print(f"\nall recorded quotes: {len(lead)}; stamped after their poll's stamp: {len(pos)} "
          f"({len(pos) / max(1, len(lead)):.0%}); lead p50 {pos[len(pos) // 2]:.2f}s  p90 {pos[9 * len(pos) // 10]:.2f}s  "
          f"max {pos[-1]:.2f}s")
    pos_ix = defaultdict(list)
    for start, rs in cycle.items():
        for i, x in enumerate(sorted(rs, key=lambda x: x['est'])):
            pos_ix[i].append(x['est'] - PAD_S - start)
    print("newest quote in the poll - cycle start, by fetch position in the cycle (sequential fetch => grows):")
    for i in sorted(pos_ix):
        v = sorted(pos_ix[i])
        print(f"  position {i}: median {v[len(v) // 2]:+.2f}s  (n={len(v)})")
    print("units: epoch SECONDS (Alpaca RFC-3339 ns trimmed to us, UTC 'Z' -> aware datetime). A timezone error would "
          "show as +-3600*k s offsets; the leads are 0–32 s and grow with fetch position. Clock: w32tm vs "
          "time.windows.com +0.05 s; Alpaca HTTP Date vs local within its 1 s resolution.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('session')
    ap.add_argument('--obs-dir', default=S.OBS_DIR)
    ap.add_argument('--as-recorded', action='store_true')
    ap.add_argument('--both', action='store_true', help='run the control AND the re-stamped replay')
    ap.add_argument('--evidence', type=int, default=0)
    ap.add_argument('--live-journal', default=S.JOURNAL_DB)
    a = ap.parse_args()
    path = os.path.join(a.obs_dir, f"{a.session}.jsonl")
    obs = load(path)
    print(f"{path}: {len(obs)} observations, {sum(o['kind'] == 'poll' for o in obs)} polls, rules {S.RULE_VERSION}")
    if a.evidence:
        evidence(obs, a.live_journal, a.evidence)
        return
    if a.as_recorded or a.both:
        report(run(obs, tempfile.mktemp(suffix='.db')), 'CONTROL - original stamps (poll-cycle start)')
    if not a.as_recorded:
        fixed, rows = restamp([dict(o) for o in obs])
        d = sorted(r['est'] - r['start'] for r in rows)
        if d:
            print(f"\nre-stamped {len(rows)} polls: available - cycle start p50 {d[len(d) // 2]:.2f}s  "
                  f"p90 {d[9 * len(d) // 10]:.2f}s  max {d[-1]:.2f}s")
        report(run(fixed, tempfile.mktemp(suffix='.db')), 'REPLAY - receipt-time stamps (fix)')


if __name__ == '__main__':
    sys.exit(main())
