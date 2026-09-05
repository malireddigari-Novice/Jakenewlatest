"""Exit taxonomy + runner-config tests (Phase 7). Run: python test_exits.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import campaign

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── exit taxonomy ──")
cases = {
    'STRUCTURAL_TP1': 'OBJECTIVE', 'STRUCTURAL_TP2': 'OBJECTIVE', 'TRAIL_GIVEBACK': 'OBJECTIVE',
    'RUNNER_TRAIL': 'OBJECTIVE', 'STOP_LOSS': 'RISK_STOP', 'EOD_FLATTEN': 'EOD',
    'CONTROL_TRANSFER': 'CONTROL_TRANSFER', 'CONTROL_FLIP_OVERWHELMING': 'CONTROL_TRANSFER',
    'ROTATION': 'THESIS_DEATH', 'STATISTICAL_EXHAUSTION': 'THESIS_DEATH',
    'DISTRIBUTION_EXIT': 'DISTRIBUTION', 'DISTRIBUTION_REDUCE': 'DISTRIBUTION',
}
for reason, cat in cases.items():
    ck(f"{reason} → {cat}", campaign.exit_category(reason) == cat)
ck("unknown reason → OTHER", campaign.exit_category('SOMETHING_NEW') == 'OTHER')

print("── runner narration ──")
ck("runner reasons have human narration",
   'runner' in campaign.campaign_end('RUNNER_TRAIL').lower()
   and 'distribution' in campaign.campaign_end('DISTRIBUTION_EXIT').lower())

print("── runner config invariants (env-independent) ──")
ck("RUNNER_ENABLED is a boolean flag", isinstance(config.RUNNER_ENABLED, bool))
ck("runner trail is wider than the base trail (let winners run)",
   config.RUNNER_TRAIL_GIVEBACK_PCT > config.TRAIL_GIVEBACK_PCT)

print("── pre-TP1 trail ownership (AMZN 08/28 260C regression) ──")
ARM, GB = config.TRAIL_ARM_PCT, config.TRAIL_GIVEBACK_PCT   # defaults: arm +40%, give back 35%
# AMZN 260C: peaked ~+56% (below the +60% TP1 → tp1_done False), then a normal high-gamma
# retracement dragged pnl back toward flat, tripping the +40%-armed 35%-giveback trail. With
# TRAIL_REQUIRE_TP1 (the fix) the trail must NOT own a pre-TP1 position — the campaign then went +700%.
amzn_peak, amzn_pnl = 0.56, 0.05
ck("legacy pre-TP1 trail WOULD have exited AMZN (documents the old bug)",
   campaign.trail_should_exit(amzn_pnl, amzn_peak, False, arm_pct=ARM, giveback_pct=GB, require_tp1=False))
ck("fix: pre-TP1 trail does NOT fire when require_tp1 (AMZN held)",
   not campaign.trail_should_exit(amzn_pnl, amzn_peak, False, arm_pct=ARM, giveback_pct=GB, require_tp1=True))
# Default runtime must ship with the fix on.
ck("TRAIL_REQUIRE_TP1 defaults ON", config.TRAIL_REQUIRE_TP1 is True)
# After TP1 the trail SHOULD protect banked gains — the fix must not disable the post-TP1 trail.
ck("post-TP1: trail still protects banked gains (giveback breached)",
   campaign.trail_should_exit(0.10, 0.60, True, arm_pct=ARM, giveback_pct=GB, require_tp1=True))
# And a healthy runner still inside its giveback band is never trailed out.
ck("post-TP1: no exit while inside the giveback band",
   not campaign.trail_should_exit(0.55, 0.60, True, arm_pct=ARM, giveback_pct=GB, require_tp1=True))
# A pre-TP1 position that never armed the trail (peak below arm) is a no-op either way.
ck("pre-TP1 below arm threshold: no exit regardless of flag",
   not campaign.trail_should_exit(0.10, 0.30, False, arm_pct=ARM, giveback_pct=GB, require_tp1=True))

print("── rejection taxonomy (§19) ──")
ck("price-extension miss is a model miss", campaign.reject_is_model_miss('MISSED_DUE_TO_PRICE_EXTENSION'))
ck("single-strike-notional miss is a model miss",
   campaign.reject_is_model_miss('MISSED_DUE_TO_SINGLE_STRIKE_NOTIONAL'))
ck("economically-valid rejection is NOT a model miss",
   not campaign.reject_is_model_miss('ECONOMICALLY_VALID_REJECTION'))
ck("capacity + data-quality are NOT model misses",
   not campaign.reject_is_model_miss('MISSED_DUE_TO_CAPACITY')
   and not campaign.reject_is_model_miss('DATA_QUALITY_REJECTION'))

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
