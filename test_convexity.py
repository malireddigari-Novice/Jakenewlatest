"""Remaining-convexity ranking tests (handoff P2). Run: python test_convexity.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import convexity as cx
from analysis import contract_select as cs

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

SPOT = 566.0

print("── gamma-per-premium ──")
ck("cheap high-gamma > expensive low-gamma per premium",
   cx.gamma_per_premium(0.03, 0.60) > cx.gamma_per_premium(0.02, 6.45))
ck("no gamma/mark → 0", cx.gamma_per_premium(None, 6.45) == 0.0)

print("── META case: cheap 570C should out-rank expensive 565C on convexity ──")
c565 = {'strike': 565.0, 'mark': 6.45, 'gamma': 0.02, 'day_low': 5.0, 'day_high': 7.0}   # expensive, near high
c570 = {'strike': 570.0, 'mark': 0.60, 'gamma': 0.03, 'day_low': 0.45, 'day_high': 1.8}  # cheap, reset, high gamma/$
ck("570C convexity_score > 565C", cx.convexity_score(c570, SPOT) > cx.convexity_score(c565, SPOT))

print("── ranker picks the best convexity-per-dollar ──")
best = cx.best([c565, c570], SPOT)
ck("best is the 570C", best['strike'] == 570.0 and 'convexity_score' in best)

print("── wired into contract_select (wider ATM±window, convexity term) ──")
config.CONVEXITY_SELECT_ENABLED = True
shk = {565.0: {'shock': 3.0, 'significant': True}, 570.0: {'shock': 3.0, 'significant': True},
       590.0: {'shock': 3.0, 'significant': True}}
strikes = [dict(c565, bid=6.4, ask=6.5, bid_size=50, ask_size=50),
           dict(c570, bid=0.59, ask=0.61, bid_size=80, ask_size=80)]   # tight spread, dramatically cheaper gamma
sel = cs.select('CALL', strikes, SPOT, shocks=shk)
ck("selector returns a contract with convexity_score", sel is not None and 'convexity_score' in sel)
ck("selector prefers the cheaper high-convexity 570C over the pricey 565C", sel['strike'] == 570.0)

print("── far-OTM lottery guard: a 590C must NOT win over a good near-ATM strike ──")
c590 = {'strike': 590.0, 'mark': 0.05, 'gamma': 0.005, 'day_low': 0.03, 'day_high': 0.4,
        'bid': 0.04, 'ask': 0.06, 'bid_size': 200, 'ask_size': 200}
sel2 = cs.select('CALL', [dict(c565, bid=6.4, ask=6.5, bid_size=50, ask_size=50),
                          dict(c570, bid=0.59, ask=0.61, bid_size=80, ask_size=80), c590], SPOT, shocks=shk)
ck("far-OTM 590C lottery does NOT win", sel2['strike'] != 590.0)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
