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
