"""Event-shape-through-time tests: DTE timing, response efficiency, distribution
probability, volume skew, new shapes, Bayesian posterior + EV. Run: python test_shape.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import response as R
from analysis import campaign as C

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

# ── DTE-sensitive timing ──
ck("0DTE → fast confirm (1) + short forming window", config.dte_timing(0)['active_confirm'] == 1
   and config.dte_timing(0)['max_forming_s'] == 120.0)
ck("1DTE → more patience than 0DTE", config.dte_timing(1)['active_confirm'] == 2
   and config.dte_timing(1)['max_forming_s'] == 300.0)
ck("2DTE+ → most persistence", config.dte_timing(5)['active_confirm'] == 3)
ck("unknown DTE → preserves old fixed constants, no forming timeout",
   config.dte_timing(None)['active_confirm'] == config.WAVE_ACTIVE_CONFIRM
   and config.dte_timing(None)['min_hold_s'] == config.WAVE_MIN_HOLD_SECONDS
   and config.dte_timing(None)['max_forming_s'] is None)
ck("dte_bucket clamps 0/1/2+", (config.dte_bucket(0), config.dte_bucket(1), config.dte_bucket(4))
   == (0, 1, 2))

# ── response efficiency + decay ──
early = R.response_efficiency(0.35, 300_000)          # 35% on $300k
late = R.response_efficiency(0.02, 1_200_000)         # 2% on $1.2M
ck("early campaign has higher response efficiency than late", early > late)
ck("efficiency decay is negative when it falls", (late - early) < 0)

# ── distribution probability (joint) ──
healthy = R.distribution_probability(extension=1.2, eff_decay=0.0, rel_premium=1.1,
                                     iv_slope=0.01, giveback=0.0, opp_accel_norm=0.1,
                                     spot_confirms=True)
dying = R.distribution_probability(extension=3.0, eff_decay=-1.0, rel_premium=6.0,
                                   iv_slope=-0.05, giveback=0.4, opp_accel_norm=1.0,
                                   spot_confirms=False)
ck("healthy accumulation → low distribution probability", healthy < 0.3)
ck("heavy volume at the high w/ IV roll-over + opposition → high", dying > 0.8)
ck("no single component decides it (monotone in giveback)",
   R.distribution_probability(extension=1.2, giveback=0.4, spot_confirms=True)
   > R.distribution_probability(extension=1.2, giveback=0.0, spot_confirms=True))

# ── volume skew + new shapes ──
early_vol = [500, 400, 300, 100] + [0] * 12           # activity front-loaded then quiet
ck("front-loaded volume → negative skew (early)", R.volume_pattern(early_vol)['skew'] < -0.3)
late_vol = [0] * 12 + [100, 300, 400, 500]            # activity back-loaded
ck("back-loaded volume → positive skew (late)", R.volume_pattern(late_vol)['skew'] > 0.3)

# extended premium giving back recently → distribution-at-high, not eligible
compact = [0] * 13 + [0, 50, 100, 800, 900, 700, 600]
vp = R.volume_pattern(compact)
d_high = R.classify(vp, resp_event=0.04, resp_recent=-0.08, value_low_dist=2.2,
                    strike_class='SINGLE_STRIKE_DOMINANT')
ck("heavy volume at the high + recent giveback → DISTRIBUTION_AT_PREMIUM_HIGH (reject)",
   d_high['shape'] == 'DISTRIBUTION_AT_PREMIUM_HIGH' and not d_high['eligible'])

# ── Bayesian posterior + expected value ──
allsig = {'leadership': True, 'waking': True, 'accumulation': True, 'control': True, 'cheap': True}
ck("all signals present → posterior clears entry threshold",
   C.posterior(allsig) >= config.CAMPAIGN_MIN_POSTERIOR)
ck("missing accumulation collapses the posterior",
   C.posterior({**allsig, 'accumulation': False}) < C.posterior(allsig))
ck("morning context lifts the prior", C.context_prior({'prior': 0.55}) > C.context_prior(None))
ck("spot confirmation raises the posterior",
   C.posterior(allsig, spot_confirms=True) > C.posterior(allsig, spot_confirms=False))
ck("EV positive when convex + high P(continue)", C.expected_value(0.9, 0.8, 0.1, 0.4) > 0)
ck("EV negative when distribution likely + little convexity left",
   C.expected_value(0.5, 0.1, 0.8, 0.4) < 0)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
