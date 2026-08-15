"""Portfolio correlation risk layer tests (addendum #18). Run: python test_portfolio.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import portfolio as pf

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

def pos(side, qty=10, price=1.0, delta=0.5):
    return {'side': side, 'qty': qty, 'entry_price': price, 'delta': delta}

print("── exposure aggregation ──")
held = [pos('CALL'), pos('CALL'), pos('PUT')]
e = pf.exposure(held)
ck("counts 2 CALL / 1 PUT", e['n_call'] == 2 and e['n_put'] == 1)
ck("net Δ-notional is long (CALLs > PUTs)", e['net_delta_notional'] > 0)

print("── gate allows within cap ──")
g = pf.gate('CALL', [pos('CALL')])           # one existing long-tech, cap default 4
ck("second correlated CALL allowed", g['ok'])

print("── gate vetoes at the correlated-side cap ──")
many = [pos('CALL') for _ in range(config.PORT_MAX_CORR_SIDE)]
g = pf.gate('CALL', many)
ck("adding beyond cap same-direction is vetoed", not g['ok'])
ck("veto reason mentions concentration", 'cap' in g['reason'] or 'concentrat' in g['reason'])

print("── opposite direction is not blocked by same-direction crowd ──")
g = pf.gate('PUT', many)                      # many CALLs should not block a PUT
ck("PUT allowed despite many CALLs", g['ok'])

print("── empty book always allows ──")
ck("empty book allows entry", pf.gate('CALL', [])['ok'])

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
