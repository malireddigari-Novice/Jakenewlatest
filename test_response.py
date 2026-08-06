"""Price-response / accumulation-vs-distribution tests. Run: python test_response.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analysis import response as R

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

# ── price_response ──
ck("premium expanded → positive response", R.price_response(1.00, 1.30) == 0.30)
ck("premium collapsed → negative response", R.price_response(2.00, 1.00) == -0.50)
ck("no event price → 0", R.price_response(0, 1.0) == 0.0)

# ── volume_pattern: compact institutional burst (TSLA 312.5P shape) ──
compact = [0]*13 + [0, 50, 100, 800, 900, 700, 600]   # dormant → burst in the last minutes
vp = R.volume_pattern(compact)
ck("compact burst → high event share", vp['event_share'] >= 0.45)
ck("compact burst → high top-3 share", vp['top3_share'] >= 0.55)
ck("compact burst → CompactCluster true", vp['compact'])
ck("compact burst → BurstPersistence >= 2", vp['burst'] >= 2)

uniform = [300]*20                                     # broadly distributed background
vpu = R.volume_pattern(uniform)
ck("uniform flow → not compact", not vpu['compact'])

dormant = [0]*20
ck("dormant → zero total", R.volume_pattern(dormant)['total'] == 0)

# ── classify: ACCUMULATION vs DISTRIBUTION ──
# 1) Compact burst + premium expanding + near low → ACCUMULATION (eligible).
acc = R.classify(vp, resp_event=0.12, resp_recent=0.08, value_low_dist=1.2,
                 strike_class='SINGLE_STRIKE_DOMINANT')
ck("compact + positive response → accumulation eligible", acc['eligible'] and 'ACCUMULATION' in acc['label'])
ck("single-strike burst → SINGLE_STRIKE_ACCUMULATION", acc['label'] == 'SINGLE_STRIKE_ACCUMULATION')

# 2) Heavy volume but premium COLLAPSING since event → HEAVY_VOLUME_NEGATIVE_RESPONSE (reject).
neg = R.classify(vp, resp_event=-0.12, resp_recent=-0.15, value_low_dist=1.2,
                 strike_class='SINGLE_STRIKE_DOMINANT')
ck("heavy volume + premium collapse → not eligible", not neg['eligible'])
ck("collapse labeled HEAVY_VOLUME_NEGATIVE_RESPONSE", neg['label'] == 'HEAVY_VOLUME_NEGATIVE_RESPONSE')
ck("collapse shape = EXHAUSTION_OR_EXIT_FLOW", neg['shape'] == 'EXHAUSTION_OR_EXIT_FLOW')

# 3) Already extended from the low (mature scaling) → MATURE_DISTRIBUTION (reject).
mat = R.classify(vp, resp_event=0.05, resp_recent=0.02, value_low_dist=2.0,
                 strike_class='SINGLE_STRIKE_DOMINANT')
ck("extended from low → MATURE_DISTRIBUTION, not eligible",
   mat['label'] == 'MATURE_DISTRIBUTION' and not mat['eligible'])

# 4) Coordinated chain burst → COORDINATED_CHAIN_ACCUMULATION.
chain = R.classify(vp, resp_event=0.10, resp_recent=0.05, value_low_dist=1.1,
                   strike_class='COORDINATED_CHAIN')
ck("chain burst → COORDINATED_CHAIN_ACCUMULATION", chain['label'] == 'COORDINATED_CHAIN_ACCUMULATION')

# 5) Distributed background + flat response → not eligible.
dist = R.classify(vpu, resp_event=0.0, resp_recent=0.0, value_low_dist=1.2, strike_class='DISTRIBUTED')
ck("distributed background → not eligible", not dist['eligible'])

# 6) Dormant → not eligible.
dorm = R.classify(R.volume_pattern(dormant), 0.0, 0.0, 1.2, 'THIN')
ck("dormant background → not eligible", not dorm['eligible'] and dorm['shape'] == 'DORMANT_BACKGROUND')

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
