"""Event-level provenance tests (v3-canonicalization #17). Run: python test_event_memory.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import event_memory as em
from analysis import campaign_store

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── events are recorded immutably, never merged ──")
store = {}
store = em.record(store, ticker='NVDA', side='PUT', strike=222.5, expiry='2026-08-18', ts='t1',
                  size=1000, price=3.0, spot=220.0, shape='CONCENTRATED_SINGLE_STRIKE_EVENT',
                  direction_hyp='FRESH_DIRECTIONAL', inventory_hyp='LIKELY_FUNDED')
store = em.record(store, ticker='NVDA', side='PUT', strike=222.5, expiry='2026-08-18', ts='t2',
                  size=1000, price=1.0, spot=224.0, shape='DOMINANT_STANDALONE',
                  direction_hyp='CLOSING_PROFITABLE', inventory_hyp='LIKELY_PARTIAL_EXIT')
evs = em.events_for(store, 'NVDA', 'PUT', 222.5, '2026-08-18')
ck("both distinct events retained (superposition preserved)", len(evs) == 2)
ck("first event keeps its original price/hypothesis", evs[0]['price'] == 3.0 and evs[0]['direction_hyp'] == 'FRESH_DIRECTIONAL')
ck("second event has its own distinct hypothesis", evs[1]['inventory_hyp'] == 'LIKELY_PARTIAL_EXIT')

print("── same-minute re-observation is idempotent (no duplicate) ──")
store = em.record(store, ticker='NVDA', side='PUT', strike=222.5, expiry='2026-08-18', ts='t2',
                  size=1000, price=1.0, spot=224.0)
ck("re-recording the same ts does not duplicate", len(em.events_for(store, 'NVDA', 'PUT', 222.5, '2026-08-18')) == 2)

print("── each event carries immutable provenance fields ──")
e = evs[0]
for f in ('event_id', 'ts', 'size', 'price', 'spot', 'shape', 'direction_hyp', 'inventory_hyp'):
    ck(f"event has {f}", f in e)

print("── prune drops dead expiries ──")
store2 = {em.contract_key('X', 'CALL', 1, '2020-01-01'): [{'event_id': 'x'}]}
ck("expired contract pruned", len(em.prune(store2, '2026-08-16', campaign_store.survives)) == 0)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
