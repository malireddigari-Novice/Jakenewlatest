"""Campaign end-taxonomy tests (addendum #21). Run: python test_campaign_taxonomy.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import campaign_store as cs

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

ck("TP2 profit → REALIZED_PROFIT", cs.classify_end('STRUCTURAL_TP2', pnl=1.2) == 'REALIZED_PROFIT')
ck("stop loss → FAILED", cs.classify_end('STOP_LOSS', pnl=-0.4) == 'FAILED')
ck("distribution exit → DISTRIBUTED", cs.classify_end('DISTRIBUTION_EXIT', pnl=0.1) == 'DISTRIBUTED')
ck("reversal → ROLLED", cs.classify_end('REVERSAL_ACTIVATED', pnl=0.0) == 'ROLLED')
ck("EOD profitable → EXPIRED_PROFITABLY", cs.classify_end('EOD_FLATTEN', pnl=0.3) == 'EXPIRED_PROFITABLY')
ck("EOD losing → FAILED", cs.classify_end('EOD_FLATTEN', pnl=-0.1) == 'FAILED')
ck("carried overnight overrides → CARRIED_OVERNIGHT", cs.classify_end('EOD_FLATTEN', pnl=0.3, carried=True) == 'CARRIED_OVERNIGHT')
ck("unknown reason, no pnl → UNKNOWN", cs.classify_end('MYSTERY') == 'UNKNOWN')

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
