"""Event-information contract selection tests (new-spec P4). Run: python test_contract_select.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import contract_select as cs

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1


def strike(k, mark, bid=None, ask=None, bsz=50, asz=50, low=None, high=None):
    bid = mark - 0.05 if bid is None else bid
    ask = mark + 0.05 if ask is None else ask
    return {'strike': k, 'mark': mark, 'bid': bid, 'ask': ask,
            'bid_size': bsz, 'ask_size': asz,
            'day_low': (low if low is not None else mark * 0.9),
            'day_high': (high if high is not None else mark * 1.2)}


print("── event_score ──")
sd = strike(222.5, 2.00)
sig_shock = {'shock': 6.0, 'significant': True}
no_shock  = {'shock': 0.0, 'significant': False}
s_hi = cs.event_score(sd, 222.5, sig_shock)
s_lo = cs.event_score(sd, 222.5, no_shock)
ck("significant shock scores higher than no shock", s_hi > s_lo)
ck("score is in [0,1]", 0.0 <= s_hi <= 1.0)
ck("unquotable contract → None", cs.event_score({'strike': 1, 'mark': None}, 222.5, no_shock) is None)

print("── relevance: nearer-ATM strike preferred, all else equal ──")
near = strike(222.0, 2.00)
far  = strike(225.0, 2.00)
ck("nearer strike scores higher on relevance",
   cs.event_score(near, 222.0, no_shock) > cs.event_score(far, 222.0, no_shock))

print("── select: high-information strike beats the noisier neighbor ──")
spot = 221.0
# 220P is closest to ATM but quiet; 222.5P carries the significant event → should win.
strikes = [
    strike(220.0, 3.00),                       # ATM-ish, no event
    strike(222.5, 2.00, low=1.90, high=2.60),  # the event strike
    strike(217.5, 4.50),
]
shocks = {220.0: no_shock, 222.5: sig_shock, 217.5: no_shock}
# widen the window so 222.5 (2nd nearest here) is eligible
_win = config.EVENT_SELECT_WINDOW
config.EVENT_SELECT_WINDOW = 2
best = cs.select('PUT', strikes, spot, shocks)
config.EVENT_SELECT_WINDOW = _win
ck("select returns a contract", best is not None)
ck("event strike (222.5) chosen over quiet ATM (220)", best and best['strike'] == 222.5)
ck("chosen contract flagged event_selected", best and best.get('event_selected'))
ck("carries an event_score", best and best.get('event_score') is not None)
ck("carries low_score + is_atm", best and 'low_score' in best and 'is_atm' in best)

print("── select: nothing quotable → None ──")
ck("no quotable strikes → None", cs.select('PUT', [{'strike': 1, 'mark': None}], spot, {}) is None)
ck("empty input → None", cs.select('PUT', [], spot, {}) is None)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
