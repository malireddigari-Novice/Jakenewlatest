"""Campaign hold / confidence tests (follow-up P1). Run: python test_hold.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import hold
from analysis.waves import WaveEngine

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── premium-structure metrics ──")
persistent = [450, 600, 700, 650, 800, 900, 750]        # AAPL-style continued participation
spike = [5_000_000, 0, 0, 0, 0, 0, 0]                    # TSLA-style single burst
ck("persistence higher for a sustained build than a lone spike",
   hold.premium_persistence(persistent) > hold.premium_persistence(spike))
ck("smoothness higher for an orderly climb than a whipsaw",
   hold.premium_smoothness([3.0, 3.1, 3.25, 3.45, 4.2, 5.8])
   > hold.premium_smoothness([3.0, 6.0, 2.0, 7.0, 4.0]))
ck("higher-low quality higher for rising lows than falling lows",
   hold.higher_low_quality([3.0, 3.5, 3.2, 4.0, 3.6, 4.5])
   > hold.higher_low_quality([5.0, 4.5, 4.6, 3.8, 3.9, 3.0]))

print("── confidence_step ──")
INTACT = {'control_ok': True, 'opp_strong': False, 'dist_high': False, 'progressing': True,
          'higher_low': True}
c_hold, _ = hold.confidence_step(0.75, INTACT, rotation_active=False)
ck("healthy hold drifts confidence up (never down)", c_hold >= 0.75)
c_rot, cause_rot = hold.confidence_step(0.75, INTACT, rotation_active=True)
ck("rotation alone is a small penalty, not a collapse", 0.60 < c_rot < 0.75 and cause_rot == 'ROTATION')
c_active, _ = hold.confidence_step(0.75, {**INTACT, 'active': True}, rotation_active=True)
ck("an ACTIVE campaign resists rotation (recovery bonus offsets the penalty)", c_active >= 0.75)
BAD = {'control_ok': False, 'opp_strong': True, 'dist_high': True, 'progressing': False,
       'higher_low': False}
c_bad, cause_bad = hold.confidence_step(0.75, BAD, rotation_active=False)
ck("multi-signal deterioration collapses confidence", c_bad < config.HOLD_EXIT_THRESHOLD)
ck("dominant cause of collapse is the biggest penalty (distribution)", cause_bad == 'DISTRIBUTION')
ck("exit label maps distribution → VERIFIED_DISTRIBUTION",
   hold.exit_reason_from('DISTRIBUTION', BAD) == 'VERIFIED_DISTRIBUTION')
ck("diffuse cause → TRUE_MULTI_VARIABLE_EXHAUSTION",
   hold.exit_reason_from(None, {}) == 'TRUE_MULTI_VARIABLE_EXHAUSTION')

# ── wave integration: rotation is a penalty, not a command ────────────────────
print("── confidence-based exits (wave engine) ──")
def metric(sym, side='CALL', share=0.5, z=4.0, ctrl=0.8, vel=1e6, acc=1e5, rank=1, score=90.0):
    cc, pc = (ctrl, 1 - ctrl) if side == 'CALL' else (1 - ctrl, ctrl)
    return {'symbol': sym, 'dominant_side': side, 'attention_share': share, 'mass_z': z,
            'ticker_mass': 5e6, 'fast_mass': 5e6, 'impulse': 2.0,
            'call_control': cc, 'put_control': pc, 'signed_control': cc - pc,
            'call_z': z, 'put_z': 0.0, 'velocity': vel, 'acceleration': acc,
            'call_velocity': vel if side == 'CALL' else 0, 'put_velocity': 0 if side == 'CALL' else vel,
            'call_acceleration': acc if side == 'CALL' else 0,
            'put_acceleration': 0 if side == 'CALL' else acc,
            'rank': rank, 'attention_score': score, 'call': {'class': 'X'}, 'put': {'class': 'X'}}

config.CAMPAIGN_CONFIDENCE_ENABLED = True
config.STABILIZE_ENABLED = False

# Healthy, still-ACTIVE incumbent out-ranked by a stronger challenger → must NOT rotate out.
we = WaveEngine(); we.new_session(); t = 1000.0
we.evaluate([metric('NVDA')], {'NVDA': metric('NVDA')}, set(), t)
we.waves[('NVDA', 'CALL')].entry_issued = True
t += 300
INTACT_ACTIVE = {'control_ok': True, 'opp_strong': False, 'dist_high': False, 'progressing': True,
                 'higher_low': True, 'self_sustaining': True}
last = None
for _ in range(8):
    t += 60
    inc = metric('NVDA', share=0.5, z=4.0, ctrl=0.8, rank=2)
    chal = metric('AAPL', score=110, share=0.5, z=4.5, ctrl=0.8, rank=1)
    last = we.evaluate([chal, inc], {'AAPL': chal, 'NVDA': inc}, {('NVDA', 'CALL')}, t,
                       health_by={('NVDA', 'CALL'): INTACT_ACTIVE})
ck("healthy ACTIVE incumbent is NOT rotated out (confidence held)",
   not last['exit'] and we.waves[('NVDA', 'CALL')].confidence >= config.HOLD_EXIT_THRESHOLD)

# Verified deterioration → exits with a §20 campaign label.
we2 = WaveEngine(); we2.new_session(); t = 5000.0
we2.evaluate([metric('NVDA')], {'NVDA': metric('NVDA')}, set(), t)
we2.waves[('NVDA', 'CALL')].entry_issued = True
t += 300
BADH = {'control_ok': False, 'opp_strong': True, 'dist_high': True, 'progressing': False,
        'higher_low': False, 'self_sustaining': False}
exits = []
for _ in range(4):
    t += 60
    bad = metric('NVDA', share=0.1, z=0.5, ctrl=0.4, vel=-100, acc=-100)
    exits += we2.evaluate([bad], {'NVDA': bad}, {('NVDA', 'CALL')}, t, health_by={('NVDA', 'CALL'): BADH})['exit']
LABELS = {'VERIFIED_DISTRIBUTION', 'PERSISTENT_CONTROL_TRANSFER', 'OPPOSITE_SIDE_CAMPAIGN_CONFIRMED',
          'PREMIUM_STRUCTURE_FAILURE', 'RESILIENCE_FAILURE', 'TRUE_MULTI_VARIABLE_EXHAUSTION'}
ck("verified deterioration exits with a §20 confidence label",
   any(e['reason'] in LABELS for e in exits))
config.CAMPAIGN_CONFIDENCE_ENABLED = False

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
