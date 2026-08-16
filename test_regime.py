"""Regime-context tests (addendum #17). Run: python test_regime.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import regime as rg

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── ordinary session is neutral ──")
r = rg.assess('2026-08-17')
ck("no tags → NORMAL, mult 1.0", r['regime'] == 'NORMAL' and r['mult'] == 1.0)

print("── macro-event day is a confidence modifier, not a gate ──")
config.REGIME_EVENT_DATES = ['2026-08-17']
r = rg.assess('2026-08-17')
ck("event date → MACRO_EVENT tag", 'MACRO_EVENT' in r['regime'])
ck("event mult < 1 (more cautious) but > 0 (never a gate)", 0 < r['mult'] < 1.0)

print("── high realized vol adds caution ──")
r = rg.assess('2026-08-18', realized_vol=0.9, high_vol_threshold=0.5)
ck("high vol → HIGH_VOL tag + mult < 1", 'HIGH_VOL' in r['regime'] and r['mult'] < 1.0)

config.REGIME_EVENT_DATES = []
print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
