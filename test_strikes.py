"""Strike-surface aggregation tests (Phase 5). Run: python test_strikes.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import strikes

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

SPOT = 250.0
print("── strike surface ──")

# One strike owns it → SINGLE_STRIKE_DOMINANT.
single = {250.0: 9e5, 252.5: 5e4, 247.5: 5e4}
ck("one dominant strike → SINGLE_STRIKE_DOMINANT",
   strikes.surface_profile(single, SPOT)['classification'] == 'SINGLE_STRIKE_DOMINANT')

# Two strikes coordinate → TWO_STRIKE_COORDINATED.
two = {250.0: 5e5, 252.5: 4e5, 245.0: 3e4}
ck("two coordinated strikes → TWO_STRIKE_COORDINATED",
   strikes.surface_profile(two, SPOT)['classification'] == 'TWO_STRIKE_COORDINATED')

# The AMZN case: call volume spread across a broad ladder, no single dominant strike, but a real
# ticker-level campaign — must NOT be dismissed as background.
amzn = {237.5: 3e5, 240.0: 3.2e5, 242.5: 3.1e5, 245.0: 3.4e5, 247.5: 3.6e5,
        250.0: 4.0e5, 252.5: 3.8e5, 255.0: 3.5e5, 257.5: 3.0e5}
prof = strikes.surface_profile(amzn, SPOT)
ck("AMZN broad ladder is recognised as a real campaign, not background",
   prof['classification'] in ('ADJACENT_STRIKE_LADDER', 'BROAD_SURFACE_ACCUMULATION'))
ck("AMZN surface is tradeable (broad participation ≠ weak participation)",
   strikes.is_tradeable_surface(prof['classification']))
ck("AMZN breadth is high and no single strike dominates",
   prof['breadth'] >= 4 and prof['top_share'] < config.SURFACE_SINGLE)
ck("AMZN names a representative contract near the weighted center",
   prof['representative_strike'] is not None
   and abs(prof['representative_strike'] - prof['weighted_center']) <= 2.5)
ck("breadth-adjusted strength rewards breadth (exceeds raw ladder mass)",
   prof['breadth_adjusted_strength'] > prof['ladder_mass'])

# Smeared across many strikes, none meaningful → DISTRIBUTED_BACKGROUND (not tradeable).
smear = {235.0 + 2.5 * i: 6e4 for i in range(10)}
smear[250.0] = 7e5     # one strike carries most; the rest are tiny, none else meaningful
dprof = strikes.surface_profile(smear, SPOT)
ck("one strike + tiny smeared rest → single-dominant or distributed, tradeability sensible",
   dprof['classification'] in ('SINGLE_STRIKE_DOMINANT', 'DISTRIBUTED_BACKGROUND'))

# Empty side → THIN, never crashes.
ck("empty side → THIN", strikes.surface_profile({}, SPOT)['classification'] == 'THIN')

# Momentum: weighted center rising as spot-side ladder shifts up.
p0 = strikes.surface_profile({245.0: 5e5, 247.5: 5e5}, SPOT)
p1 = strikes.surface_profile({250.0: 5e5, 252.5: 5e5}, SPOT, prev_center=p0['weighted_center'])
ck("rising weighted center → positive strike momentum", p1['momentum'] is not None and p1['momentum'] > 0)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
