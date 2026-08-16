"""Contract value memory tests (v3-review #4). Run: python test_value_memory.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import value_memory as vm
from analysis import campaign_store

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── empty history is neutral (new contract not penalised) ──")
a = vm.assess(None, current_mark=1.0)
ck("no history → is_cheap True, neutral", a['is_cheap'] and a['robust_low'] is None)

print("── robust low ignores a single bad print ──")
rec = None
for m in [3.0, 3.1, 2.9, 3.05, 2.95, 3.0, 3.2]:
    rec = vm.observe(rec, mark=m, ts='t')
rec = vm.observe(rec, mark=0.05, ts='t')     # one corrupt low print
a = vm.assess(rec, current_mark=3.0)
ck("robust low is not the $0.05 corrupt print", a['robust_low'] > 0.5)

print("── cheapness percentile ──")
rec2 = None
for m in [1.0, 1.5, 2.0, 2.5, 3.0]:
    rec2 = vm.observe(rec2, mark=m, ts='t')
lo = vm.assess(rec2, current_mark=1.0)
hi = vm.assess(rec2, current_mark=3.0)
ck("cheapest mark → low cheapness pctile", lo['cheapness'] <= 0.3)
ck("richest mark → high cheapness pctile", hi['cheapness'] >= 0.9)
ck("cheapest is flagged is_cheap", lo['is_cheap'])
ck("richest is NOT cheap", not hi['is_cheap'])

print("── state-adjusted ratio isolates non-spot cheapening ──")
rec3 = vm.observe(None, mark=2.0, spot=100.0, ts='t0')
# spot fell 2 pts, delta 0.5 → expected mark ~1.0; actual 1.0 → ratio ~1.0 (fully explained by spot)
a = vm.assess(rec3, current_mark=1.0, current_delta=0.5, current_spot=98.0)
ck("move fully explained by spot → ratio ~1.0", a['state_adjusted_ratio'] is not None and abs(a['state_adjusted_ratio'] - 1.0) < 0.15)
# actual 0.5 when spot move only explains 1.0 → genuinely cheaper than spot explains → ratio < 1
a2 = vm.assess(rec3, current_mark=0.5, current_delta=0.5, current_spot=98.0)
ck("cheaper than spot explains → ratio < 1", a2['state_adjusted_ratio'] < 1.0)

print("── prune by expiry ──")
store = {vm.contract_key('NVDA', 'CALL', 220, '2026-08-16'): {'samples': []},
         vm.contract_key('NVDA', 'CALL', 220, '2020-01-01'): {'samples': []}}
kept = vm.prune(store, '2026-08-16', campaign_store.survives)
ck("expired pruned, live kept", len(kept) == 1)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
