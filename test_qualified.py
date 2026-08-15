"""Qualified directional control tests (new-spec 8/11 NVDA). Run: python test_qualified.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import qualified as q

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── side_quality ──")
# concentrated event with premium ABSORPTION + accelerating → high quality
good = q.side_quality('CONCENTRATED_SINGLE_STRIKE_EVENT', 'ABSORPTION', 4.0, 10)  # unknown class → THIN base
conc = q.side_quality('SINGLE_STRIKE_DOMINANT', 'ABSORPTION', 4.0, 10)
ck("concentrated + absorption + fresh → quality > 1", conc > 1.0)
# distributed + premium REJECTION (bleed) + decelerating → heavily discounted
bleed = q.side_quality('DISTRIBUTED', 'REJECTION', 0.0, -50)
ck("distributed + rejection + stale → heavy discount", bleed < 0.2)
ck("a compact absorbing event outranks a distributed bleeding one", conc > bleed)
# neutral baseline
neut = q.side_quality('SINGLE_STRIKE_DOMINANT', 'NEUTRAL', 0.0, 0)
ck("neutral single-strike ≈ 1.0", abs(neut - 1.0) < 0.01)

print("── qualified_control: compact PUT event overturns larger raw CALL pool (NVDA 220C vs 220P) ──")
# Raw: calls have the larger mass (the 220C distributed pool). Puts smaller but high-quality.
call_mass, put_mass = 1_000_000.0, 600_000.0
call_q = q.side_quality('DISTRIBUTED', 'REJECTION', 0.0, -40)      # bleeding distributed calls
put_q  = q.side_quality('SINGLE_STRIKE_DOMINANT', 'ABSORPTION', 4.0, 30)  # compact expanding puts
res = q.qualified_control(call_mass, put_mass, call_q, put_q)
ck("raw winner is CALL", call_mass > put_mass)
ck("qualified winner flips to PUT", res['dominant_side'] == 'PUT')
ck("flip flagged", res['flipped_from_raw'])
ck("qualified put control > 0.5", res['q_put_control'] > 0.5)

print("── qualified_control: genuine larger side keeps control ──")
res2 = q.qualified_control(1_000_000.0, 300_000.0,
                           q.side_quality('SINGLE_STRIKE_DOMINANT', 'ABSORPTION', 4.0, 20),
                           q.side_quality('DISTRIBUTED', 'REJECTION', 0.0, -10))
ck("strong large CALL keeps control", res2['dominant_side'] == 'CALL' and not res2['flipped_from_raw'])

print("── degenerate ──")
ck("both zero → None", q.qualified_control(0, 0, 1.0, 1.0)['dominant_side'] is None)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
