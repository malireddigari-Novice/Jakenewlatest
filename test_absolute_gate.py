"""Absolute entry-quality gate tests (handoff Priority 1). Run: python test_absolute_gate.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import absolute_gate as ag

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

config.ABS_GATE_ENABLED = True
config.ABS_MIN_SCORE = 50
config.ABS_MIN_DOMINANCE = 0.60

print("── case-study calibration: winners pass, losers WATCH ──")
ck("NVDA 94 / 0.73 → AUTHORIZED", ag.authorize(94, 0.73)['authorized'])
ck("TSLA 75 / 0.66 → AUTHORIZED", ag.authorize(75, 0.66)['authorized'])
ck("AAPL 49 / 0.57 → WATCH (weak score AND weak dominance)", not ag.authorize(49, 0.57)['authorized'])
ck("MSFT 47 / 0.54 → WATCH", not ag.authorize(47, 0.54)['authorized'])
ck("META 42 / 0.80 → WATCH (score fails even though dominance strong)", not ag.authorize(42, 0.80)['authorized'])

print("── lean classification (0.54-0.60 is a LEAN, not control) ──")
ck("0.73 → CONTROL", ag.lean(0.73) == 'CONTROL')
ck("0.57 → WEAK_LEAN", ag.lean(0.57) == 'WEAK_LEAN')
ck("0.55 → WEAK_LEAN (the NVDA-0.55 case)", ag.lean(0.55) == 'WEAK_LEAN')
ck("0.45 → BALANCED", ag.lean(0.45) == 'BALANCED')

print("── verdict + reasons ──")
r = ag.authorize(49, 0.57)
ck("verdict is WATCH_WEAK_ABSOLUTE", r['verdict'] == 'WATCH_WEAK_ABSOLUTE')
ck("both failure reasons reported", len(r['reasons']) == 2)
ck("strong signal verdict AUTHORIZED_ENTRY", ag.authorize(94, 0.73)['verdict'] == 'AUTHORIZED_ENTRY')

print("── gate disabled → always authorized ──")
config.ABS_GATE_ENABLED = False
ck("disabled → authorized", ag.authorize(10, 0.51)['authorized'])
config.ABS_GATE_ENABLED = True

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
