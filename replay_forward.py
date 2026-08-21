"""
Forward-outcome replay (audit items 7-8) — research/labeling ONLY.

For every archived candidate in the Decision Ledger, fetch the REAL 1-minute option bars for its
contract and measure what happened AFTER the decision timestamp — using only future bars for
evaluation, never for the original decision features (strict no-leakage). Answers the two questions
the reject data alone cannot:

  • Near-miss cohort (SCORED 0.45-0.54, not entered): do these actually contain winners? Bucketed by
    route-score band and split by archetype/route.
  • Hard-veto cohort (DISTRIBUTION / EXIT_SHAPE / PREMIUM_REJECTION / OBJECTIVELY_LATE): what is the
    FALSE-VETO rate — how often did a vetoed event go on to a large favourable move?

Outputs +1/3/5/10/30-min returns, MFE, MAE, EOD return, time-to-MFE per candidate, then aggregates.
Expiry is reconstructed (0DTE guess → nearest-Friday fallback) for records predating the ledger's
candidate_expiry field. Prints a report and writes replay_forward_report.txt.

Run: python replay_forward.py            (all archived days)
     python replay_forward.py 2026-08-18 (one day)
"""
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.alpaca_client import occ_symbol
from backtest import option_bars                      # real 1-min Alpaca option bars

LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jakenew_decisions.jsonl')
HORIZONS = [('+1m', 60), ('+3m', 180), ('+5m', 300), ('+10m', 600), ('+30m', 1800)]


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    return xs[len(xs) // 2] if xs else None


def load_candidates(only_day=None):
    rows = []
    for line in open(LEDGER, encoding='utf-8'):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get('owner') == 'smoke':
            continue                                   # exclude test/smoke runs
        strike, ts = r.get('candidate_strike'), r.get('ts')
        if strike is None or not ts:
            continue
        if only_day and ts[:10] != only_day:
            continue
        owner = r.get('owner', '') or ''
        if 'MISSED_DUE_TO_LOW_ASYMMETRY' in owner:
            cat = 'NEAR_MISS'
        elif r.get('decision') == 'ALLOW':
            cat = 'ENTERED'
        elif 'ECONOMICALLY_VALID_REJECTION' in owner:
            cat = 'HARD_VETO'
        else:
            cat = 'OTHER'
        vetoes = r.get('route_hard_vetoes') or ([r.get('route_primary_veto')] if r.get('route_primary_veto') else [])
        rows.append({'ts': ts, 'day': ts[:10], 'sym': r.get('ticker'), 'side': r.get('side'),
                     'strike': float(strike), 'score': r.get('route_score'), 'route': r.get('route'),
                     'arch': r.get('event_archetype'), 'cat': cat, 'vetoes': vetoes,
                     'expiry': r.get('candidate_expiry')})
    return rows


def enrich_from_log(rows, logpath='jakenew_scheduled.log'):
    """Recover route + asym for records that predate the ledger's route_score field, by joining the
    scheduled log (has route=/asym= but no strike) to the ledger (has strike) on ts-minute+ticker+side."""
    import re
    if not os.path.exists(logpath):
        return
    pat = re.compile(r'^(\d{4}-\d\d-\d\d) (\d\d:\d\d):\d\d.*ENTRY-REJECT (\w+) (CALL|PUT) route=(\w+) asym=([0-9.]+)')
    lut = {}
    for line in open(logpath, encoding='utf-8', errors='ignore'):
        m = pat.match(line)
        if m:
            d, hm, sym, side, route, asym = m.groups()
            lut[(d, hm, sym, side)] = (route, float(asym))
    for r in rows:
        if r['score'] is not None:
            continue
        key = (r['day'], r['ts'][11:16], r['sym'], r['side'])
        if key in lut:
            r['route'], r['score'] = lut[key]


def _nearest_friday(day_str):
    d = date.fromisoformat(day_str)
    while d.weekday() != 4:
        d += timedelta(days=1)
    return d


def build_series(rows):
    """{(day,sym,strike,side): [(epoch,cumvol,mark,lo,hi)...]} — 0DTE guess then nearest-Friday."""
    out, by_day = {}, defaultdict(list)
    for r in rows:
        by_day[r['day']].append(r)
    for day, drows in by_day.items():
        uniq = {(r['sym'], r['strike'], r['side']): r for r in drows}
        # pass 1: expiry = the stored one, else the decision day (0DTE)
        occ_map = {}
        for (sym, strike, sd), r in uniq.items():
            exp = date.fromisoformat(r['expiry']) if r.get('expiry') else date.fromisoformat(day)
            occ_map[occ_symbol(sym, exp, strike, sd)] = (sym, strike, sd)
        got = set()
        try:
            for occ, ser in option_bars(list(occ_map), day).items():
                if ser:
                    out[(day,) + occ_map[occ]] = ser
                    got.add(occ_map[occ])
        except Exception as e:
            print(f"  [warn] bar fetch failed for {day} pass1: {e}")
        # pass 2: nearest-Friday for the misses (weekly-only names / non-0DTE days)
        miss = [k for k in uniq if k not in got]
        if miss:
            occ2 = {}
            fri = _nearest_friday(day)
            for (sym, strike, sd) in miss:
                occ2[occ_symbol(sym, fri, strike, sd)] = (sym, strike, sd)
            try:
                for occ, ser in option_bars(list(occ2), day).items():
                    if ser:
                        out[(day,) + occ2[occ]] = ser
            except Exception as e:
                print(f"  [warn] bar fetch failed for {day} pass2: {e}")
    return out


def forward(series, dec_ts):
    """Forward outcome from the decision ts using ONLY bars at/after it (no leakage)."""
    E = datetime.fromisoformat(dec_ts).timestamp()
    fut = [b for b in series if b[0] >= E]
    if len(fut) < 2:
        return None
    entry = fut[0][2]
    if not entry or entry <= 0:
        return None
    marks = [b[2] for b in fut if b[2]]
    def ret_at(h):
        for b in fut:
            if b[0] >= E + h and b[2]:
                return round(b[2] / entry - 1, 4)
        return round(fut[-1][2] / entry - 1, 4)
    peak = max(fut, key=lambda b: b[2] or 0)
    o = {'entry': round(entry, 3), 'mfe': round(max(marks) / entry - 1, 4),
         'mae': round(min(marks) / entry - 1, 4), 'eod': round(fut[-1][2] / entry - 1, 4),
         'ttm_min': round((peak[0] - E) / 60, 1)}
    for name, h in HORIZONS:
        o[name] = ret_at(h)
    return o


def _stat_block(items):
    """items: list of forward-outcome dicts. Returns a compact stats dict."""
    if not items:
        return {'N': 0}
    mfe = [i['mfe'] for i in items]
    mae = [i['mae'] for i in items]
    eod = [i['eod'] for i in items]
    return {'N': len(items),
            'win%_eod': round(100 * sum(1 for x in eod if x > 0) / len(eod)),
            'med_MFE': _median(mfe), 'med_MAE': _median(mae), 'med_EOD': _median(eod),
            'big_win%_MFE>50': round(100 * sum(1 for x in mfe if x > 0.5) / len(mfe)),
            'blowup%_MAE<-40': round(100 * sum(1 for x in mae if x < -0.4) / len(mae))}


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    rows = load_candidates(only)
    enrich_from_log(rows)                              # recover route/asym for pre-08/20 records
    cats = {c: sum(1 for r in rows if r['cat'] == c) for c in sorted(set(r['cat'] for r in rows))}
    print(f"loaded {len(rows)} archived candidates" + (f" for {only}" if only else "")
          + f" | categories: {cats}")
    series = build_series(rows)
    print(f"fetched forward bars for {len(series)} distinct contracts\n")

    out_lines = []
    def emit(s=""):
        print(s); out_lines.append(s)

    # attach forward outcomes
    for r in rows:
        key = (r['day'], r['sym'], r['strike'], r['side'])
        r['fwd'] = forward(series[key], r['ts']) if key in series else None
    covered = [r for r in rows if r['fwd']]
    emit(f"forward outcomes computed for {len(covered)}/{len(rows)} candidates "
         f"(missing = no bars for the reconstructed contract)\n")

    # ── NEAR-MISS cohort: by score band × route ──────────────────────────────────
    emit("=" * 78)
    emit("NEAR-MISS COHORT (scored 0.45-0.54, NOT entered) — do these contain winners?")
    emit("=" * 78)
    nm = [r for r in covered if r['cat'] == 'NEAR_MISS']
    def band(s):
        if s is None:
            return 'score_NA'
        return '0.45-0.49' if s < 0.50 else '0.50-0.54' if s < 0.55 else '0.55+'
    by_band = defaultdict(list)
    for r in nm:
        by_band[band(r['score'])].append(r['fwd'])
    for b in ('0.50-0.54', '0.45-0.49', 'score_NA'):
        if by_band.get(b):
            emit(f"  {b:10} {_stat_block(by_band[b])}")
    emit("  by route:")
    by_route = defaultdict(list)
    for r in nm:
        by_route[r['route'] or '?'].append(r['fwd'])
    for rt, items in sorted(by_route.items(), key=lambda kv: -len(kv[1])):
        emit(f"    {rt:18} {_stat_block(items)}")

    # ── ENTERED cohort (sanity: how did actual entries do?) ──────────────────────
    ent = [r['fwd'] for r in covered if r['cat'] == 'ENTERED']
    if ent:
        emit("\nENTERED cohort (actual paper entries): " + str(_stat_block(ent)))

    # ── HARD-VETO cohort: false-veto rate by family ──────────────────────────────
    emit("\n" + "=" * 78)
    emit("HARD-VETO COHORT — false-veto study (did vetoed events go on to move?)")
    emit("=" * 78)
    hv = [r for r in covered if r['cat'] == 'HARD_VETO']
    by_fam = defaultdict(list)
    for r in hv:
        for fam in (r['vetoes'] or ['UNKNOWN']):
            by_fam[fam or 'UNKNOWN'].append(r['fwd'])
    emit(f"  overall vetoed (with bars): {_stat_block([r['fwd'] for r in hv])}")
    for fam, items in sorted(by_fam.items(), key=lambda kv: -len(kv[1])):
        emit(f"    {fam:22} {_stat_block(items)}")

    emit("\nNOTE: 'win%_eod' = EOD return > 0; 'big_win%_MFE>50' = peak favourable move > +50% "
         "(a candidate we\n      passed that a runner would have caught); 'blowup%_MAE<-40' = drew "
         "down past the stop.\n      Forward metrics use ONLY post-decision bars — no look-ahead in "
         "any original feature.")

    with open('replay_forward_report.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(out_lines))
    print("\nwrote replay_forward_report.txt")


if __name__ == '__main__':
    main()
