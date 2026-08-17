"""Per-strike BarVolumeShock tests (new-spec P2). Run: python test_barshock.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import barshock as bs

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

print("── BarVolumeShock (robust baseline + tiny-baseline safeguard) ──")
# A normally-quiet contract that suddenly prints 1,000 → high shock AND significant.
quiet = bs.bar_shock([20, 30, 25, 15, 30, 1000], mark=2.5)
ck("quiet contract + sudden large print → high shock", quiet['shock'] >= config.BARSHOCK_MIN_Z)
ck("...and it is significant (clears absolute floor)", quiet['significant'])
# A persistently-busy contract adapts into its own background (median high → low shock).
busy = bs.bar_shock([900, 1000, 950, 1100, 980, 1000], mark=2.5)
ck("persistently-busy contract normalizes into background (low shock)", busy['shock'] < config.BARSHOCK_MIN_Z)
# Tiny baseline (#6): 1→20 is a huge RATIO but not economically significant → not significant.
tiny = bs.bar_shock([1, 0, 1, 1, 0, 20], mark=0.10)
ck("tiny-baseline spike is NOT significant (absolute floor)", not tiny['significant'])
ck("short history → no shock", bs.bar_shock([100, 200])['shock'] == 0.0)

print("── strike position at event time (#8) ──")
ck("call strike below spot → ITM", bs.strike_position(215, 220, 'CALL').endswith('ITM'))
ck("call strike above spot → OTM", bs.strike_position(225, 220, 'CALL').endswith('OTM'))
ck("put strike above spot → ITM", bs.strike_position(225, 220, 'PUT').endswith('ITM'))
ck("near spot → ATM", bs.strike_position(220, 220, 'CALL') == 'ATM')

print("── relative + cluster + classification ──")
ck("relative shock vs neighbors", bs.relative_shock(9.0, [3.0, 2.0]) == 3.0)
ck("cluster counts elevated strikes", bs.cluster_shock([4.0, 5.0, 3.5, 1.0]) == 3)
ck("many strikes elevated → COORDINATED_MULTI_STRIKE_EVENT",
   bs.classify_event(5.0, 1.1, 3) == 'COORDINATED_MULTI_STRIKE_EVENT')
ck("one strike dominant vs neighbors → CONCENTRATED_SINGLE_STRIKE_EVENT",
   bs.classify_event(9.0, 3.0, 1) == 'CONCENTRATED_SINGLE_STRIKE_EVENT')
ck("below-threshold shock → NONE", bs.classify_event(1.0, 1.0, 0) == 'NONE')

print("── entry_gate (hard evidence gate) ──")
# a genuine concentrated event → ALLOW
ok, why = bs.entry_gate({'event_type': 'CONCENTRATED_SINGLE_STRIKE_EVENT', 'significant': True})
ck("significant concentrated event → allow", ok)
# a coordinated multi-strike event → ALLOW
ok, why = bs.entry_gate({'event_type': 'COORDINATED_MULTI_STRIKE_EVENT', 'significant': True})
ck("significant coordinated event → allow", ok)
# no abnormal event (background flow) → VETO
ok, why = bs.entry_gate({'event_type': 'NONE', 'significant': False})
ck("no abnormal event → veto", (not ok) and why == 'NO_ABNORMAL_EVENT')
# clears Z but fails the absolute floor (tiny-baseline) → VETO
ok, why = bs.entry_gate({'event_type': 'STRIKE_EVENT', 'significant': False})
ck("sub-floor (not significant) event → veto", (not ok) and why == 'SUBTHRESHOLD_EVENT')
# missing data → ALLOW (never starve entries on absent evidence)
ok, why = bs.entry_gate(None)
ck("missing barshock data → allow (no veto on absent evidence)", ok and why == 'NO_BARSHOCK_DATA')

print("── time-of-day normalization (#7) ──")
ck("session_phase: open", bs.session_phase(5) == 'OPEN')
ck("session_phase: midday", bs.session_phase(150) == 'MIDDAY')
# An opening spike that is NORMAL for the open should read tamer once judged vs same-phase history.
series = [20, 30, 25, 1000]                       # rolling window sees a huge jump (short history)
open_hist = [900, 1100, 1000, 950, 1050, 1000]    # but 1,000 is normal AT THE OPEN for this contract
tod = bs.bar_shock_tod(series, mark=2.5, phase_baseline=open_hist)
ck("tod_shock computed from same-phase history", tod['tod_shock'] is not None)
ck("effective shock is the more conservative (open spike is normal for the open)",
   tod['effective_shock'] <= tod['shock'])
# with no phase history yet, effective shock falls back to the rolling shock
tod2 = bs.bar_shock_tod(series, mark=2.5, phase_baseline=[])
ck("no phase history → effective == rolling shock", tod2['effective_shock'] == tod2['shock'])

print("── baseline quality tag (v3-audit item 7) ──")
ck("unseeded baseline → UNSEEDED", bs.bar_shock([100])['baseline_quality'] == 'UNSEEDED')
ck("short baseline → PARTIAL", bs.bar_shock([20, 30, 25, 15, 800])['baseline_quality'] == 'PARTIAL')
long_series = [20, 30, 25, 15, 30, 22, 28, 19, 26, 900]
ck("well-filled baseline → ESTABLISHED", bs.bar_shock(long_series)['baseline_quality'] == 'ESTABLISHED')

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
