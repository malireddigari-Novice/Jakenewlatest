"""Package / Leg / Roll Resolver tests (addendum #7-8, v3-review #14 probabilistic). Run: python test_packages.py"""
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
vols = {(335.0, 'CALL'): 5000, (340.0, 'CALL'): 100}
r = pk.resolve(335.0, 'CALL', vols, SPOT)
ck("lone large print → OUTRIGHT_LIKELY", r['label'] == 'OUTRIGHT_LIKELY' and not r['leg'])
ck("outright → complex_prob 0, no discount", r['complex_prob'] == 0.0 and r['discount'] == 1.0)

print("── vertical: adjacent same-side size-matched → probabilistic, not a hard veto ──")
vols = {(335.0, 'CALL'): 10000, (340.0, 'CALL'): 10000}
r = pk.resolve(335.0, 'CALL', vols, SPOT)
ck("labelled VERTICAL_LIKELY", r['label'] == 'VERTICAL_LIKELY')
ck("has a complex_prob in (0,1)", 0 < r['complex_prob'] < 1.0)
ck("single vertical match is NOT hard-veto strength", not r['leg'])          # 0.55 < PKG_VETO_MIN_CONF
ck("discount scales with complex_prob (between PKG_DISCOUNT and 1)",
   config.PKG_DISCOUNT <= r['discount'] < 1.0)

print("── overwhelming package → hard-veto strength ──")
# straddle (call+put matched) + adjacent vertical → complex prob saturates to 1.0
vols = {(335.0, 'CALL'): 8000, (335.0, 'PUT'): 8000, (340.0, 'CALL'): 8000}
r = pk.resolve(335.0, 'CALL', vols, SPOT)
ck("overwhelming complex_prob ≥ veto threshold", r['complex_prob'] >= config.PKG_VETO_MIN_CONF)
ck("leg True only when overwhelming", r['leg'])

print("── roll: cross-expiry size-match ──")
r = pk.resolve(335.0, 'CALL', {(335.0, 'CALL'): 9000}, SPOT, cross_expiry_vol={(335.0, 'CALL'): 9000})
ck("cross-expiry match → ROLL_LIKELY", r['label'] == 'ROLL_LIKELY')

print("── probabilities present and outright complements complex ──")
r = pk.resolve(335.0, 'CALL', {(335.0, 'CALL'): 10000, (340.0, 'CALL'): 10000}, SPOT)
ck("probs dict present", 'probs' in r and 'OUTRIGHT' in r['probs'])
ck("outright ≈ 1 − complex", abs(r['probs']['OUTRIGHT'] - (1 - r['complex_prob'])) < 0.01)

print("── sub-floor traded leg is not resolvable ──")
r = pk.resolve(335.0, 'CALL', {(335.0, 'CALL'): config.PKG_MIN_LEG_CONTRACTS - 1}, SPOT)
ck("sub-floor → OUTRIGHT, not a leg", r['label'] == 'OUTRIGHT_LIKELY' and not r['leg'])

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
