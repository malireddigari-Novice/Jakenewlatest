"""Fresh-premium + control layer test. Run: python test_premium.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analysis import premium as pm

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

# ── relevance_to_spot: ATM=1, far-OTM decays to 0 ──
ck("ATM relevance = 1.0", pm.relevance_to_spot(100.0, 100.0) == 1.0)
ck("3% away relevance = 0.0", pm.relevance_to_spot(100.0, 103.0, band_pct=0.03) == 0.0)
ck("no spot -> neutral 1.0", pm.relevance_to_spot(None, 100.0) == 1.0)

# ── directional_premium: notional × relevance; zero on no volume ──
ck("no delta_vol -> 0 premium", pm.directional_premium(delta_vol=0, mark=1.0, spot=100, strike=100) == 0.0)
p = pm.directional_premium(delta_vol=100, mark=1.0, spot=100, strike=100)
ck("100 contracts @ $1 ATM -> $10,000 notional", p == 100 * 1.0 * 100 * 1.0)

# ── symbol_attention_input: call control when calls carry more fresh premium ──
contracts = [
    {'strike': 100, 'side': 'CALL', 'delta_vol': 500, 'mark': 1.20, 'day_low': 1.0, 'day_high': 2.0},
    {'strike': 100, 'side': 'PUT',  'delta_vol': 100, 'mark': 1.00, 'day_low': 0.8, 'day_high': 1.5},
]
ai = pm.symbol_attention_input(contracts, spot=100.0, band_pct=0.03)
ck("call control detected", ai['control_side'] == 'CALL')
ck("control share > 0.5", ai['control_share'] > 0.5)
ck("premium is positive int", isinstance(ai['premium'], int) and ai['premium'] > 0)
ck("low_score present from control-side range", ai['low_score'] is not None and 0 <= ai['low_score'] <= 1)

# ── put control when puts dominate ──
contracts2 = [
    {'strike': 100, 'side': 'CALL', 'delta_vol': 50,  'mark': 1.00, 'day_low': 1.0, 'day_high': 2.0},
    {'strike': 100, 'side': 'PUT',  'delta_vol': 800, 'mark': 1.50, 'day_low': 0.8, 'day_high': 1.6},
]
ai2 = pm.symbol_attention_input(contracts2, spot=100.0)
ck("put control detected", ai2['control_side'] == 'PUT')

# ── no fresh volume -> None (nothing to allocate) ──
ck("all-zero deltas -> None", pm.symbol_attention_input(
    [{'strike': 100, 'side': 'CALL', 'delta_vol': 0, 'mark': 1.0, 'day_low': 1, 'day_high': 2}], 100.0) is None)

# ── room_from_low: on the low = 1.0, at the high = 0.0 ──
ck("mark on day low -> room 1.0", pm._room_from_low(1.0, 1.0, 2.0) == 1.0)
ck("mark at day high -> room 0.0", pm._room_from_low(2.0, 1.0, 2.0) == 0.0)
ck("unknown range -> None", pm._room_from_low(1.5, None, None) is None)

# ── PremiumTracker: first sighting = baseline (delta 0), then real deltas ──
tr = pm.PremiumTracker()
snap = {(100.0, 'CALL'): {'volume': 1000, 'mark': 1.2, 'day_low': 1.0, 'day_high': 2.0}}
first = tr.contracts_with_deltas('AAPL', snap)
ck("first sighting -> delta 0 (no opening-flush spike)", first[0]['delta_vol'] == 0)
snap2 = {(100.0, 'CALL'): {'volume': 1350, 'mark': 1.3, 'day_low': 1.0, 'day_high': 2.0}}
second = tr.contracts_with_deltas('AAPL', snap2)
ck("second poll -> delta = 350 fresh contracts", second[0]['delta_vol'] == 350)
snap3 = {(100.0, 'CALL'): {'volume': 200, 'mark': 1.3, 'day_low': 1.0, 'day_high': 2.0}}  # session reset
third = tr.contracts_with_deltas('AAPL', snap3)
ck("cumulative drop (reset) -> delta 0, not negative", third[0]['delta_vol'] == 0)

# ── full pipeline: two Mag7 names, AAPL should out-premium NVDA ──
tr2 = pm.PremiumTracker()
tr2.contracts_with_deltas('AAPL', {(100.0, 'CALL'): {'volume': 0, 'mark': 2.0, 'day_low': 1, 'day_high': 3}})
tr2.contracts_with_deltas('NVDA', {(100.0, 'PUT'):  {'volume': 0, 'mark': 2.0, 'day_low': 1, 'day_high': 3}})
a = pm.symbol_attention_input(
    tr2.contracts_with_deltas('AAPL', {(100.0, 'CALL'): {'volume': 5000, 'mark': 2.0, 'day_low': 1, 'day_high': 3}}), 100.0)
n = pm.symbol_attention_input(
    tr2.contracts_with_deltas('NVDA', {(100.0, 'PUT'):  {'volume': 500,  'mark': 2.0, 'day_low': 1, 'day_high': 3}}), 100.0)
ck("AAPL fresh premium > NVDA fresh premium", a['premium'] > n['premium'])

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
