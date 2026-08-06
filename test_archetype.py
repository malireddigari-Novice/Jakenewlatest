"""Campaign archetype classification tests (Phase 4). Run: python test_archetype.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import archetype

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1


def vp(**kw):
    base = {'dominant': 0.3, 'burst': 0, 'decay_rate': 0.0, 'reaccel': 0.0,
            'compact': False, 'skew': 0.0}
    base.update(kw)
    return base

print("── archetypes ──")

# Compact dominant abnormal burst → SHOCK_ACCUMULATION.
shock = {'vp': vp(dominant=0.8, compact=True, burst=1), 'mass_z': 5.0, 'resp_event': 0.12,
         'velocity': 1e6}
ck("compact dominant abnormal burst → SHOCK_ACCUMULATION",
   archetype.classify(shock)['archetype'] == 'SHOCK_ACCUMULATION')

# Premium rising while volume fades → SELF_SUSTAINING_EXPANSION (the AAPL case).
selfsust = {'vp': vp(decay_rate=0.7, burst=1), 'mass_z': 2.0, 'resp_event': 0.03,
            'self_sust': 0.5, 'eff_trend': 'STABLE', 'rel_premium': 1.4}
ck("premium rising as volume fades → SELF_SUSTAINING_EXPANSION",
   archetype.classify(selfsust)['archetype'] == 'SELF_SUSTAINING_EXPANSION')

# Repeated moderate participation, no single dominant bar → PERSISTENT_ACCUMULATION.
persist = {'vp': vp(dominant=0.3, burst=3, compact=False), 'mass_z': 2.5, 'resp_event': 0.0,
           'velocity': 1e5}
ck("repeated moderate participation → PERSISTENT_ACCUMULATION",
   archetype.classify(persist)['archetype'] == 'PERSISTENT_ACCUMULATION')

# Dip-then-recover with prior excursion → SHAKEOUT_AND_RECOVERY.
shake = {'vp': vp(burst=1), 'mass_z': 3.0, 'resp_event': -0.02, 'shakeout': 0.4, 'mfe': 0.10}
ck("dip-then-recover with MFE → SHAKEOUT_AND_RECOVERY",
   archetype.classify(shake)['archetype'] == 'SHAKEOUT_AND_RECOVERY')

# Heavy distribution evidence dominates everything else.
dist = {'vp': vp(dominant=0.8, compact=True, burst=1), 'mass_z': 5.0, 'resp_event': -0.09,
        'dist_prob': 0.85}
ck("distribution/exit evidence → DISTRIBUTION",
   archetype.classify(dist)['archetype'] == 'DISTRIBUTION')

# Reacceleration after a pause → STAIR_STEP_ACCUMULATION.
stair = {'vp': vp(burst=2, reaccel=0.6, dominant=0.4), 'mass_z': 2.0, 'resp_event': 0.0}
ck("reacceleration after a pause → STAIR_STEP_ACCUMULATION",
   archetype.classify(stair)['archetype'] == 'STAIR_STEP_ACCUMULATION')

# Forward expiry concentration (from the P3 scan) → FORWARD_POSITIONING.
fwd = {'vp': vp(burst=1), 'mass_z': 2.0, 'resp_event': 0.0, 'expiry_class': 'FORWARD_POSITIONING'}
ck("forward expiry concentration → FORWARD_POSITIONING",
   archetype.classify(fwd)['archetype'] == 'FORWARD_POSITIONING')

# Same side across expiries → CROSS_EXPIRY_ACCUMULATION.
cross = {'vp': vp(burst=1), 'mass_z': 2.0, 'resp_event': 0.0,
         'expiry_class': 'SAME_SIDE_MULTI_EXPIRY_CONTROL'}
ck("same side across expiries → CROSS_EXPIRY_ACCUMULATION",
   archetype.classify(cross)['archetype'] == 'CROSS_EXPIRY_ACCUMULATION')

# Nothing distinctive → UNCLASSIFIED (never a crash / always a dict).
r = archetype.classify({'vp': vp(), 'mass_z': 0.5, 'resp_event': 0.0})
ck("featureless flow → UNCLASSIFIED with confidence in [0,1]",
   r['archetype'] == 'UNCLASSIFIED' and 0.0 <= r['confidence'] <= 1.0)

print("── archetype-aware quality score (§17) ──")
# A persistent build with strong persistence but weak acceleration should score WELL as
# PERSISTENT_ACCUMULATION (persistence-weighted) and poorly as a SHOCK (acceleration-weighted).
persist_f = {'persistence': 0.9, 'acceleration': 0.1, 'control': 0.8, 'notional': 0.7,
             'continuation': 0.8, 'low_dist': 0.9, 'response': 0.5, 'self_sust': 0.7, 'expiry': 0.3}
ck("persistent build scores higher as PERSISTENT than as SHOCK",
   archetype.quality_score('PERSISTENT_ACCUMULATION', persist_f)
   > archetype.quality_score('SHOCK_ACCUMULATION', persist_f))
# A violent shock (high acceleration, low persistence) is the reverse.
shock_f = {'persistence': 0.1, 'acceleration': 0.9, 'control': 0.8, 'notional': 0.7,
           'continuation': 0.5, 'low_dist': 0.9, 'response': 0.8, 'self_sust': 0.1, 'expiry': 0.1}
ck("shock scores higher as SHOCK than as PERSISTENT",
   archetype.quality_score('SHOCK_ACCUMULATION', shock_f)
   > archetype.quality_score('PERSISTENT_ACCUMULATION', shock_f))
ck("quality score is 0-100", 0 <= archetype.quality_score('UNCLASSIFIED', persist_f) <= 100)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
