"""Multi-hypothesis engine tests (addendum #9). Run: python test_hypotheses.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import hypotheses as hp

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── clean fresh directional ──")
r = hp.assess({'acceptance': 'ABSORPTION', 'resp_event': 0.15, 'self_sust': 0.6,
               'inv_ambiguity': 'LOW', 'package': 'OUTRIGHT_LIKELY', 'hedge': 'DIRECTIONAL'})
ck("top hypothesis is FRESH_DIRECTIONAL", r['top'] == 'FRESH_DIRECTIONAL')
ck("not ambiguous", not r['ambiguous'])

print("── roll dominates when package is a roll ──")
r = hp.assess({'acceptance': 'NEUTRAL', 'package': 'ROLL_LIKELY'})
ck("ROLL is top", r['top'] == 'ROLL')

print("── spread leg ──")
r = hp.assess({'package': 'VERTICAL_LIKELY'})
ck("SPREAD_LEG is top", r['top'] == 'SPREAD_LEG')

print("── convexity/hedge ──")
r = hp.assess({'hedge': 'CONVEXITY', 'package': 'STRADDLE_COMBO_LIKELY'})
ck("HEDGE is top", r['top'] == 'HEDGE')

print("── inventory HIGH kills fresh-directional ──")
r = hp.assess({'acceptance': 'REJECTION', 'resp_event': -0.1, 'inv_ambiguity': 'HIGH',
               'inv_state': 'LIKELY_PARTIAL_EXIT'})
ck("fresh-directional suppressed", r['directional_p'] < 0.25)
ck("closing/overwrite family elevated", r['probs']['CLOSING_PROFITABLE'] > r['directional_p'])

print("── probabilities normalise ──")
r = hp.assess({})
ck("distribution sums ~1", abs(sum(r['probs'].values()) - 1.0) < 1e-6)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
