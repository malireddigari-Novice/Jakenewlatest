"""Inventory Memory Layer tests (addendum #1-4). Run: python test_inventory.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import inventory as inv
from analysis import campaign_store

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── no prior inventory: a fresh anomaly ──")
a = inv.assess(None, current_price=1.00, new_size=1000)
ck("fresh anomaly → LOW ambiguity, no discount", a['ambiguity'] == 'LOW' and a['discount'] == 1.0)
ck("fresh anomaly state UNKNOWN", a['state'] == 'UNKNOWN')

print("── the $3 → $1 case (unwind vs fresh is ambiguous) ──")
rec = None
rec = inv.observe(rec, price=3.00, size=1000, ts='2026-08-14T10:00:00')
ck("basis remembered ~3.00", abs(inv._basis(rec)['vwap'] - 3.00) < 1e-6)
a2 = inv.assess(rec, current_price=1.00, new_size=1000)   # 67% below basis
ck("print far below basis → HIGH ambiguity", a2['ambiguity'] == 'HIGH')
ck("HIGH ambiguity → heavy discount", a2['discount'] == config.INV_HIGH_DISCOUNT)
ck("HIGH ambiguity → LIKELY_PARTIAL_EXIT", a2['state'] == 'LIKELY_PARTIAL_EXIT')

print("── coherent build near basis ──")
a3 = inv.assess(rec, current_price=3.10, new_size=800)     # right at basis, premium advancing
ck("adding near basis → LOW ambiguity", a3['ambiguity'] == 'LOW')
ck("coherent build → no discount", a3['discount'] == 1.0)

print("── hidden slow exit: MFE goes weak ──")
# bought 1000 @ 1.00, premium later 5.00 but the contract has huge accumulated size → tiny marginal ΔP
big = inv.observe(None, price=1.00, size=1000, ts='t0')
for i in range(20):
    big = inv.observe(big, price=1.00, size=1000, ts=f't{i}')   # lots of same-price flow → basis stays ~1
mfe = inv.marginal_flow_efficiency(big, 1.00)                    # no premium progress at all
ck("no premium progress → MFE ≤ weak floor", mfe <= config.INV_MFE_WEAK)

print("── distribution into strength (far above basis + stalling marginal MFE) ──")
d = inv.observe(None, price=1.00, size=5000, ts='t0')   # big accumulation at 1.00
d = inv.observe(d, price=2.00, size=300, ts='t1')        # clip at the high (≥ record floor)
a4 = inv.assess(d, current_price=2.00, new_size=300)     # ran ~+90% above basis; latest clip no longer advances premium
ck("far above basis + stalling MFE → HIGH ambiguity", a4['ambiguity'] == 'HIGH')
ck("distribution-into-strength → LIKELY_PARTIAL_EXIT", a4['state'] == 'LIKELY_PARTIAL_EXIT')

print("── sub-floor prints are not remembered ──")
r = inv.observe(None, price=1.0, size=config.INV_EVENT_MIN_CONTRACTS - 1, ts='t')
ck("sub-floor print ignored (no basis)", inv._basis(r)['vwap'] is None)

print("── depletion model (#4) ──")
fund = inv.observe(None, price=1.00, size=5000, ts='t0')      # all accumulated at the low
ck("all near-low volume → LIKELY_FUNDED", inv.depletion(fund)['state'] == 'LIKELY_FUNDED')
ck("funded → remaining ~1.0", inv.depletion(fund)['remaining'] >= 0.99)
sold = inv.observe(fund, price=2.00, size=5000, ts='t1')      # half the volume printed up +100%
dep = inv.depletion(sold)
ck("large volume distributed high → not FUNDED", dep['state'] != 'LIKELY_FUNDED')
ck("distributed fraction rises", dep['distributed'] >= config.INV_DEPLETE_PARTIAL)
ck("no prints → INVENTORY_UNKNOWN", inv.depletion({'prints': []})['state'] == 'INVENTORY_UNKNOWN')

print("── micro-distribution (#5): small clips into strength, no ≥250 print needed ──")
# premium rose to a peak then sits near highs while modest volume keeps trading (quiet unwind)
marks_up = [1.0, 1.5, 2.5, 4.0, 5.0, 4.9, 4.95, 4.9, 4.92, 4.88]
small_clips = [1000, 0, 0, 0, 0, 120, 110, 130, 100, 115]     # clips of ~100 well under the 250 floor
md = inv.micro_distribution(small_clips, marks_up, est_campaign_vol=1000)
ck("chunked micro-distribution detected without any ≥250 clip", md['chunked'])
ck("state is LIKELY_DISTRIBUTING_IN_CHUNKS", md['state'] == 'LIKELY_DISTRIBUTING_IN_CHUNKS')
quiet_hold = [1000, 0, 0, 0, 0, 0, 0, 0, 0, 0]                 # no post-peak volume = self-sustaining, not exit
md2 = inv.micro_distribution(quiet_hold, marks_up, est_campaign_vol=1000)
ck("no post-peak clips → not chunked (self-sustaining is not distribution)", not md2['chunked'])

print("── prune keeps live-expiry records ──")
store = {inv.contract_key('NVDA', 'CALL', 220, '2026-08-14'): {'prints': []},
         inv.contract_key('NVDA', 'CALL', 220, '2020-01-01'): {'prints': []}}
kept = inv.prune(store, '2026-08-14', campaign_store.survives)
ck("expired-expiry record pruned", len(kept) == 1)
ck("live-expiry record kept", inv.contract_key('NVDA', 'CALL', 220, '2026-08-14') in kept)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
