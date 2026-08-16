"""Expiry-value / cross-expiry / overnight-carry tests (spec §36, addendum #6/#8). Run: python test_expiry_value.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import expiry_value as xv

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── late-day 0DTE theta penalty ──")
early = xv.late_day_0dte_value(0, 20, strength=0.8, activation=0.8, remaining_convexity=0.8)
late = xv.late_day_0dte_value(0, 360, strength=0.8, activation=0.8, remaining_convexity=0.8)
ck("early 0DTE has ~no theta risk", early['theta_risk'] < 0.05)
ck("late 0DTE carries high theta risk", late['theta_risk'] > 0.5)
ck("late 0DTE value < early value", late['value'] < early['value'])
ck("non-0DTE is unpenalised", xv.late_day_0dte_value(3, 360, strength=0.8, activation=0.8, remaining_convexity=0.8)['theta_risk'] == 0.0)

print("── late-0DTE gate ──")
ok_e, _ = xv.late_day_0dte_ok(early)
ok_l, _ = xv.late_day_0dte_ok(late)
ck("strong early 0DTE passes", ok_e)
ck("weak late 0DTE vetoed", not ok_l)

print("── cross-expiry direction ──")
rows = [{'key': '2026-08-15', 'share': 0.5, 'side': 'CALL'},
        {'key': '2026-08-22', 'share': 0.3, 'side': 'CALL'}]
conf = xv.cross_expiry_direction('CALL', rows)
ck("forward expiries agree → CONFIRM + bonus", conf['verdict'] == 'CONFIRM' and conf['bonus'] > 0)
rows2 = [{'key': '2026-08-15', 'share': 0.5, 'side': 'PUT'},
         {'key': '2026-08-22', 'share': 0.3, 'side': 'PUT'}]
conf2 = xv.cross_expiry_direction('CALL', rows2)
ck("forward expiries oppose → CONFLICT + penalty mult<1", conf2['verdict'] == 'CONFLICT' and conf2['mult'] < 1.0)

print("── overnight carry ──")
camp = {'side': 'CALL'}
ck("same-side control persists → CONTINUATION",
   xv.overnight_carry(camp, 'CALL', 0.7, 1.05) == 'CONTINUATION')
ck("opposite controls open → REVERSAL",
   xv.overnight_carry(camp, 'PUT', 0.7, 1.0) == 'REVERSAL')
ck("same side but premium gapped down → OPENING_MONETIZATION",
   xv.overnight_carry(camp, 'CALL', 0.4, 0.6) == 'OPENING_MONETIZATION')

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
