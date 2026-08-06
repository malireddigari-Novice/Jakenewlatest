"""Local-value / latency-diagnosis tests (follow-up §11-12). Run: python test_value.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import value

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── local value + extension ──")
ck("prefers campaign-start premium", value.local_value(marks=[5, 6, 7], campaign_start=3.0) == 3.0)
ck("falls back to event VWAP", value.local_value(marks=[5, 6, 7], event_vwap=4.0) == 4.0)
ck("falls back to a local median", value.local_value(marks=[5.0, 6.0, 7.0]) == 6.0)
ck("extension = mark / reference", value.extension(6.0, 3.0) == 2.0)
ck("extension safe on bad ref", value.extension(6.0, 0) == 1.0)

print("── CHASED sub-classification (§11) ──")
ck("large premium drift since capture → DETECTION_LATENCY",
   value.classify_chased(1.6) == 'MISSED_DUE_TO_DETECTION_LATENCY')
ck("little drift (extended when found) → PRICE_EXTENSION",
   value.classify_chased(1.05) == 'MISSED_DUE_TO_PRICE_EXTENSION')

print("── notional aggregation label (§12) ──")
ck("cluster would have covered the floor → CLUSTER_AGGREGATION",
   value.notional_reject_label(2.0e4, 5.0e5, 5.5e4) == 'MISSED_DUE_TO_CLUSTER_AGGREGATION')
ck("even the cluster is thin → SINGLE_STRIKE_NOTIONAL",
   value.notional_reject_label(2.0e4, 3.0e4, 5.5e4) == 'MISSED_DUE_TO_SINGLE_STRIKE_NOTIONAL')

print("── latency metrics ──")
lm = value.latency_metrics(
    stamps={'first_abnormal': 0, 'sustained': 30, 'eligible': 60, 'alert': 180, 'fill': 185},
    premiums={'accumulation': 1.0, 'eligible': 1.2, 'alert': 2.0, 'fill': 2.1},
    eventual_mfe=4.0)
ck("detection latency = alert − sustained", lm['detection_latency_s'] == 150)
ck("decision latency = alert − eligible", lm['decision_latency_s'] == 120)
ck("premium drift = alert / accumulation", lm['premium_drift'] == 2.0)
ck("convexity consumed before alert is a fraction in (0,1]",
   0 < lm['convexity_consumed_before_alert'] <= 1.0)
ck("empty stamps never crash", isinstance(value.latency_metrics({}, {}), dict))

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
