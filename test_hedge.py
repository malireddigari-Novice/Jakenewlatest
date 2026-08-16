"""Hedge-flow (directional vs convexity) tests (addendum #13). Run: python test_hedge.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import hedge as hf

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── directional: spot confirms + premium responds ──")
r = hf.assess(iv_slope=0.0, spot_confirms=True, resp_event=0.2, delta=0.5)
ck("read DIRECTIONAL", r['read'] == 'DIRECTIONAL')
ck("no discount", r['mult'] == 1.0)

print("── convexity: IV bid, spot not confirming, far OTM ──")
r = hf.assess(iv_slope=0.05, spot_confirms=False, resp_event=0.15, delta=0.15)
ck("read CONVEXITY", r['read'] == 'CONVEXITY')
ck("convexity discount applied", r['mult'] == config.HEDGE_DISCOUNT)

print("── neutral / balanced ──")
r = hf.assess(iv_slope=None, spot_confirms=False, resp_event=0.0, delta=0.35)
ck("balanced → NEUTRAL, no discount", r['read'] == 'NEUTRAL' and r['mult'] == 1.0)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
