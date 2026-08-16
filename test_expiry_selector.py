"""Expiry selector tests (v3-review #10). Run: python test_expiry_selector.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import expiry_selector as xs

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

rows = [
    {'dte': 0, 'share': 0.5, 'side': 'CALL'},
    {'dte': 1, 'share': 0.3, 'side': 'CALL'},
    {'dte': 4, 'share': 0.2, 'side': 'CALL'},
]

print("── early session intraday: 0DTE with most flow wins ──")
r = xs.select(rows, traded_side='CALL', minutes_since_open=20, campaign_horizon='INTRADAY')
ck("best is 0DTE early", r['best_dte'] == 0)

print("── late session: 0DTE theta penalty pushes to a later expiry ──")
r = xs.select(rows, traded_side='CALL', minutes_since_open=370, campaign_horizon='INTRADAY')
ck("late-day best is not 0DTE", r['best_dte'] != 0)

print("── multiday horizon rewards forward expiries ──")
r = xs.select(rows, traded_side='CALL', minutes_since_open=60, campaign_horizon='MULTIDAY')
ck("multiday best is a forward expiry", r['best_dte'] >= 1)

print("── theta burden ramps for 0DTE across the session ──")
early = xs.score_expiry({'dte': 0, 'share': 0.5, 'side': 'CALL'}, traded_side='CALL', minutes_since_open=10)
late = xs.score_expiry({'dte': 0, 'share': 0.5, 'side': 'CALL'}, traded_side='CALL', minutes_since_open=380)
ck("late 0DTE theta > early 0DTE theta", late['theta'] > early['theta'])

print("── no structure → default nearest ──")
ck("empty rows → best_dte None", xs.select([], traded_side='CALL', minutes_since_open=30)['best_dte'] is None)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
