"""New-spec tests: premium acceptance + T+1 OI reconciliation + config locks. Run: python test_newspec.py"""
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

print("── T+1 OI reconciliation (oi-recon-v1) ──")
ck("volume→new OI → OPENING_SUPPORTED",
   oi_confirm.classify_oi_change(prior_oi=1000, session_volume=5000, new_oi=4000) == 'OPENING_SUPPORTED')
ck("OI flat despite big volume → OPENING_WEAKENED (flat can hide transfers)",
   oi_confirm.classify_oi_change(prior_oi=5000, session_volume=8000, new_oi=5000) == 'OPENING_WEAKENED')
ck("partial OI rise → OPENING_PARTIAL",
   oi_confirm.classify_oi_change(prior_oi=1000, session_volume=5000, new_oi=2200) == 'OPENING_PARTIAL')
ck("small positive OI rise is still partial (not inconclusive)",
   oi_confirm.classify_oi_change(prior_oi=1000, session_volume=5000, new_oi=1100) == 'OPENING_PARTIAL')
ck("missing OI → INCONCLUSIVE",
   oi_confirm.classify_oi_change(prior_oi=None, session_volume=5000, new_oi=None) == 'INCONCLUSIVE')
ck("missing full-session volume → INCONCLUSIVE (partial volume is never substituted)",
   oi_confirm.classify_oi_change(prior_oi=1000, session_volume=None, new_oi=3000) == 'INCONCLUSIVE')
ck("|ΔOI| > V → RECONCILE_REQUIRED",
   oi_confirm.classify_oi_change(prior_oi=1000, session_volume=500, new_oi=2000) == 'RECONCILE_REQUIRED')
ck("|ΔOI| > V (falling) → RECONCILE_REQUIRED",
   oi_confirm.classify_oi_change(prior_oi=3000, session_volume=500, new_oi=1000) == 'RECONCILE_REQUIRED')
b = oi_confirm.oi_bounds(5000, 3000)
ck("bounds V=5000 Δ=3000 → OO∈[3000,4000] CC∈[0,1000] T∈[0,2000]",
   b == {'oo_min': 3000, 'oo_max': 4000, 'cc_min': 0, 'cc_max': 1000, 't_min': 0, 't_max': 2000})
b = oi_confirm.oi_bounds(7, -2)
ck("bounds V=7 Δ=-2 → OO∈[0,2] CC∈[2,4] T∈[1,5] (parity)",
   b == {'oo_min': 0, 'oo_max': 2, 'cc_min': 2, 'cc_max': 4, 't_min': 1, 't_max': 5})
ck("bounds are internally consistent (OO−CC=Δ, OO+CC+T=V at the extremes)",
   all((bb['oo_min'] - bb['cc_min'] == d) and (bb['oo_min'] + bb['cc_min'] + bb['t_max'] == v)
       and (bb['oo_max'] - bb['cc_max'] == d) and (bb['oo_max'] + bb['cc_max'] + bb['t_min'] == v)
       for v in range(0, 30) for d in range(-v, v + 1) for bb in [oi_confirm.oi_bounds(v, d)]))
ck("oi_bounds |Δ|>V → None", oi_confirm.oi_bounds(10, 11) is None)
ck("reconcile record carries rule_version",
   oi_confirm.reconcile(1000, 5000, 4000)['rule_version'] == oi_confirm.RULE_VERSION)
ck("legacy labels map to bounded replacements",
   oi_confirm.LEGACY_LABELS['NEW_POSITION_CONFIRMED'] == 'OPENING_SUPPORTED'
   and oi_confirm.LEGACY_LABELS['LIKELY_CLOSING_CHURN'] == 'OPENING_WEAKENED')

print("── config locks present ──")
ck("DAILY_ENTRY_LOCK_ENABLED is a bool", isinstance(config.DAILY_ENTRY_LOCK_ENABLED, bool))
ck("REINFORCE_LOG_ENABLED is a bool", isinstance(config.REINFORCE_LOG_ENABLED, bool))

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
