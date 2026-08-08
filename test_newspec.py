"""New-spec tests: premium acceptance + T+1 OI classifier + config locks. Run: python test_newspec.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import flow_response as fr
from analysis import oi_confirm
from analysis import entry

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── premium acceptance (GOOGL absorption vs rejection) ──")
# Heavy recent volume + premium making lower lows (GOOGL 362.5C destroyed) → REJECTION.
rej = fr.premium_acceptance(minute_vols=[100, 120, 900, 1000, 1100],
                            marks=[3.0, 2.6, 2.1, 1.5, 0.9])
ck("heavy volume + lower lows → REJECTION", rej['label'] == 'REJECTION' and not rej['absorbing'])
# Heavy recent volume + premium holding flat (357.5C stabilising) → ABSORPTION (no appreciation needed).
absb = fr.premium_acceptance(minute_vols=[100, 120, 900, 1000, 1100],
                             marks=[2.0, 2.0, 2.05, 2.0, 2.05])
ck("heavy volume + premium holding flat → ABSORPTION (no appreciation required)",
   absb['label'] == 'ABSORPTION' and absb['absorbing'])
# Light volume → NEUTRAL (not enough to classify).
ck("light volume → NEUTRAL", fr.premium_acceptance([10, 10, 11, 10], [2, 2, 2, 2])['label'] == 'NEUTRAL')
# Regression: contract_marks returns (ts, price) TUPLES — premium_acceptance must handle them
# (this exact mismatch crashed the live engine every poll on 2026-08-07).
tup = fr.premium_acceptance([100, 120, 900, 1000, 1100],
                            [(1, 3.0), (2, 2.6), (3, 2.1), (4, 1.5), (5, 0.9)])
ck("premium_acceptance handles (ts, price) tuple marks (live-crash regression)",
   tup['label'] == 'REJECTION')

print("── acceptance wired into entry routing ──")
def cand(**kw):
    base = {'side': 'CALL', 'notional': 1.2e5, 'dist_low': 1.1, 'resp_event': 0.0, 'self_sust': 0.3,
            'cont_prob': 0.7, 'dist_prob': 0.1, 'archetype': {'archetype': 'SHOCK_ACCUMULATION'},
            'surface': {}}
    base.update(kw); return base
def m(rank=1, share=0.5, z=4.5, ctrl=0.85):
    return {'rank': rank, 'attention_share': share, 'mass_z': z, 'call_control': ctrl, 'put_control': 1 - ctrl}
ck("REJECTION acceptance is a hard veto in route mode",
   entry.hard_veto(cand(acceptance={'label': 'REJECTION', 'absorbing': False})) == 'ECONOMICALLY_VALID_REJECTION')
# Absorption lifts response evidence even with a flat/negative instant response (no appreciation).
ev_flat = entry.evidence(cand(resp_event=-0.02), m())['response']
ev_absorb = entry.evidence(cand(resp_event=-0.02, acceptance={'label': 'ABSORPTION', 'absorbing': True, 'score': 0.85}), m())['response']
ck("absorption raises response evidence without appreciation", ev_absorb > ev_flat)

print("── T+1 OI classifier ──")
ck("volume→new OI → NEW_POSITION_CONFIRMED",
   oi_confirm.classify_oi_change(prior_oi=1000, today_volume=5000, new_oi=4000) == 'NEW_POSITION_CONFIRMED')
ck("OI flat despite big volume → LIKELY_CLOSING_CHURN",
   oi_confirm.classify_oi_change(prior_oi=5000, today_volume=8000, new_oi=5000) == 'LIKELY_CLOSING_CHURN')
ck("partial OI rise → PARTIALLY_CONFIRMED",
   oi_confirm.classify_oi_change(prior_oi=1000, today_volume=5000, new_oi=2200) == 'PARTIALLY_CONFIRMED')
ck("missing OI → INCONCLUSIVE",
   oi_confirm.classify_oi_change(prior_oi=None, today_volume=5000, new_oi=None) == 'INCONCLUSIVE')

print("── config locks present ──")
ck("DAILY_ENTRY_LOCK_ENABLED is a bool", isinstance(config.DAILY_ENTRY_LOCK_ENABLED, bool))
ck("REINFORCE_LOG_ENABLED is a bool", isinstance(config.REINFORCE_LOG_ENABLED, bool))

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
