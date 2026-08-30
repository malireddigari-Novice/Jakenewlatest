"""Opposite-side flip-workflow tests (handoff P5). Run: python test_flip.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analysis import reversal

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── flip_plan only fires on EXIT_REVERSE (activated + opposite qualifies) ──")
cl = reversal.new_cluster('NVDA', 'CALL')
ck("not activated → no flip", reversal.flip_plan(cl, True)['flip'] is False)

cl['state'] = 'REVERSAL_ACTIVATED'
ck("activated but opposite does NOT qualify → EXIT_FLAT, no flip",
   reversal.flip_plan(cl, False)['flip'] is False)

plan = reversal.flip_plan(cl, True)
ck("activated + opposite qualifies → FLIP_PENDING", plan['flip'] and plan['state'] == 'FLIP_PENDING')
ck("flip names the correct direction (CALL→PUT)",
   plan['from_side'] == 'CALL' and plan['to_side'] == 'PUT' and plan['ticker'] == 'NVDA')
ck("flip carries a hand-off reason", isinstance(plan.get('reason'), str) and 'recompute' in plan['reason'])

print("── outcome semantics unchanged ──")
ck("EXIT_REVERSE when opposite qualifies", reversal.outcome(cl, True) == 'EXIT_REVERSE')
ck("EXIT_FLAT when opposite does not qualify", reversal.outcome(cl, False) == 'EXIT_FLAT')
cl['state'] = 'REVERSAL_WATCH'
ck("HOLD before activation", reversal.outcome(cl, True) == 'HOLD')

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
