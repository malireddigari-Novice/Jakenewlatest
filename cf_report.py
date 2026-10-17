"""Old-versus-new shadow comparison for one session (both policies ran on the identical engine polls).

    python cf_report.py [YYYY-MM-DD] [--journal jakenew_campaign_flow.db] [--log jakenew.log]

New policy  (campaign-flow journal): window funnel and every rejection reason, value-band mix, candidates and
            WATCH reasons, proposals, campaigns with fills (SIM = simulated, never an execution), exit reasons,
            suppressed-candidate shadow marks (observations, not fills), OI freeze status, incidents.
Old policy  (legacy engine log + decision ledger): entries, exits and exit reasons; exits whose reason the
            revised policy removed (premium structure, generic exhaustion, percentage targets/trails/stops).
No hit-rate claim is made: the sample is a handful of campaigns and thresholds are uncalibrated.
"""
import argparse
import json
import os
import re
from collections import Counter
from datetime import date

from campaign_flow import calendar_ny as cal
from campaign_flow.journal import Journal

REMOVED = ('PREMIUM_STRUCTURE', 'EXHAUSTION', 'TRAIL', 'TP1', 'TP2', 'TARGET', 'HARD_STOP', 'STOP_LOSS',
           'GIVEBACK', 'SCALE')
_ENTER = re.compile(r"^(\S+ \S+) .*\[(LIVE|SHADOW)\] ENTER (\w+) (CALL|PUT) ([\d.]+) x(\d+) @ \$([\d.]+)")
_EXIT = re.compile(r"^(\S+ \S+) .*\[(LIVE|SHADOW)\] EXIT (\w+) (CALL|PUT) x(\d+) @ \$([\d.]+) \((\S+) ([+-]?\d+)%\)")


