"""Rotation resolver tests (spec §23-24). Run: python test_rotation.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import rotation as rt

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

ranked = [
    {'symbol': 'TSLA', 'attention_score': 86.0, 'dominant_side': 'CALL', 'call_control': 0.7, 'put_control': 0.3},
    {'symbol': 'GOOGL', 'attention_score': 40.0, 'dominant_side': 'PUT', 'call_control': 0.2, 'put_control': 0.6},
]
prev = {'TSLA': 45.0, 'GOOGL': 38.0}   # TSLA accelerating +41, GOOGL flat +2
cand = {'TSLA': {'barshock': {'significant': True, 'event_type': 'COORDINATED_CHAIN'},
                 'surface': {'breadth': 3}}}

print("── AAPL exit → TSLA is the rotation destination ──")
d = rt.resolve('AAPL', ranked, prev, cand, {})
ck("destination is TSLA CALL", d['ticker'] == 'TSLA' and d['side'] == 'CALL')
ck("delta reflects the +41 acceleration", d['delta'] >= 40)

print("── the ticker we just left is excluded ──")
d2 = rt.resolve('TSLA', ranked, prev, cand, {})
ck("TSLA excluded → not chosen", d2.get('ticker') != 'TSLA')

print("── no accelerating destination → None ──")
d3 = rt.resolve('AAPL', ranked, {'TSLA': 85.0, 'GOOGL': 39.0}, cand, {})   # nobody accelerating
ck("flat board → no destination", d3.get('ticker') is None)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
