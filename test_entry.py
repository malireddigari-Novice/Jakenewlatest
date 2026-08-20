"""Archetype entry-routing tests (follow-up §10). Run: python test_entry.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import entry

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1


def m(rank=1, share=0.5, z=4.0, ctrl=0.85, side='CALL'):
    cc, pc = (ctrl, 1 - ctrl) if side == 'CALL' else (1 - ctrl, ctrl)
    return {'rank': rank, 'attention_share': share, 'mass_z': z, 'call_control': cc, 'put_control': pc}


def cand(arch='SHOCK_ACCUMULATION', notional=1.2e5, dist_low=1.1, resp=0.08, self_sust=0.3,
         cont=0.7, dist_prob=0.1, surface=None, side='CALL'):
    return {'side': side, 'notional': notional, 'dist_low': dist_low, 'resp_event': resp,
            'self_sust': self_sust, 'cont_prob': cont, 'dist_prob': dist_prob,
            'archetype': {'archetype': arch}, 'surface': surface or {}}

print("── hard vetoes (§10-A) ──")
ck("coherent distribution is a hard veto",
   entry.hard_veto(cand(dist_prob=0.9)) == 'ECONOMICALLY_VALID_REJECTION')
ck("objectively-late extension is a hard veto",
   entry.hard_veto(cand(dist_low=3.0)) == 'MISSED_DUE_TO_PRICE_EXTENSION')
ck("a clean candidate has no hard veto", entry.hard_veto(cand()) is None)
ck("a DISTRIBUTION archetype is a hard veto (never route-enter distribution)",
   entry.hard_veto(cand(arch='DISTRIBUTION')) == 'ECONOMICALLY_VALID_REJECTION')
ck("a mature/exit event shape is a hard veto",
   entry.hard_veto({**cand(), 'shape': 'MATURE_SCALING_ACTIVITY'}) == 'ECONOMICALLY_VALID_REJECTION')
ck("HEAVY_VOLUME_NEGATIVE_RESPONSE is a hard veto (the GOOGL 362.5C case)",
   entry.hard_veto({**cand(), 'shape': 'HEAVY_VOLUME_NEGATIVE_RESPONSE'}) == 'ECONOMICALLY_VALID_REJECTION')
ck("ISOLATED_PRINT is a hard veto (lone/late chase)",
   entry.hard_veto({**cand(), 'shape': 'ISOLATED_PRINT'}) == 'ECONOMICALLY_VALID_REJECTION')
ck("decide() refuses a DISTRIBUTION archetype even at high asymmetry",
   not entry.decide(cand(arch='DISTRIBUTION'), m())['pass'])

print("── archetype routing + total asymmetry (§10-B/C) ──")
shock = entry.decide(cand('SHOCK_ACCUMULATION'), m(z=5.5))
ck("a strong shock enters via FAST_SHOCK", shock['pass'] and shock['route'] == 'FAST_SHOCK')

# Persistent AAPL-style: rank #3, modest abnormality, but strong persistence + control → should
# still enter on the PERSISTENT_BUILD route (rank does not veto it — §6/§10-C).
persist = entry.decide(
    cand('PERSISTENT_ACCUMULATION', self_sust=0.7, cont=0.85, resp=0.03),
    m(rank=3, share=0.35, z=2.0, ctrl=0.85))
ck("a persistent build enters despite low rank/abnormality (compensating persistence)",
   persist['pass'] and persist['route'] == 'PERSISTENT_BUILD')

# AMZN-style broad ladder: single-contract notional is small, but the surface's breadth-adjusted
# mass is large → the notional evidence should come from the cluster, letting it enter.
amzn = entry.decide(
    cand('SHOCK_ACCUMULATION', notional=2.0e4, surface={'breadth_adjusted_strength': 5.0e5}),
    m(z=4.5))
ck("broad-surface ladder contributes cluster notional (not one strike)", amzn['pass'])

# A weak candidate across the board fails the asymmetry threshold (not a hard veto).
weak = entry.decide(
    cand('UNCLASSIFIED', notional=2.0e4, resp=-0.02, self_sust=0.0, cont=0.2, dist_low=1.4),
    m(rank=4, share=0.15, z=0.5, ctrl=0.55))
ck("a weak candidate fails on low total asymmetry (soft, not veto)",
   not weak['pass'] and weak['reason'] == 'MISSED_DUE_TO_LOW_ASYMMETRY')

ck("evidence dimensions are all in [0,1]",
   all(0.0 <= v <= 1.0 for v in entry.evidence(cand(), m()).values()))


# audit: route decision must expose the score decomposition (v3 second-audit follow-up)
_c = {'side':'PUT','archetype':{'archetype':'CROSS_EXPIRY_ACCUMULATION'},'notional':1,'dist_low':1.2,
      'self_sust':0.55,'cont_prob':0.6,'resp_event':0.0,'surface':{},'acceptance':{}}
_m = {'rank':3,'attention_share':0.16,'mass_z':2.5,'put_control':0.78}
_d = entry.decide(_c, _m)
ck("route decision exposes contributions", isinstance(_d.get('contributions'), dict) and len(_d['contributions'])==7)
ck("route decision exposes top_drag (3 dims)", len(_d.get('top_drag') or [])==3)
ck("contributions sum to the score", abs(sum(_d['contributions'].values()) - _d['score']) < 1e-6)
ck("shortfall is threshold - score when failing", _d['shortfall'] >= 0)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
