"""Package / Leg / Roll Resolver tests (addendum #7-8). Run: python test_packages.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import packages as pk

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

SPOT = 335.0

print("── outright: no size-matched co-print ──")
vols = {(335.0, 'CALL'): 5000, (340.0, 'CALL'): 100}   # neighbor is sub-floor
r = pk.resolve(335.0, 'CALL', vols, SPOT)
ck("lone large print → OUTRIGHT_LIKELY", r['label'] == 'OUTRIGHT_LIKELY' and not r['leg'])
ck("outright → no discount", r['discount'] == 1.0)

print("── vertical: adjacent same-side size-matched ──")
vols = {(335.0, 'CALL'): 10000, (340.0, 'CALL'): 10000}
r = pk.resolve(335.0, 'CALL', vols, SPOT)
ck("size-matched adjacent same-side → VERTICAL_LIKELY", r['label'] == 'VERTICAL_LIKELY' and r['leg'])
ck("vertical → discounted", r['discount'] == config.PKG_DISCOUNT)

print("── straddle/combo: same strike call+put matched ──")
vols = {(335.0, 'CALL'): 8000, (335.0, 'PUT'): 8000}
r = pk.resolve(335.0, 'CALL', vols, SPOT)
ck("call+put same strike matched → STRADDLE_COMBO_LIKELY", r['label'] == 'STRADDLE_COMBO_LIKELY')

print("── ratio: ~2:1 size ratio adjacent ──")
vols = {(335.0, 'CALL'): 10000, (337.5, 'CALL'): 5000}
r = pk.resolve(335.0, 'CALL', vols, SPOT)
ck("~2:1 adjacent → RATIO_LIKELY", r['label'] == 'RATIO_LIKELY' and r['leg'])

print("── roll: same strike/side matched in a neighboring expiry ──")
vols = {(335.0, 'CALL'): 9000}
xexp = {(335.0, 'CALL'): 9000}
r = pk.resolve(335.0, 'CALL', vols, SPOT, cross_expiry_vol=xexp)
ck("cross-expiry size-match → ROLL_LIKELY", r['label'] == 'ROLL_LIKELY' and r['leg'])

print("── sub-floor traded leg is not resolvable ──")
vols = {(335.0, 'CALL'): config.PKG_MIN_LEG_CONTRACTS - 1}
r = pk.resolve(335.0, 'CALL', vols, SPOT)
ck("sub-floor → OUTRIGHT, not a leg", r['label'] == 'OUTRIGHT_LIKELY' and not r['leg'])

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
