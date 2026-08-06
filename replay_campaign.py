"""
Poll-by-poll campaign replay for a SPECIFIC contract (follow-up spec §18/§45).

Reconstructs one option's minute-by-minute story from real Alpaca 1-min bars — premium (bid/mid/ask
proxy), cumulative + fresh volume, fresh notional, underlying spot, running low, extension from the
local low, and MFE/MAE — then diagnoses WHEN the contract was cheap vs when it extended (the
detection-latency lens: was a winner discoverable early and cheap, and how much of the eventual
move was already gone by the time it looked 'obvious'?).

Usage:
    python replay_campaign.py NVDA 200 C 2026-08-03 [EXPIRY]
    python replay_campaign.py TSLA 315 C 2026-08-03
    python replay_campaign.py MSFT 490 C 2026-08-04
    python replay_campaign.py AAPL 305 C 2026-08-04
EXPIRY (YYYY-MM-DD) is optional; if omitted the tool probes same-day 0DTE, then that week's Friday,
then the next Friday, and uses the first with real bars.
"""
import sys
from datetime import date, datetime, timedelta

import requests

import config
from analysis import value
from data.alpaca_client import occ_symbol
from data.market_utils import CST

_H = {'APCA-API-KEY-ID': config.ALPACA_API_KEY, 'APCA-API-SECRET-KEY': config.ALPACA_SECRET_KEY}
_DATA = 'https://data.alpaca.markets'


def _get(url, params, tries=4):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=_H, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            last = exc
    raise last


def _epoch(iso):
    return datetime.fromisoformat(iso.replace('Z', '+00:00')).timestamp()


def stock_bars(sym, day):
    j = _get(f"{_DATA}/v2/stocks/{sym}/bars",
             {'timeframe': '1Min', 'start': f"{day}T13:29:00Z", 'end': f"{day}T20:01:00Z",
              'feed': 'sip', 'limit': 10000, 'sort': 'asc'})
    return [(_epoch(b['t']), float(b['c'])) for b in (j.get('bars') or [])]


def option_bars(occ, day):
    out = []
    j = _get(f"{_DATA}/v1beta1/options/bars",
             {'symbols': occ, 'timeframe': '1Min', 'start': f"{day}T13:29:00Z",
              'end': f"{day}T20:01:00Z", 'limit': 10000, 'sort': 'asc'})
    for b in (j.get('bars') or {}).get(occ, []):
        out.append((_epoch(b['t']), int(b['v']), float(b['vw'] or b['c']), float(b['l']), float(b['h'])))
    return out


def candidate_expiries(sym, day):
    d = date.fromisoformat(day)
    fri = d + timedelta(days=(4 - d.weekday()) % 7)
    picks = [d, fri, fri + timedelta(days=7)]
    seen, out = set(), []
    for e in picks:
        if e not in seen and e >= d:
            seen.add(e); out.append(e)
    return out


def _spot_at(spots, t):
    hit = None
    for s in spots:
        if s[0] <= t:
            hit = s[1]
        else:
            break
    return hit


def main():
    a = sys.argv[1:]
    if len(a) < 4:
        print(__doc__); sys.exit(1)
    sym, strike, cp, day = a[0].upper(), float(a[1]), a[2].upper(), a[3]
    side = 'CALL' if cp.startswith('C') else 'PUT'
    exps = [date.fromisoformat(a[4])] if len(a) > 4 else candidate_expiries(sym, day)

    spots = stock_bars(sym, day)
    series, used_exp, occ = [], None, None
    for e in exps:
        o = occ_symbol(sym, e, strike, side)
        b = option_bars(o, day)
        if b:
            series, used_exp, occ = b, e, o
            break
    label = f"{sym} {strike:g}{cp[0]} {day} (exp {used_exp}, {occ})"
    if not series:
        print(f"REPLAY {label}: no option bars found for any probed expiry ({exps}).")
        return

    print(f"REPLAY {label}   dte={(used_exp - date.fromisoformat(day)).days}")
    print(f"{'time':>6} {'prem':>7} {'freshV':>7} {'cumV':>8} {'freshNotl':>11} "
          f"{'spot':>8} {'low':>7} {'ext':>5} {'MFE%':>6} {'MAE%':>6}")
    prev_cum = 0
    run_low = None
    first_prem = None
    first_abn_t = None
    peak = None
    fresh_vals = []
    rows = []
    for (t, cum, mk, lo, hi) in series:
        fresh = max(0, cum - prev_cum); prev_cum = cum
        fresh_vals.append(fresh)
        if first_prem is None:
            first_prem = mk
        run_low = mk if run_low is None else min(run_low, mk)
        peak = mk if peak is None else max(peak, mk)
        ext = round(mk / run_low, 2) if run_low else 1.0
        mfe = round(100 * (peak / first_prem - 1), 0) if first_prem else 0
        mae = round(100 * (run_low / first_prem - 1), 0) if first_prem else 0
        pre_mean = (sum(fresh_vals[:-1]) / max(len(fresh_vals) - 1, 1)) if len(fresh_vals) > 1 else 0
        if first_abn_t is None and fresh > max(3 * pre_mean, 50):
            first_abn_t = t
        spot = _spot_at(spots, t)
        hh = datetime.fromtimestamp(t, tz=CST).strftime('%H:%M')
        rows.append((t, mk, ext, peak))
        print(f"{hh:>6} {mk:>7.2f} {fresh:>7d} {cum:>8d} {fresh*mk*100:>11,.0f} "
              f"{(spot or 0):>8.2f} {run_low:>7.2f} {ext:>5.2f} {mfe:>6.0f} {mae:>6.0f}")

    # ── diagnosis (§45) ──
    peak_t = max(rows, key=lambda r: r[3])[0]
    eventual_mfe = round(100 * (peak / first_prem - 1), 0) if first_prem else 0
    # first minute the contract looked "cheap" (extension <= the engine's chase gate)
    cheap_rows = [r for r in rows if r[2] <= config.GATE_MAX_DIST_FROM_LOW]
    first_cheap = cheap_rows[0][0] if cheap_rows else None
    # how much of the eventual MFE was already consumed once it left the cheap window
    print("\n-- diagnosis --")
    print(f"  first abnormal fresh-volume minute : "
          f"{datetime.fromtimestamp(first_abn_t, tz=CST).strftime('%H:%M') if first_abn_t else 'n/a'}")
    print(f"  first premium (event start)        : {first_prem:.2f}")
    print(f"  peak premium                       : {peak:.2f}  at "
          f"{datetime.fromtimestamp(peak_t, tz=CST).strftime('%H:%M')}  (eventual MFE {eventual_mfe:+.0f}%)")
    if first_cheap and first_abn_t:
        drift_at_abn = None
        # premium at first-abnormal vs first-premium → PremiumDrift by the time volume spiked
        abn_prem = next((r[1] for r in rows if r[0] >= first_abn_t), first_prem)
        drift_at_abn = round(abn_prem / first_prem, 2) if first_prem else 1.0
        print(f"  premium drift by first-abnormal    : {drift_at_abn:.2f}x  → CHASED verdict: "
              f"{value.classify_chased(drift_at_abn)}")
    print(f"  cheap window (ext<= {config.GATE_MAX_DIST_FROM_LOW}) lasted until : "
          f"{datetime.fromtimestamp(cheap_rows[-1][0], tz=CST).strftime('%H:%M') if cheap_rows else 'n/a'}")
    print("  (A long cheap window before the peak = the campaign was catchable early → any miss is "
          "detection latency, not an invalid setup.)")


if __name__ == '__main__':
    main()
