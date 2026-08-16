"""Data-quality / quote-sync tests (addendum #11-12). Run: python test_dataquality.py"""
import os
import sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import dataquality as dq

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

now = datetime(2026, 8, 15, 9, 0, 0, tzinfo=timezone.utc)
fresh = now.isoformat()
stale = (now - timedelta(seconds=120)).isoformat()

print("── clean snapshot ──")
v = dq.validate({'bid': 1.95, 'ask': 2.00, 'mark': 1.98, 'quote_ts': fresh}, now)
ck("clean → ok, full confidence", v['ok'] and v['confidence'] == 1.0 and not v['drop'])

print("── crossed quote is dropped ──")
v = dq.validate({'bid': 2.10, 'ask': 2.00, 'mark': 2.05, 'quote_ts': fresh}, now)
ck("crossed → flagged + dropped", 'CROSSED' in v['flags'] and v['drop'])

print("── no/zero mark dropped ──")
ck("zero mark dropped", dq.validate({'bid': 1.0, 'ask': 1.1, 'mark': 0}, now)['drop'])

print("── wide spread lowers confidence but not dropped ──")
v = dq.validate({'bid': 1.00, 'ask': 3.00, 'mark': 2.00, 'quote_ts': fresh}, now)
ck("wide spread → confidence reduced", v['confidence'] < 1.0 and 'WIDE_SPREAD' in v['flags'])
ck("wide spread not dropped", not v['drop'])

print("── stale quote lowers confidence ──")
v = dq.validate({'bid': 1.95, 'ask': 2.00, 'mark': 1.98, 'quote_ts': stale}, now)
ck("stale quote → STALE flag + lower confidence", 'STALE_QUOTE' in v['flags'] and v['confidence'] < 1.0)

print("── mark outside the book ──")
v = dq.validate({'bid': 1.95, 'ask': 2.00, 'mark': 2.50, 'quote_ts': fresh}, now)
ck("mark out of book flagged", 'MARK_OUT_OF_BOOK' in v['flags'])

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
