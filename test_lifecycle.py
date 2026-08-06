"""Campaign-lifecycle tests: windowed response, shakeout, self-sustainability, efficiency
trend, continuation, expanded shape metrics, delayed convexity. Run: python test_lifecycle.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import lifecycle as lc
from analysis import response as R

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

# ── windowed premium response ──
rising = [(0, 1.0), (30, 1.1), (60, 1.25), (90, 1.3), (120, 1.35), (150, 1.4)]
wpr = lc.windowed_premium_response(rising, 1.0)
ck("MFE captures best excursion", wpr['mfe'] == 0.4)
ck("AUC positive when premium spent time above event", wpr['auc'] > 0)
ck("windowed responses populated", wpr['r180'] > 0 and wpr['r300'] > 0)
ck("empty marks → neutral zeros", lc.windowed_premium_response([], 1.0)['mfe'] == 0.0)

# ── self-sustainability: premium climbs while volume fades ──
fade_vol = [900, 700, 300, 120, 60, 40]
ck("premium rising as volume fades → high self-sustainability",
   lc.self_sustainability(fade_vol, rising) > 0.6)
falling = [(0, 1.0), (30, 0.95), (60, 0.9), (90, 0.85), (120, 0.8), (150, 0.78)]
ck("premium fails as volume fades → low self-sustainability",
   lc.self_sustainability(fade_vol, falling) < 0.2)

# ── shakeout: dip below event then recover ──
sk = [(0, 1.0), (30, 0.82), (60, 0.78), (90, 0.9), (120, 1.05)]
ck("dip-then-recover → positive shakeout score", lc.shakeout_score(sk, 1.0) > 0.3)
ck("still falling → no shakeout credit",
   lc.shakeout_score([(0, 1.0), (30, 0.9), (60, 0.8), (90, 0.7)], 1.0) == 0.0)

# ── efficiency trend ──
ck("efficiency rising → RISING", lc.efficiency_trend([0.1, 0.15, 0.2, 0.28, 0.35])['label'] == 'RISING')
ck("efficiency decaying → DECAYING", lc.efficiency_trend([0.4, 0.3, 0.2, 0.1, 0.02])['label'] == 'DECAYING')
ck("short history → STABLE", lc.efficiency_trend([0.2])['label'] == 'STABLE')

# ── continuation probability ──
healthy = lc.continuation_probability(self_sust=0.5, eff_slope=0.02, auc=0.15, control=0.8,
                                      spot_confirms=True, shakeout=0.0)
weak = lc.continuation_probability(self_sust=0.0, eff_slope=-0.02, auc=-0.1, control=0.6,
                                   spot_confirms=False, shakeout=0.0)
ck("healthy campaign → high continuation probability", healthy > 0.7)
ck("failing campaign → low continuation probability", weak < 0.3)

# ── expanded shape metrics ──
compact = [0] * 13 + [0, 50, 100, 800, 900, 700, 600]
vp = R.volume_pattern(compact)
ck("concentrated burst → high Gini", vp['gini'] > 0.5)
ck("concentrated burst → low-ish entropy", vp['entropy'] < 0.8)
ck("silence fraction high when mostly dormant bins", vp['silence'] > 0.5)
ck("half_life is a positive integer", isinstance(vp['half_life'], int) and vp['half_life'] >= 0)

# ── delayed convexity: negative instant response but a recovered shakeout w/ prior excursion ──
d = R.classify(vp, resp_event=-0.04, resp_recent=-0.03, value_low_dist=1.2,
               strike_class='SINGLE_STRIKE_DOMINANT', mfe=0.12, shakeout=0.4)
ck("delayed convexity (mfe+shakeout) → still eligible", d['eligible'])
# without the lifecycle evidence the same negative response is NOT eligible
d0 = R.classify(vp, resp_event=-0.04, resp_recent=-0.03, value_low_dist=1.2,
                strike_class='SINGLE_STRIKE_DOMINANT')
ck("same negative response w/o mfe/shakeout → not eligible", not d0['eligible'])
# a genuine collapse is never rescued (below the delayed floor)
dbad = R.classify(vp, resp_event=-0.20, resp_recent=-0.25, value_low_dist=1.2,
                  strike_class='SINGLE_STRIKE_DOMINANT', mfe=0.12, shakeout=0.4)
ck("true collapse below floor → still rejected", not dbad['eligible'])

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