def legacy(session: str, log_path: str) -> dict:
    """Legacy log lines are in Central time; NY session date == CT date for regular hours."""
    out = {'entries': [], 'exits': []}
    if not os.path.exists(log_path):
        return out
    with open(log_path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if not line.startswith(session):
                continue
            m = _ENTER.match(line)
            if m:
                out['entries'].append({'time': m.group(1)[11:], 'ticker': m.group(3), 'side': m.group(4),
                                       'strike': float(m.group(5)), 'qty': int(m.group(6)), 'price': float(m.group(7))})
                continue
            m = _EXIT.match(line)
            if m:
                out['exits'].append({'time': m.group(1)[11:], 'ticker': m.group(3), 'side': m.group(4),
                                     'qty': int(m.group(5)), 'price': float(m.group(6)), 'reason': m.group(7),
                                     'pct': int(m.group(8))})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('session', nargs='?', default=None)
    ap.add_argument('--journal', default=None)
    ap.add_argument('--log', default='jakenew.log')
    a = ap.parse_args()
    j = Journal(a.journal)
    sess = a.session or max((c['session'] for c in j.campaigns()), default=date.today().isoformat())
    lo, hi = (cal.bounds(date.fromisoformat(sess)) or (0, 0))
    lo, hi = lo - 3600, hi + 3600
    within = lambda rows: [r for r in rows if lo <= r['ts'] <= hi]
    print(f"=== campaign-flow shadow report — session {sess} ===\n")

    wins = within(j.logs('WINDOW'))
    print(f"NEW POLICY — completed windows with volume: {len(wins)}")
    if wins:
        el = [w for w in wins if w['qual']['eligible']]
        ac = [w for w in el if w['qual']['accepted']]
        print(f"  eligible shocks {len(el)}  accepted (premium rose) {len(ac)}")
        rc = Counter(r for w in wins for r in w['qual']['reasons'])
        print("  rejection reasons (a window can have several):")
        for k, v in rc.most_common():
            print(f"    {k:<44} {v}")
        bands = Counter((w['value'] or {}).get('band') for w in wins)
        print(f"  value bands: {dict(bands)}")
        cs = Counter(w['complex_status'] for w in wins)
        print(f"  complex-leg status: {dict(cs)}")
    rej = within(j.logs('WINDOW_REJECTED'))
    if rej:
        print(f"  invalid windows: {dict(Counter(r for x in rej for r in x['reasons']))}")
    watch = within(j.logs('CANDIDATE_WATCH'))
    props = within(j.logs('PROPOSAL'))
    print(f"\n  candidates → WATCH {len(watch)}, PROPOSE {len(props)}")
    for k, v in Counter(r for w in watch for r in w['reasons']).most_common(12):
        print(f"    {k:<44} {v}")
    below = sum(1 for p in props if 'VERIFIED_CLUSTER_BELOW_SCORE_BOUNDARY' in p.get('logs', []))
    print(f"  proposals below the old 0.550 route boundary (logged, not vetoed): {below}")
    camps = [c for c in j.campaigns() if c['session'] == sess]
    print(f"\n  campaigns {len(camps)}")
    for c in camps:
        k = c['contract']
        fills = j.fills(c['campaign_id'])
        src = {f.get('source') for f in fills} or {'—'}
        ep = (c.get('exit_pending') or {}).get('reasons')
        print(f"    {c['campaign_id'][:8]} {c['ticker']} {k['strike']:g}{k['right']} {k['expiry']} {c['state']:<13} "
              f"planned {c['planned_qty']} filled {c['entry_filled_qty']} avg {c['avg_entry'] or 0:.2f} "
              f"exited {c['exit_filled_qty']} realized ${c['realized']:+.2f} fills={','.join(sorted(src))} exit={ep}")
    marks = [m for m in j.marks() if lo <= m['due_ts'] <= hi + 86400 and m.get('kind') == 'SUPPRESSED' and m.get('done')]
    if marks:
        print(f"\n  suppressed-candidate shadow marks (observations, never fills): {len(marks)}")
        for lab in ('+5m', '+15m', '+30m', 'session_close', 'next_open'):
            ms = [m for m in marks if m['label'] == lab and m.get('bid') and m.get('origin_ask')]
            if ms:
                ch = sorted(m['bid'] / m['origin_ask'] - 1 for m in ms)
                print(f"    {lab:<14} n={len(ms):<4} bid vs origin ask: median {ch[len(ch) // 2] * 100:+.1f}%  "
                      f"issues={dict(Counter(m.get('issue') for m in marks if m['label'] == lab))}")
    fz = within(j.logs('OI_FREEZE')) + within(j.logs('OI_FREEZE_MISSING'))
    if fz:
        print("\n  OI freeze: " + ', '.join(f"{x['ticker']}={x.get('expiry') or 'MISSING:' + str(x.get('reason'))}" for x in fz))
    inc = within(j.logs('INCIDENT')) + within(j.logs('RECONCILIATION_EXCEPTION'))
    if inc:
        print(f"  incidents: {len(inc)}")
    boards = within(j.logs('BOARD'))
    if boards:
        dis = sum(1 for b in boards if not b['scenario_leader_agrees'] and b.get('labels'))
        print(f"  board updates {len(boards)}, raw/discounted leader disagreement {dis}")

    old = legacy(sess, a.log)
    print(f"\nOLD POLICY — entries {len(old['entries'])}, exits {len(old['exits'])}")
    for e in old['entries']:
        print(f"    ENTER {e['time']} CT {e['ticker']} {e['strike']:g}{e['side'][0]} x{e['qty']} @ {e['price']:.2f}")
    removed = 0
    for x in old['exits']:
        rm = any(r in x['reason'] for r in REMOVED)
        removed += rm
        print(f"    EXIT  {x['time']} CT {x['ticker']} {x['side']} x{x['qty']} @ {x['price']:.2f} {x['reason']} "
              f"{x['pct']:+d}%{'   ← exit type removed by the revised policy' if rm else ''}")
    if old['exits']:
        print(f"  {removed}/{len(old['exits'])} legacy exits used a reason the revised policy no longer allows")
    print("\nSample sizes are tiny and thresholds uncalibrated — this is a shadow comparison, not a performance claim.")


if __name__ == '__main__':
    main()
