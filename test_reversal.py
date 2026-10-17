"""Stateful reversal-cluster tests (new-spec P3). Run: python test_reversal.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import reversal as rv

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1


def opp_event(strike=215, control=0.7, accept=True, cross=False, fail=False):
    return {'opp_abnormal': True, 'opp_control': control, 'opp_premium_accept': accept,
            'cross_strike': cross, 'incumbent_progress_fail': fail, 'opp_strike': strike}

QUIET = {'opp_abnormal': False, 'opp_control': 0.2, 'opp_premium_accept': False,
         'cross_strike': False, 'incumbent_progress_fail': False}

print("── a single opposite print does NOT flip the position ──")
cl = rv.new_cluster('NVDA', 'PUT')                 # holding NVDA puts; watch for a call reversal
cl = rv.update(cl, opp_event(215), 1000)
ck("one opposite event → OPPOSITE_FLOW_DETECTED (not a flip)", cl['state'] == 'OPPOSITE_FLOW_DETECTED')
ck("outcome is HOLD after a single print", rv.outcome(cl, opp_qualifies=True) == 'HOLD')

print("── evidence must accumulate to activate (NVDA 215C then 217.5C) ──")
cl = rv.update(cl, opp_event(217.5), 1060)         # 2nd opposite event → WATCH
ck("second opposite event → REVERSAL_WATCH", cl['state'] == 'REVERSAL_WATCH')
# confirmation: cross-strike (two strikes) + premium acceptance, sustained
cl = rv.update(cl, opp_event(217.5, cross=True), 1120)
cl = rv.update(cl, opp_event(217.5, cross=True), 1180)
ck("cross-strike + accepted, sustained → REVERSAL_CLUSTER_CONFIRMED",
   cl['state'] == 'REVERSAL_CLUSTER_CONFIRMED')
# activation: incumbent progress failing
cl = rv.update(cl, opp_event(217.5, cross=True, fail=True), 1240)
ck("confirmed + incumbent failing → REVERSAL_ACTIVATED", cl['state'] == 'REVERSAL_ACTIVATED')

print("── EXIT != REVERSE (safeguard #10) ──")
ck("ACTIVATED + opposite qualifies → EXIT_REVERSE", rv.outcome(cl, opp_qualifies=True) == 'EXIT_REVERSE')
ck("ACTIVATED + opposite does NOT qualify → EXIT_FLAT (invalidate, don't reverse)",
   rv.outcome(cl, opp_qualifies=False) == 'EXIT_FLAT')

print("── weak / fading opposite flow does not reach activation ──")
cl2 = rv.new_cluster('AAPL', 'CALL')
cl2 = rv.update(cl2, opp_event(310, control=0.5), 2000)   # control below REV_OPP_CONTROL_MIN → not an event
ck("opposite flow below control floor stays NONE", cl2['state'] == 'NONE')
cl3 = rv.new_cluster('AAPL', 'CALL')
cl3 = rv.update(cl3, opp_event(310), 3000)
for t in range(3060, 3300, 60):
    cl3 = rv.update(cl3, QUIET, t)                          # opposite flow fades
ck("faded opposite flow never reaches CONFIRMED/ACTIVATED",
   cl3['state'] in ('NONE', 'OPPOSITE_FLOW_DETECTED', 'REVERSAL_WATCH'))
ck("faded cluster outcome is HOLD", rv.outcome(cl3, opp_qualifies=True) == 'HOLD')

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
