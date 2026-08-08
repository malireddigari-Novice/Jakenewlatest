"""Cross-session campaign memory tests (new-spec P1). Run: python test_campaign_store.py"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import campaign_store as cs

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── identity + survival ──")
ck("campaign_id is (ticker,side,origin,strike)",
   cs.campaign_id('AMZN', 'CALL', '2026-08-06', 270) == 'AMZN-CALL-20260806-270')
# A Friday-expiry campaign is still alive ON Friday (0DTE) but not Saturday.
ck("expiry alive today (0DTE) survives", cs.survives('2026-08-07', date(2026, 8, 7)))
ck("expiry in the past does NOT survive", not cs.survives('2026-08-07', date(2026, 8, 8)))

print("── carry-forward across the session boundary (the AMZN Thu→Fri case) ──")
thu = {'AMZN-CALL-20260806-270': cs.record('AMZN', 'CALL', 270, '2026-08-07', '2026-08-06', 0.9, 'ACTIVE'),
       'NVDA-CALL-20260806-200': cs.record('NVDA', 'CALL', 200, '2026-08-06', '2026-08-06', 0.8, 'ACTIVE'),  # 0DTE Thu
       'TSLA-PUT-20260806-300':  cs.record('TSLA', 'PUT', 300, '2026-08-07', '2026-08-06', 0.7, 'EXITED')}   # terminal
carried = cs.carry_forward(thu, date(2026, 8, 7))
ck("surviving-expiry campaign is carried into Friday",
   'AMZN-CALL-20260806-270' in carried and carried['AMZN-CALL-20260806-270']['overnight'] is True)
ck("Thursday 0DTE campaign is dropped (expired)", 'NVDA-CALL-20260806-200' not in carried)
ck("a terminal (EXITED) campaign is not carried", 'TSLA-PUT-20260806-300' not in carried)
ck("carried campaign is marked OVERNIGHT_INTACT",
   carried['AMZN-CALL-20260806-270']['overnight_state'] == 'OVERNIGHT_INTACT')

print("── overnight opposite-side hysteresis ──")
opp = cs.opposite_inherited(carried, 'AMZN', 'PUT')   # a Friday PUT vs the inherited CALL campaign
ck("a Friday PUT sees the inherited AMZN CALL campaign (raises its bar)",
   opp is not None and opp['side'] == 'CALL')
ck("a Friday CALL sees no opposite inherited campaign for AMZN",
   cs.opposite_inherited(carried, 'AMZN', 'CALL') is None)

print("── overnight classification ──")
ck("alive expiry → OVERNIGHT_INTACT",
   cs.classify_overnight(cs.record('AMZN', 'CALL', 270, '2026-08-08', '2026-08-06', 0.9, 'ACTIVE'), date(2026, 8, 7)) == 'OVERNIGHT_INTACT')
ck("terminal → OVERNIGHT_<state>",
   cs.classify_overnight({'state': 'COMPLETED', 'expiry': '2026-08-08'}, date(2026, 8, 7)) == 'OVERNIGHT_COMPLETED')

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
