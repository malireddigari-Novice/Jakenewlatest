"""
One-shot data gather — capture a single Attention-Engine poll and print/save it.

This is exactly what the live loop does each minute, run once on demand: for every Mag-7 name
it reads spot + near-ATM option snapshots twice (`--interval` seconds apart, so the difference
is one interval's worth of FRESH contracts), turns that into fresh premium + call/put control,
builds the attention board, and shows what the entry gate would decide.

Usage:
  python gather.py                      # 60s gap (a true one-minute poll), label = now
  python gather.py --interval 10        # quick look (understates a full minute of flow)
  python gather.py --label 08:34        # tag the report with a clock time

On a closed market the fresh deltas are ~0 (nothing is trading), so the pool reads empty — the
live spots and cumulative volumes still print so you can confirm the feed works.
"""
import argparse
import json
import logging
import sys
import time
from datetime import datetime

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import config
from analysis import attention as at
from analysis.premium import PremiumTracker, symbol_attention_input
from data.alpaca_data_client import AlpacaDataClient
from data.market_utils import is_market_open, now_cst

logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')


def _read_all(data: AlpacaDataClient):
    """One read of spot + near-ATM snapshots for every Mag-7 name."""
    out = {}
    for sym in config.MAG7:
        spot = data.get_spot(sym)
        expiry = data.get_nearest_expiry(sym)
        if not spot or not expiry:
            print(f"  {sym:<5} no spot/expiry (feed issue or unlisted) — skipped")
            continue
        snaps = data.get_option_snapshots(sym, expiry, spot, config.PREMIUM_BAND_PCT)
        out[sym] = {'spot': spot, 'expiry': expiry, 'snaps': snaps}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--interval', type=int, default=60,
                    help='seconds between the two reads (a true poll is 60)')
    ap.add_argument('--label', default=None, help='clock label for the report, e.g. 08:34')
    args = ap.parse_args()

    now = now_cst()
    label = args.label or now.strftime('%H:%M')
    data = AlpacaDataClient()
    if not data.verify():
        print("Alpaca data feed unavailable — check ALPACA_* in .env.")
        sys.exit(1)

    open_now = is_market_open(now)
    print("=" * 70)
    print(f"ATTENTION GATHER  {label} CST   ({now:%Y-%m-%d %H:%M:%S})   "
          f"market {'OPEN' if open_now else 'CLOSED'}")
    print(f"reading twice, {args.interval}s apart, to measure fresh premium")
    print("=" * 70)

    tracker = PremiumTracker()
    tracker.new_session(now.date())

    print(f"\n[read 1] {now_cst():%H:%M:%S} — establishing baselines")
    r1 = _read_all(data)
    for sym, d in r1.items():
        tracker.contracts_with_deltas(sym, d['snaps'])   # sets baselines (deltas ignored)

    time.sleep(args.interval)

    print(f"[read 2] {now_cst():%H:%M:%S} — measuring the interval's fresh flow\n")
    r2 = _read_all(data)

    # Per-name fresh premium + control from the delta between reads.
    inputs = {}
    per_name = {}
    for sym, d in r2.items():
        contracts = tracker.contracts_with_deltas(sym, d['snaps'])
        fresh_ct = sum(c['delta_vol'] for c in contracts)
        ai = symbol_attention_input(contracts, d['spot'], config.PREMIUM_BAND_PCT)
        per_name[sym] = {'spot': d['spot'], 'expiry': d['expiry'].isoformat(),
                         'contracts_sampled': len(contracts), 'fresh_contracts': fresh_ct,
                         'input': ai}
        if ai and ai['premium'] > 0:
            inputs[sym] = ai

    # Per-name table.
    print(f"{'SYM':<6}{'SPOT':>9}{'EXPIRY':>12}{'#CTR':>6}{'FRESH':>8}"
          f"{'PREMIUM$':>13}{'CTRL':>7}{'SHARE':>7}")
    print("-" * 70)
    for sym in config.MAG7:
        p = per_name.get(sym)
        if not p:
            print(f"{sym:<6}{'—':>9}")
            continue
        ai = p['input']
        prem = f"${ai['premium']:,}" if ai else "$0"
        ctrl = ai['control_side'] if ai else '-'
        share = f"{100*ai['control_share']:.0f}%" if ai else '-'
        print(f"{sym:<6}{p['spot']:>9.2f}{p['expiry']:>12}{p['contracts_sampled']:>6}"
              f"{p['fresh_contracts']:>8}{prem:>13}{ctrl:>7}{share:>7}")

    # Attention board.
    weights = {'share': config.ATTENTION_W_SHARE, 'velocity': config.ATTENTION_W_VELOCITY,
               'acceleration': config.ATTENTION_W_ACCELERATION,
               'control': config.ATTENTION_W_CONTROL, 'low': config.ATTENTION_W_LOW}
    board = at.attention_board(inputs, weights=weights, min_total=config.ATTENTION_MIN_TOTAL,
                               score_min=config.ATTENTION_SCORE_MIN)

    print("\nATTENTION BOARD (this poll has no prior minute, so velocity/accel are neutral)")
    print(f"  pool fresh premium: ${board['total_premium']:,}   "
          f"(needs >= ${config.ATTENTION_MIN_TOTAL:,.0f} to allocate)")
    if board['ranked']:
        print(f"  {'#':<3}{'SYM':<7}{'SCORE':>6}{'SHARE':>7}{'CTRL':>6}{'>=70?':>7}")
        for r in board['ranked']:
            print(f"  {r['rank']:<3}{r['symbol']:<7}{r['attention_score']:>6.0f}"
                  f"{100*r['share']:>6.0f}%{(r['control_side'] or '-'):>6}"
                  f"{('yes' if r['above_threshold'] else 'no'):>7}")
    else:
        print("  (no fresh flow measured — nobody is pulling premium this interval)")

    # What the entry gate would do.
    leader = board['leader']
    print("\nENTRY DECISION")
    if not leader:
        reason = ("market closed / no fresh flow" if not inputs
                  else "pool below minimum or leader under score 70")
        print(f"  NO TRADE — no attention leader ({reason}).")
    else:
        row = board['by_symbol'][leader]
        sig = 'BULLISH' if row['control_side'] == 'CALL' else 'BEARISH'
        g = at.gate_signal(board, leader, sig, score_min=config.ATTENTION_SCORE_MIN,
                           require_control_agree=config.ATTENTION_GATE_REQUIRE_CONTROL,
                           max_rank=1 if config.ATTENTION_SINGLE_TRADE else config.ATTENTION_GATE_MAX_RANK)
        print(f"  Leader: {leader}  control={row['control_side']}  "
              f"score={row['attention_score']:.0f}  share={100*row['share']:.0f}%")
        print(f"  Gate: {g['decision']} ({g['reason']}) → "
              f"would buy the ATM {row['control_side']} on {leader}"
              if g['decision'] == 'KEEP' else f"  Gate: {g['decision']} ({g['reason']})")

    # Save the raw gather for the record.
    fname = f"gather_{now:%Y%m%d_%H%M}.json"
    with open(fname, 'w', encoding='utf-8') as fh:
        json.dump({'label': label, 'timestamp': now.isoformat(), 'market_open': open_now,
                   'interval_sec': args.interval, 'per_name': per_name, 'board': board},
                  fh, indent=2, default=str)
    print(f"\nsaved → {fname}")


if __name__ == '__main__':
    main()
