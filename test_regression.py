"""
Frozen-time regression suite (spec §59) + negative controls (addendum #16).

Each named case is asserted through the PURE classifiers using ONLY point-in-time inputs — no future
price is ever fed to a classifier (addendum #15 look-ahead guard). Future performance is used only to
LABEL the case in a comment, never as an input. If a future change regresses the intended behavior on
one of these canonical cases, this suite fails.

Run: python test_regression.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import qualified as q
from analysis import barshock as bs
from analysis import reversal as rv
from analysis import campaign_store as cs
from analysis import hypotheses as hp
from analysis import inventory as inv

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

# ── NVDA 8/11 — distributed CALL mass must NOT beat the clean PUT event ──────────
print("── NVDA 8/11: qualified control (220C distributed vs 220P concentrated) ──")
# 220C: much larger raw pool, but DISTRIBUTED shape + premium REJECTION + decelerating (stale).
call_q = q.side_quality('DISTRIBUTED', 'REJECTION', 1.0, -5.0)
# 220P: smaller pool, SINGLE_STRIKE_DOMINANT + premium ABSORPTION + fresh/accelerating.
put_q = q.side_quality('SINGLE_STRIKE_DOMINANT', 'ABSORPTION', 4.0, 12.0)
qc = q.qualified_control(call_mass=1_000_000, put_mass=400_000, call_q=call_q, put_q=put_q)
ck("qualified control flips CALL→PUT", qc['dominant_side'] == 'PUT' and qc['flipped_from_raw'])
ck("220P seniority: qualified put mass > qualified call mass", qc['q_put_mass'] > qc['q_call_mass'])

# ── AAPL 307.5P — a dominant STANDALONE print stays entry-eligible ───────────────
print("── AAPL 307.5P: dominant standalone event is a genuine event ──")
quiet = [8, 5, 9, 6, 11, 7, 10, 6]
standalone = bs.bar_shock(quiet + [4960], mark=1.0)          # ~4.96K vs a near-empty baseline
ck("standalone bar is significant", standalone['significant'] and standalone['shock'] >= config.BARSHOCK_MIN_Z)
etype = bs.classify_event(standalone['shock'], rel_shock=5.0, cluster_count=1)   # isolated
ck("classified as a real (not NONE) event despite low density", etype != 'NONE')
allow, why = bs.entry_gate({'event_type': etype, 'significant': True})
ck("standalone passes the barshock entry-gate (isolation is not weakness)", allow)

# ── TSLA 8/13 — coordinated CALL chain outranks scattered PUT activity ───────────
print("── TSLA 8/13: coordinated call chain outranks scattered puts ──")
# calls: coordinated chain + acceptance + fresh;  puts: distributed + rejection.
tsla_call_q = q.side_quality('COORDINATED_CHAIN', 'ABSORPTION', 3.5, 8.0)
tsla_put_q = q.side_quality('DISTRIBUTED', 'REJECTION', 1.5, -2.0)
# even with the puts carrying a briefly-larger raw pool, the qualified call side wins.
tqc = q.qualified_control(call_mass=600_000, put_mass=650_000, call_q=tsla_call_q, put_q=tsla_put_q)
ck("coordinated call chain wins side control", tqc['dominant_side'] == 'CALL')

# ── GOOGL 8/10 — a few CALL-control polls must NOT flip the funded PUT campaign ──
print("── GOOGL 8/10: early PUT campaign survives a few opposite-control polls ──")
cl = rv.new_cluster('GOOGL', 'PUT')
# three polls of mild opposite (CALL) pressure — abnormal but not a confirmed cross-strike cluster.
mild = {'opp_abnormal': True, 'opp_control': 0.56, 'opp_premium_accept': False,
        'cross_strike': False, 'incumbent_progress_fail': False, 'opp_strike': 355.0}
for t in (0, 60, 120):
    cl = rv.update(cl, mild, t)
ck("a few CALL-control polls do NOT reach REVERSAL_ACTIVATED", cl['state'] != 'REVERSAL_ACTIVATED')
ck("outcome is HOLD (no premature reverse)", rv.outcome(cl, opp_qualifies=True) == 'HOLD')

# ── AMZN overnight — a surviving-expiry campaign serializes across sessions ──────
print("── AMZN overnight: surviving-expiry campaign carries forward ──")
camps = {'AMZN-CALL-20260814-270': cs.record('AMZN', 'CALL', 270.0, '2026-08-15',
                                             '2026-08-14', 0.7, 'ACTIVE', 1_500_000)}
carried = cs.carry_forward(camps, '2026-08-15')     # Friday-expiry campaign, still alive Friday
ck("live-expiry campaign carried into next session", len(carried) == 1)
ck("carried campaign marked overnight/intact",
   list(carried.values())[0]['overnight'] and list(carried.values())[0]['overnight_state'] == 'OVERNIGHT_INTACT')
dead = cs.carry_forward({'X-CALL-20200101-1': cs.record('X', 'CALL', 1, '2020-01-01', '2020-01-01', 0.5, 'ACTIVE')},
                        '2026-08-15')
ck("expired campaign is NOT carried", len(dead) == 0)

# ── NEGATIVE CONTROL (#16) — same morphology, opposite economics ─────────────────
print("── negative control: a beautiful event that should FAIL the intent test ──")
# The winner and the look-alike have the SAME abnormal volume morphology (both 'significant' events);
# only the economic response separates them. Morphology alone must not decide direction.
winner = hp.assess({'acceptance': 'ABSORPTION', 'resp_event': 0.18, 'self_sust': 0.6,
                    'inv_ambiguity': 'LOW', 'package': 'OUTRIGHT_LIKELY', 'hedge': 'DIRECTIONAL'})
lookalike = hp.assess({'acceptance': 'REJECTION', 'resp_event': -0.12, 'self_sust': 0.0,
                       'inv_ambiguity': 'HIGH', 'inv_state': 'LIKELY_PARTIAL_EXIT',
                       'package': 'OUTRIGHT_LIKELY', 'hedge': 'NEUTRAL'})
ck("winner reads FRESH_DIRECTIONAL", winner['top'] == 'FRESH_DIRECTIONAL')
ck("look-alike does NOT read fresh directional", lookalike['top'] != 'FRESH_DIRECTIONAL')
ck("directional confidence separates winner from look-alike",
   winner['directional_p'] > 2 * lookalike['directional_p'])
# and the inventory layer would abstain on the look-alike's collision, not the winner's fresh print
la_inv = inv.assess(inv.observe(None, price=3.0, size=1000, ts='t0'), current_price=1.0, new_size=1000)
ck("look-alike inventory collision → HIGH ambiguity (PASS)", la_inv['ambiguity'] == 'HIGH')
ck("winner fresh print → LOW ambiguity (tradeable)",
   inv.assess(None, current_price=1.0, new_size=1000)['ambiguity'] == 'LOW')

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
