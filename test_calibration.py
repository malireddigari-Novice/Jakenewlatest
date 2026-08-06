"""Probability calibration tests (Phase 8). Run: python test_calibration.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import calibration as cal

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── metrics ──")
# Perfectly calibrated toy set: prob p appears, outcome 1 with frequency p.
perfect = []
for p, n in [(0.1, 100), (0.5, 100), (0.9, 100)]:
    pos = round(p * n)
    perfect += [(p, 1)] * pos + [(p, 0)] * (n - pos)
ck("Brier is low for a well-calibrated set", cal.brier_score(perfect) < 0.2)
ck("ECE near zero for a well-calibrated set", cal.ece(perfect) < 0.02)

# A miscalibrated set: always predicts 0.9 but only 10% actually happen.
bad = [(0.9, 1)] * 10 + [(0.9, 0)] * 90
ck("ECE high for an over-confident set", cal.ece(bad) > 0.5)
ck("Brier worse for the bad set than the good set", cal.brier_score(bad) > cal.brier_score(perfect))

print("── reliability + deciles ──")
rc = cal.reliability_curve(perfect, bins=10)
ck("reliability curve returns one row per bin", len(rc) == 10)
pop = [r for r in rc if r['n']]
ck("populated bins have mean_pred ≈ frac_pos",
   all(abs(r['mean_pred'] - r['frac_pos']) < 0.06 for r in pop))
dec = cal.decile_table(perfect)
ck("top predicted decile continues more than the bottom decile (rank ordering)",
   dec[-1]['realized'] >= dec[0]['realized'] and dec[-1]['mean_pred'] >= dec[0]['mean_pred'])

print("── report + empty safety ──")
rep = cal.report(perfect)
ck("report carries n / base_rate / brier / ece / deciles",
   rep['n'] == 300 and 'base_rate' in rep and 'brier' in rep and 'ece' in rep and rep['deciles'])
import math
ck("empty input never crashes (NaN metrics, empty tables)",
   math.isnan(cal.brier_score([])) and cal.decile_table([]) == [] and cal.report([])['n'] == 0)

print("── archive matching ──")
recs = [
    {'symbol': 'NVDA', 'side': 'CALL', 'decision': 'ENTERED', 'cont_prob': 0.7, 'archetype': 'SHOCK_ACCUMULATION'},
    {'symbol': 'NVDA', 'side': 'CALL', 'decision': 'EXIT', 'pnl': 0.25},
    {'symbol': 'AAPL', 'side': 'PUT', 'decision': 'ENTERED', 'cont_prob': 0.6, 'archetype': 'PERSISTENT_ACCUMULATION'},
    {'symbol': 'AAPL', 'side': 'PUT', 'decision': 'EXIT', 'pnl': -0.30},
]
pairs, skipped = cal.pairs_from_archive(recs)
ck("archive matching pairs ENTERED→EXIT with win/loss outcome",
   pairs == [(0.7, 1), (0.6, 0)] and skipped == 0)
sl = cal.slice_reports(recs, by='archetype')
ck("slice reports split by archetype", set(sl) == {'SHOCK_ACCUMULATION', 'PERSISTENT_ACCUMULATION'})

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
