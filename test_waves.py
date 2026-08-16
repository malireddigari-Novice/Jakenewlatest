"""Wave state-machine + mass tests. Run: python test_waves.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import campaign
from analysis import mass
from analysis.waves import WaveEngine

# Base wave tests exercise the validated 6-state path — pin the newer exit flags OFF so they are
# deterministic regardless of what .env enables live. The Phase-1 / confidence sections below toggle
# these themselves around their own checks.
config.STABILIZE_ENABLED = False
config.CAMPAIGN_CONFIDENCE_ENABLED = False
config.RAW_FLIP_EXIT_DISABLED = False   # legacy raw-flip path is exercised in isolation below

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

# ── MASS ─────────────────────────────────────────────────────────────────────
print("── mass ──")
ck("ATM relevance ~1", abs(mass.relevance_weight(100, 100) - 1.0) < 1e-9)
ck("adjacent strike weight < ATM and > 0",
   0 < mass.relevance_weight(102.5, 100) < 1.0)
strikes = {(100.0, 'CALL'): {'fresh_vol': 5000, 'mark': 2.0},
           (102.5, 'CALL'): {'fresh_vol': 500, 'mark': 1.2},
           (100.0, 'PUT'):  {'fresh_vol': 400, 'mark': 1.5}}
m = mass.compute_masses(strikes, 100.0)
ck("call mass dominates", m['call_mass'] > m['put_mass'])
ck("single-strike dominant classified", m['call']['class'] == 'SINGLE_STRIKE_DOMINANT')

tmass = mass.TickerMass()
r0 = tmass.update(m)
ck("first Z is 0 (baseline seeding)", r0['mass_z'] == 0.0)
big = mass.compute_masses({(100.0, 'CALL'): {'fresh_vol': 50000, 'mark': 2.0}}, 100.0)
r1 = tmass.update(big)
ck("surge produces positive Z + velocity", r1['mass_z'] > 0 and r1['velocity'] > 0)
ck("call control ~1 on all-call flow", r1['call_control'] > 0.99)

# ── WAVE STATE MACHINE ───────────────────────────────────────────────────────
print("── waves ──")
def metric(sym, side='CALL', share=0.5, z=4.0, ctrl=0.8, vel=1e6, acc=1e5,
           opp_z=0.0, opp_vel=0.0, opp_acc=0.0, rank=1, score=90.0, fast=5e6):
    cc, pc = (ctrl, 1 - ctrl) if side == 'CALL' else (1 - ctrl, ctrl)
    return {'symbol': sym, 'dominant_side': side, 'attention_share': share, 'mass_z': z,
            'ticker_mass': fast, 'fast_mass': fast, 'impulse': 2.0,
            'call_control': cc, 'put_control': pc, 'signed_control': cc - pc,
            'call_z': z if side == 'CALL' else opp_z, 'put_z': opp_z if side == 'CALL' else z,
            'velocity': vel, 'acceleration': acc,
            'call_velocity': vel if side == 'CALL' else opp_vel,
            'put_velocity': opp_vel if side == 'CALL' else vel,
            'call_acceleration': acc if side == 'CALL' else opp_acc,
            'put_acceleration': opp_acc if side == 'CALL' else acc,
            'rank': rank, 'attention_score': score,
            'call': {'class': 'SINGLE_STRIKE_DOMINANT'}, 'put': {'class': 'SINGLE_STRIKE_DOMINANT'}}

we = WaveEngine(); we.new_session()
t = 1000.0

# A strong opening burst → FORMING → ACTIVE(immediate) → one primary entry.
res = we.evaluate([metric('NVDA')], {'NVDA': metric('NVDA')}, set(), t)
ck("strong burst issues exactly one entry", len(res['enter']) == 1 and res['enter'][0]['ticker'] == 'NVDA')
wave_id = res['enter'][0]['wave_id']
we.waves[('NVDA', 'CALL')].entry_issued = True     # engine sets this after the fill

# Next polls, still strong → NO new entry (one wave = one entry).
t += 60
dup = we.evaluate([metric('NVDA')], {'NVDA': metric('NVDA')}, {('NVDA', 'CALL')}, t)
ck("no duplicate entry inside the same wave", len(dup['enter']) == 0)

# Opposite side merely AWAKENING (puts active but not controlling) → HOLD, no exit.
t += 60
awak = we.evaluate([metric('NVDA', opp_z=2.5, opp_vel=5e5)],
                   {'NVDA': metric('NVDA', opp_z=2.5, opp_vel=5e5)}, {('NVDA', 'CALL')}, t)
ck("puts awakening (not controlling) does NOT exit the call", len(awak['exit']) == 0)

# OVERWHELMING opposite control bypasses the min-hold → immediate exit even on a young wave.
def flip(sym, put_ctrl, put_z, call_vel=-50, put_acc=5e4):
    return {'symbol': sym, 'dominant_side': 'PUT', 'attention_share': 0.6, 'mass_z': put_z,
            'ticker_mass': 5e6, 'fast_mass': 5e6, 'impulse': 2.0,
            'call_control': 1 - put_ctrl, 'put_control': put_ctrl, 'signed_control': 1 - 2 * put_ctrl,
            'call_z': 0.5, 'put_z': put_z, 'velocity': 1e6, 'acceleration': 1e5,
            'call_velocity': call_vel, 'put_velocity': 5e5, 'call_acceleration': -10, 'put_acceleration': put_acc,
            'rank': 1, 'attention_score': 90, 'call': {'class': 'X'}, 'put': {'class': 'X'}}
we_o = WaveEngine(); we_o.new_session(); to = 5000.0
we_o.evaluate([metric('NVDA')], {'NVDA': metric('NVDA')}, set(), to)
we_o.waves[('NVDA', 'CALL')].entry_issued = True
ov = flip('NVDA', 0.8, 6.0)
ro = we_o.evaluate([ov], {'NVDA': ov}, {('NVDA', 'CALL')}, to + 60)      # young wave (60s)
ck("overwhelming flip bypasses min-hold → immediate exit",
   any(e['reason'] == 'CONTROL_FLIP_OVERWHELMING' for e in ro['exit']))

# v3-review item 13: when the ReversalCluster owns opposite-side exits, a RAW overwhelming flip must
# NOT independently flatten the position (that recreated the round-trip failures). Same setup, gate on.
config.RAW_FLIP_EXIT_DISABLED = True
config.REVERSAL_ENABLED = True
we_r = WaveEngine(); we_r.new_session()
we_r.evaluate([metric('NVDA')], {'NVDA': metric('NVDA')}, set(), to)
we_r.waves[('NVDA', 'CALL')].entry_issued = True
rr = we_r.evaluate([ov], {'NVDA': ov}, {('NVDA', 'CALL')}, to + 60)
ck("raw overwhelming flip does NOT exit when reversal owns opposite exits (item 13)",
   not any(e['reason'] == 'CONTROL_FLIP_OVERWHELMING' for e in rr['exit']))
config.RAW_FLIP_EXIT_DISABLED = False   # restore for the remaining legacy-path checks

# MODERATE persistent transfer: protected during min-hold, then exits after 2 confirmations.
we_p = WaveEngine(); we_p.new_session(); tp = 6000.0
we_p.evaluate([metric('NVDA')], {'NVDA': metric('NVDA')}, set(), tp)
we_p.waves[('NVDA', 'CALL')].entry_issued = True
mod = flip('NVDA', 0.58, 2.5)
young = we_p.evaluate([mod], {'NVDA': mod}, {('NVDA', 'CALL')}, tp + 60)     # 60s < 180s hold
ck("young wave protected from a moderate flip", not young['exit'])
r1 = we_p.evaluate([mod], {'NVDA': mod}, {('NVDA', 'CALL')}, tp + 200)       # past hold, 1st confirm
r2 = we_p.evaluate([mod], {'NVDA': mod}, {('NVDA', 'CALL')}, tp + 260)       # 2nd confirm → exit
ck("moderate transfer exits only after 2 confirmations past min-hold",
   (not r1['exit']) and any(e['reason'] == 'CONTROL_TRANSFER' for e in r2['exit']))

# ── rotation hysteresis ──
we2 = WaveEngine(); we2.new_session(); t = 2000.0
# AAPL held (incumbent). NVDA challenger with only a small score margin → NO rotation exit.
inc = metric('AAPL', score=85)
chal_small = metric('NVDA', score=90, share=0.35)      # margin 5 < 8
r = we2.evaluate([chal_small, inc], {'AAPL': inc, 'NVDA': chal_small}, {('AAPL', 'CALL')}, t)
ck("small score lead does NOT rotate the incumbent out", not any(e['reason'] == 'ROTATION' for e in r['exit']))
# Big, confirmed margin → rotation exit — but only once the incumbent's OWN wave is fading.
t += 240
we2.waves[('AAPL', 'CALL')].state = 'DECAYING'      # incumbent thesis weakening
fading = metric('AAPL', score=85, share=0.20, z=1.0, vel=-100, acc=-100)   # stays decaying
chal_big = metric('NVDA', score=105, share=0.45, z=4.0, ctrl=0.75)          # margin 20, confirmed
r2 = we2.evaluate([chal_big, fading], {'AAPL': fading, 'NVDA': chal_big}, {('AAPL', 'CALL')}, t)
ck("confirmed rotation exits a FADING incumbent", any(e['reason'] == 'ROTATION' for e in r2['exit']))
# ...but a still-ACTIVE, healthy incumbent is NOT rotated out on a higher challenger score.
we4 = WaveEngine(); we4.new_session(); tt = 7000.0
we4.evaluate([metric('AAPL', score=85)], {'AAPL': metric('AAPL', score=85)}, set(), tt)
we4.waves[('AAPL', 'CALL')].entry_issued = True
tt += 240
healthy = metric('AAPL', score=85)      # still strong → wave recovers/stays ACTIVE
chal = metric('NVDA', score=105, share=0.45, z=4.0, ctrl=0.75)
r3 = we4.evaluate([chal, healthy], {'AAPL': healthy, 'NVDA': chal}, {('AAPL', 'CALL')}, tt)
ck("healthy ACTIVE incumbent is NOT rotated out for a higher score",
   not any(e['reason'] == 'ROTATION' for e in r3['exit']))

# ── refractory ──
we3 = WaveEngine(); we3.new_session(); t = 3000.0
r = we3.evaluate([metric('TSLA')], {'TSLA': metric('TSLA')}, set(), t)
we3.waves[('TSLA', 'CALL')].entry_issued = True
we3.force_end('TSLA', 'CALL', t, reason='STRUCTURAL')      # wave ends
t += 120                                                    # 2 min later (< 7 min refractory)
again = we3.evaluate([metric('TSLA', z=3.0)], {'TSLA': metric('TSLA', z=3.0)}, set(), t)
ck("refractory suppresses immediate re-entry on residual activity", len(again['enter']) == 0)
t += 60
renew = we3.evaluate([metric('TSLA', z=5.0)], {'TSLA': metric('TSLA', z=5.0)}, set(), t)  # exceptional
ck("exceptional shock (z>=4) overrides refractory", len(renew['enter']) == 1)

# ── Phase 1: campaign memory / stabilization (STABILIZE_ENABLED) ──────────────
print("── phase 1: stabilization ──")
config.STABILIZE_ENABLED = True
INTACT = {'control_ok': True, 'opp_strong': False, 'dist_high': False,
          'progressing': True, 'recovering': False}

# A cooling-but-structurally-intact incumbent must move to STABILIZING and NOT be exited —
# this is the core "cooling is not death" fix (spec §19-21, §31).
wes = WaveEngine(); wes.new_session(); ts = 8000.0
wes.evaluate([metric('NVDA')], {'NVDA': metric('NVDA')}, set(), ts)
wes.waves[('NVDA', 'CALL')].entry_issued = True
cool = metric('NVDA', share=0.10, z=0.5, ctrl=0.70, vel=-100, acc=-100)   # cooled, still controlling
hi = {('NVDA', 'CALL'): INTACT}
last = None
ts += 240                                                                 # past the 180s min-hold
for _ in range(6):
    ts += 60
    last = wes.evaluate([cool], {'NVDA': cool}, {('NVDA', 'CALL')}, ts, health_by=hi)
ck("cooling-but-intact wave → STABILIZING (campaign memory), no exit",
   wes.waves[('NVDA', 'CALL')].state == 'STABILIZING' and not last['exit'])

# A STABILIZING wave that reaccelerates returns to ACTIVE with the SAME wave_id (no new entry).
wid = wes.waves[('NVDA', 'CALL')].wave_id
ts += 60
back = wes.evaluate([metric('NVDA')], {'NVDA': metric('NVDA')}, {('NVDA', 'CALL')}, ts, health_by=hi)
ck("reaccelerating STABILIZING wave recovers to ACTIVE, same wave_id, no new entry",
   wes.waves[('NVDA', 'CALL')].state == 'ACTIVE'
   and wes.waves[('NVDA', 'CALL')].wave_id == wid and not back['enter'])

# Genuine multi-signal deterioration (control lost + premium failing) → STATISTICAL_EXHAUSTION.
wed = WaveEngine(); wed.new_session(); td = 9000.0
wed.evaluate([metric('NVDA')], {'NVDA': metric('NVDA')}, set(), td)
wed.waves[('NVDA', 'CALL')].entry_issued = True
bad = metric('NVDA', share=0.10, z=0.5, ctrl=0.50, vel=-100, acc=-100)    # control below stabilize floor
hd = {('NVDA', 'CALL'): {'control_ok': False, 'opp_strong': False, 'dist_high': False,
                         'progressing': False, 'recovering': False}}
td += 240
exd = []
for _ in range(5):
    td += 60
    exd += wed.evaluate([bad], {'NVDA': bad}, {('NVDA', 'CALL')}, td, health_by=hd)['exit']
ck("genuine deterioration still exits on STATISTICAL_EXHAUSTION",
   any(e['reason'] == 'STATISTICAL_EXHAUSTION' for e in exd))
config.STABILIZE_ENABLED = False

# ── Phase 2: early detection / latency (EARLY_DETECT_ENABLED) ─────────────────
print("── phase 2: early detection ──")
config.EARLY_DETECT_ENABLED = True
wee = WaveEngine(); wee.new_session(); te = 11000.0
# Sub-forming abnormal flow (z between EARLY_WATCH_Z=1.5 and WAVE_FORMING_Z=2.0): WATCH, no birth.
watchm = metric('AAPL', z=1.7, ctrl=0.60, share=0.20, vel=1e5, acc=1e4)
wee.evaluate([watchm], {'AAPL': watchm}, set(), te)
em = wee.early_marks('AAPL', 'CALL')
ck("sub-forming abnormal flow records WATCH before wave birth",
   em.get('state') == 'WATCH' and em.get('watch_ts') is not None)
ck("no wave is born below the forming Z", ('AAPL', 'CALL') not in wee.waves)
te += 60
wee.evaluate([watchm], {'AAPL': watchm}, set(), te)
ck("sustained participation → BUILDING (with an earlier building_ts)",
   wee.early_marks('AAPL', 'CALL').get('state') == 'BUILDING'
   and wee.early_marks('AAPL', 'CALL').get('building_ts') is not None)
config.EARLY_DETECT_ENABLED = False

# EarlyAccumulationScore: higher for early/cheap/controlled/responding than chased/distributing.
mg = metric('AAPL', z=4.0, ctrl=0.80)
eas_good = campaign.early_accumulation_score(
    mg, {'side': 'CALL', 'dist_low': 1.05, 'resp_event': 0.10, 'shakeout': 0.0, 'dist_prob': 0.05})
eas_bad = campaign.early_accumulation_score(
    mg, {'side': 'CALL', 'dist_low': 1.90, 'resp_event': -0.08, 'shakeout': 0.0, 'dist_prob': 0.70})
ck("EAS rewards early/cheap/responding over chased/distributing",
   0 <= eas_good <= 100 and eas_good > eas_bad)

# ── MSFT rank-1 relaxation under ENTRY_ROUTES (non-leader can qualify) ─────────
print("── rank relaxation (routes) ──")
config.STABILIZE_ENABLED = False
config.CAMPAIGN_CONFIDENCE_ENABLED = False
config.ENTRY_ROUTES_ENABLED = False
wr = WaveEngine(); wr.new_session()
strong2 = lambda: metric('MSFT', share=0.45, z=4.5, ctrl=0.8, rank=2, score=90)
off = wr.evaluate([strong2()], {'MSFT': strong2()}, set(), 15000.0)
ck("rank-2 campaign is NOT proposed with routes OFF (strict rank-1 discipline)", len(off['enter']) == 0)
config.ENTRY_ROUTES_ENABLED = True
wr2 = WaveEngine(); wr2.new_session()
on = wr2.evaluate([strong2()], {'MSFT': strong2()}, set(), 16000.0)
ck("rank-2 strong campaign IS proposed with routes ON (MSFT 495C fix)", len(on['enter']) == 1)
config.ENTRY_ROUTES_ENABLED = False

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
