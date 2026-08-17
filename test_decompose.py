"""Premium-move decomposition tests (addendum #14). Run: python test_decompose.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import decompose as dc

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── spot-driven: spot moved, premium tracks delta·ΔS ──")
# delta 0.5, spot +2.0 → delta_contrib ~+1.0; ΔP ~+1.0 → mostly spot-explained
r = dc.decompose(prev_mark=2.0, mark=3.0, delta=0.5, gamma=0.0, spot_prev=100.0, spot=102.0)
ck("driver SPOT_DRIVEN", r['driver'] == 'SPOT_DRIVEN')
ck("delta contribution ≈ +1.0", abs(r['delta_contrib'] - 1.0) < 1e-6)

print("── unexplained-driven: premium doubled with spot barely moving ──")
r = dc.decompose(prev_mark=1.0, mark=2.0, delta=0.4, gamma=0.0, spot_prev=100.0, spot=100.1)
ck("driver UNEXPLAINED_DRIVEN (not called 'IV' until greeks exist)", r['driver'] == 'UNEXPLAINED_DRIVEN')
ck("unexplained component carries most of the move", abs(r['unexplained_premium']) > abs(r['delta_contrib']))

print("── unknown when greeks missing ──")
ck("missing delta → UNKNOWN", dc.decompose(prev_mark=1.0, mark=2.0, delta=None, gamma=None,
                                            spot_prev=100.0, spot=101.0)['driver'] == 'UNKNOWN')

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
