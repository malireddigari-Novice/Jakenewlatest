"""
Tape-lane review (flow handoff §11): coverage and abstentions as well as positives.

  python tape_report.py [SESSION ...]

Reports, per session set: coverage incidents, print statuses and every side-abstention reason, UOA
candidates vs working hypotheses and why the leading read abstained, package candidates vs abstentions
by association grade, feed latency, and the precommitted research outcome (buy ask at observation, sell
bid at horizon, fees both sides) by DTE channel and side thesis — with sample size, the number of
independent CLUSTERS (repeated alerts on one campaign count once), and Wilson 95% intervals. Thresholds
are whatever RULE_VERSION was frozen at capture; nothing here re-infers the past with today's code.
"""
import json
import math
import sys
from collections import Counter, defaultdict

from tape.store import Store


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round((c - r) / d, 3), round((c + r) / d, 3))


def pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    return s[min(len(s) - 1, int(q / 100 * len(s)))]


def main(sessions) -> None:
    st = Store()
    where = f"WHERE session IN ({','.join('?' * len(sessions))})" if sessions else ''
    args = tuple(sessions)
    print("== prints ==")
    for status, n, v in st.q(f"SELECT status, COUNT(*), SUM(size) FROM prints {where} GROUP BY status", args):
        print(f"  {status:<18} {n:>8} prints {v or 0:>10} contracts")
    print("== side readings (abstentions included) ==")
    for side, reason, n in st.q(f"SELECT side, side_reason, COUNT(*) FROM prints {where} "
                                f"{'AND' if where else 'WHERE'} status='COUNTED' GROUP BY side, side_reason "
                                f"ORDER BY 3 DESC", args):
        print(f"  {side:<18} {reason or '-':<40} {n:>8}")
    lat = [r[0] for r in st.q(f"SELECT (recv_ns-event_ns)/1e6 FROM prints {where} {'AND' if where else 'WHERE'} "
                              f"source='stream'", args)]
    print(f"== feed latency (ms, stream prints): p50 {pct(lat, 50)} p95 {pct(lat, 95)} p99 {pct(lat, 99)}")
    print("== coverage incidents ==")
    for kind, rec, n in st.q(f"SELECT kind, recovery, COUNT(*) FROM incidents {where} GROUP BY kind, recovery", args):
        print(f"  {kind:<24} {rec or '-':<34} {n}")
    obs = st.q(f"SELECT obs_id, campaign_id, dims FROM observations {where}", args)
    fails, by_bucket, wh = Counter(), Counter(), 0
    camp_of = {}
    for oid, cid, d in obs:
        d = json.loads(d)
        camp_of[oid] = cid
        by_bucket[d['urgency']['channel']] += 1
        if d['side_thesis'].get('state') == 'WORKING_HYPOTHESIS':
            wh += 1
        for f in d.get('leading_read_fail') or []:
            fails[f] += 1
    print(f"== observations: {len(obs)} ({wh} working hypotheses) in {len(set(camp_of.values()))} campaigns ==")
    print("  by channel:", dict(by_bucket))
    print("  leading-read abstentions:", dict(fails.most_common()))
    print("== packages ==")
    for status, assoc, n in st.q(f"SELECT status, association, COUNT(*) FROM packages {where} "
                                 f"GROUP BY status, association", args):
        print(f"  {status:<20} {assoc or '-':<32} {n}")
    print("== research outcome (long the observed contract: ask in, bid out, fees) ==")
    rows = st.q("SELECT o.obs_id, o.horizon_min, o.net_per_contract, o.status, ob.dims FROM outcomes o "
                "JOIN observations ob ON ob.obs_id=o.obs_id" + (f" WHERE ob.session IN ({','.join('?' * len(sessions))})"
                                                               if sessions else ''), args)
    grp = defaultdict(list)
    status_n = Counter()
    for oid, h, net, status, d in rows:
        status_n[status] += 1
        if status != 'OK':
            continue
        d = json.loads(d)
        key = (h, d['urgency']['channel'], d['side_thesis'].get('side') or 'NEUTRAL')
        grp[key].append((camp_of.get(oid, oid), net))
    print("  outcome status:", dict(status_n))
    for (h, ch, side), vals in sorted(grp.items()):
        # cluster: one result per campaign (mean of its alerts) — repeated alerts are one trial
        per = defaultdict(list)
        for c, v in vals:
            per[c].append(v)
        cl = [sum(v) / len(v) for v in per.values()]
        k = sum(1 for v in cl if v > 0)
        lo, hi = wilson(k, len(cl))
        print(f"  +{h:>3}m {ch:<11} {side:<18} alerts {len(vals):>4} clusters {len(cl):>4} "
              f"positive {k}/{len(cl)} (95% CI {lo}-{hi}) mean ${sum(cl) / len(cl):,.0f}")
    print("No hit-rate claim is valid without an audited held-out sample and a named denominator.")


if __name__ == '__main__':
    main(sys.argv[1:])
