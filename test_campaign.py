"""Campaign assessment (§14/§15) tests. Run: python test_campaign.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analysis import campaign as C

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

def M(share=0.5, z=4.0, rank=1, ctrl=0.8, side='CALL'):
    return {'symbol': 'AAPL', 'attention_share': share, 'mass_z': z, 'rank': rank,
            'call_control': ctrl if side == 'CALL' else 1 - ctrl,
            'put_control': 1 - ctrl if side == 'CALL' else ctrl}

def Cand(side='CALL', accum=True, dist=1.2, resp=0.1, label='SINGLE_STRIKE_ACCUMULATION'):
    return {'symbol': 'AAPL', 'side': side, 'accumulation': accum, 'dist_low': dist,
            'resp_event': resp, 'acc_label': label}

# ── all five signals present + strong → CONFIRMED ──
a = C.assess(M(), Cand())
ck("genuine campaign → confirmed", a['confirmed'] and not a['missing'])
ck("confirmed campaign scores well", a['score'] >= 62)
ck("thesis names the campaign", 'CAMPAIGN QUALIFIED' in a['thesis'])

# ── each missing signal blocks the campaign and is named ──
ck("not leading Mag-7 → not a campaign (leadership)",
   'leadership' in C.assess(M(rank=2), Cand())['missing'])
ck("dormant not woken (low z) → missing waking",
   'waking' in C.assess(M(z=1.0), Cand())['missing'])
ck("no accumulation → missing accumulation",
   'accumulation' in C.assess(M(), Cand(accum=False))['missing'])
ck("side doesn't control the tape → missing control",
   'control' in C.assess(M(ctrl=0.55), Cand())['missing'])
ck("premium already extended → missing cheap",
   'cheap' in C.assess(M(), Cand(dist=3.0))['missing'])
ck("any missing signal → not confirmed", not C.assess(M(rank=2), Cand())['confirmed'])

# ── strong signals but a NEGATIVE premium response lowers conviction ──
neg = C.assess(M(), Cand(resp=-0.03, accum=False))
ck("distribution (no accumulation) → not confirmed", not neg['confirmed'])

# ── campaign-death vocabulary (§15 exit narration) ──
ck("rotation → 'rotated'", 'rotated' in C.campaign_end('ROTATION'))
ck("exhaustion → 'exhausted'", 'exhausted' in C.campaign_end('STATISTICAL_EXHAUSTION'))
ck("control transfer → 'control'", 'control' in C.campaign_end('CONTROL_TRANSFER'))
ck("profit target → 'objective'", 'objective' in C.campaign_end('STRUCTURAL_TP2'))

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
