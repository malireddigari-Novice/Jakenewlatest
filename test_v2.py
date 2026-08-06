"""v2 four-layer tests. Run: python test_v2.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from analysis import attention as at
from analysis import control as ctrl
from analysis import events as ev
from analysis.flow import FlowTracker
import execution

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

def C(strike, side, vol, mark, bid=None, ask=None, bs=20, asz=20, low=1.0, high=3.0, ts=None):
    return {'volume': vol, 'mark': mark, 'bid': bid if bid is not None else mark - 0.05,
            'ask': ask if ask is not None else mark + 0.05, 'bid_size': bs, 'ask_size': asz,
            'quote_ts': ts, 'day_low': low, 'day_high': high, 'delta': 0.5, 'gamma': 0.1}

# ══ FLOW: rolling windows + opening capture + shock ══════════════════════════════
print("── flow ──")
ft = FlowTracker(); ft.new_session('2026-07-27')
# Pre-open seed at t=1000 (RTH cum ~0), then the OPEN burst at t=1030 (cum 500).
ft.ingest('AAPL', {(100.0, 'CALL'): C(100, 'CALL', 0, 2.0)}, 100.0, 1000.0)
ft.ingest('AAPL', {(100.0, 'CALL'): C(100, 'CALL', 500, 2.0)}, 100.0, 1030.0)
sf = ft.symbol_flow('AAPL', 1030.0)
ck("opening burst captured as fresh (not discarded)", sf['fresh_vol_window'] == 500)
ck("fresh premium = 500 x $2 x 100 = $100k", abs(sf['fresh_prem_window'] - 100_000) < 1)
ck("call side carries the premium", sf['call_prem'] > 0 and sf['put_prem'] == 0)
ck("positive velocity as flow arrives", sf['velocity'] > 0)
z1 = ft.update_shock('AAPL', sf['fresh_prem_poll'])
ck("first shock reading is 0 (baseline seeded)", z1 == 0.0)
ft.mark_poll('AAPL', 1030.0)
# A later, far bigger poll → positive shock vs the ticker's own baseline.
ft.ingest('AAPL', {(100.0, 'CALL'): C(100, 'CALL', 8000, 2.0)}, 100.0, 1060.0)
sf2 = ft.symbol_flow('AAPL', 1060.0)
z2 = ft.update_shock('AAPL', sf2['fresh_prem_poll'])
ck("abnormal surge → positive attention shock", z2 > 0)

# ══ CONTROL: five states, awakening, quote bias ═════════════════════════════════
print("── control ──")
ctr = ctrl.ControlTracker(); ctr.new_session()
s = ctr.evaluate('AAPL', 900_000, 80_000)
ck("dominant calls, quiet puts → CALL_CONTROL", s['state'] == 'CALL_CONTROL' and s['dominant_side'] == 'CALL')
sb = ctr.evaluate('MSFT', 100_000, 95_000)
ck("near 50/50 → BALANCED_CONTEST", sb['state'] == 'BALANCED_CONTEST')
ctr.evaluate('NVDA', 190_000, 10_000)                       # seed prev
sa = ctr.evaluate('NVDA', 200_000, 90_000)                  # calls lead but puts surged
ck("calls lead while puts surge → CALL_CONTROL_PUTS_AWAKENING",
   sa['state'] == 'CALL_CONTROL_PUTS_AWAKENING' and sa['awakening'])
ck("quote_bias near ask = buying (+)", ctrl.quote_bias(1.98, 1.90, 2.00) > 0)
ck("quote_bias near bid = selling (-)", ctrl.quote_bias(1.91, 1.90, 2.00) < 0)

# ══ EVENTS: metrics, classification, activation, migration, selection, freshness ══
print("── events ──")
single = [{'strike': 100, 'fresh_prem': 800_000, 'fresh_vol': 4000},
          {'strike': 101, 'fresh_prem': 100_000, 'fresh_vol': 500},
          {'strike': 99,  'fresh_prem': 100_000, 'fresh_vol': 500}]
m = ev.event_metrics(single)
ck("dominant single strike → high top-share, not distributed",
   m['top_strike_share'] >= 0.6 and not m['distributed_background'])
ck("classify SINGLE_STRIKE", ev.classify_event(m) == 'SINGLE_STRIKE')
scattered = [{'strike': k, 'fresh_prem': 100_000, 'fresh_vol': 500} for k in (90, 95, 100, 105, 110)]
ms = ev.event_metrics(scattered)
ck("scattered prints → distributed background", ms['distributed_background'])
ck("classify DISTRIBUTED", ev.classify_event(ms) == 'DISTRIBUTED')

# Moving convexity front: call one strike OTM, spot rising toward it, volume accelerating.
act = ev.strike_activation('CALL', strike=101, spot=100.0, spot_prev=99.5, vol_accel=500)
ck("OTM call, spot approaching → OTM_TO_ATM transition", act['transition'] == 'OTM_TO_ATM')
ck("activation positive with approach + accel", act['activation'] > 0 and act['ramp'])
mt = ev.MigrationTracker(); mt.new_session()
mt.update('AAPL', 'CALL', 100, 100.0)
mg = mt.update('AAPL', 'CALL', 101, 100.6)                  # top strike + spot both stepped up
ck("ordered strike migration up detected", mg['migrating'] and mg['direction'] == 'UP')

sel = ev.select_contract('CALL', [
    dict(strike=100, side='CALL', fresh_prem=50_000, **C(100, 'CALL', 0, 2.0)),
    dict(strike=101, side='CALL', fresh_prem=300_000, **C(101, 'CALL', 0, 1.4)),  # most participation
], spot=100.3)
ck("select_contract picks the highest-participation ATM±1 strike", sel['strike'] == 101)
ck("MISSED freshness blocks entry", ev.entry_freshness(1.0, 1.8)['label'] == 'MISSED'
   and not ev.entry_freshness(1.0, 1.8)['tradeable'])
ck("EARLY freshness is tradeable", ev.entry_freshness(1.0, 1.05)['label'] == 'EARLY')

# ══ ATTENTION v2: hard gates + blended board + asymmetric exits ═══════════════════
print("── attention v2 ──")
def base_row(**kw):
    r = {'fresh_prem': 200_000, 'fresh_vol': 2000, 'shock': 2.0, 'velocity': 1000,
         'acceleration': 100, 'control_side': 'CALL', 'control_state': 'CALL_CONTROL',
         'control_share': 0.8, 'control_strength': 0.8, 'event_quality': 0.7,
         'best_contract': {'fresh_prem': 60_000}, 'spread_pct': 0.05, 'quote_size': 20,
         'quote_stale_s': 1.0, 'dist_from_low': 1.2, 'top_strike_share': 0.7}
    r.update(kw); return r
ck("clean row is eligible (no gate fails)", at.hard_gates(base_row()) == [])
ck("thin premium → SYMBOL_PREMIUM_LOW", 'SYMBOL_PREMIUM_LOW' in at.hard_gates(base_row(fresh_prem=1000)))
ck("wide spread → SPREAD_WIDE", 'SPREAD_WIDE' in at.hard_gates(base_row(spread_pct=0.5)))
ck("balanced control → CONTROL_CONTESTED",
   'CONTROL_CONTESTED' in at.hard_gates(base_row(control_state='BALANCED_CONTEST')))
ck("chased contract → CONTRACT_CHASED", 'CONTRACT_CHASED' in at.hard_gates(base_row(dist_from_low=3.0)))

# Self-normalisation: a CHEAPER but far more abnormal/participatory AAPL beats an expensive META.
board = at.build_board({
    'AAPL': base_row(fresh_prem=400_000, fresh_vol=4000, shock=5.0, control_strength=0.9, event_quality=0.8),
    'META': base_row(fresh_prem=700_000, fresh_vol=1000, shock=0.5, control_strength=0.7, event_quality=0.5),
}, score_min=50)
ba = board['by_symbol']
ck("cheaper-but-abnormal AAPL outranks expensive META (self-normalised)",
   board['leader'] == 'AAPL' and ba['AAPL']['attention_score'] > ba['META']['attention_score'])
# Ineligibility keeps a name out of leadership regardless of raw size.
board2 = at.build_board({
    'AAPL': base_row(fresh_prem=400_000, shock=5.0),
    'NVDA': base_row(fresh_prem=2_000_000, shock=9.0, spread_pct=0.9),   # huge but untradeable spread
}, score_min=50)
ck("huge-but-ineligible NVDA is not the leader", board2['leader'] == 'AAPL'
   and not board2['by_symbol']['NVDA']['eligible'])

# Asymmetric exits.
em = at.PositionExitMonitor()
ovb = at.build_board({'AAPL': base_row(control_side='PUT', control_share=0.85, shock=4.0, velocity=5000)}, score_min=50)
e = em.evaluate(ovb, 'AAPL', 'CALL', pnl=0.1)
ck("overwhelming opposite control → IMMEDIATE exit", e['exit'] and e['mode'] == 'IMMEDIATE')
em2 = at.PositionExitMonitor()
modb = at.build_board({'AAPL': base_row(control_side='PUT', control_share=0.62, shock=1.0, velocity=-10)}, score_min=50)
r1 = em2.evaluate(modb, 'AAPL', 'CALL', pnl=0.1)
r2 = em2.evaluate(modb, 'AAPL', 'CALL', pnl=0.1)
ck("moderate control loss → FAST exit after 2 polls, not 1", (not r1['exit']) and r2['exit'] and r2['mode'] == 'FAST')
# Rank loss alone must NOT exit a still-controlled, profitable position.
em3 = at.PositionExitMonitor()
stillb = at.build_board({
    'NVDA': base_row(fresh_prem=5_000_000, shock=9.0),
    'AAPL': base_row(fresh_prem=300_000, shock=1.0, control_side='CALL', control_strength=0.8, control_share=0.8),
}, score_min=50)
held = all(not em3.evaluate(stillb, 'AAPL', 'CALL', pnl=0.3)['exit'] for _ in range(5))
ck("rank drop alone does NOT exit a still-controlled winner", held)

# ══ EXECUTION guards ═════════════════════════════════════════════════════════════
print("── execution ──")
good = {'bid': 1.95, 'ask': 2.05, 'mark': 2.0, 'bid_size': 20, 'ask_size': 20, 'quote_ts': None}
ck("wide spread blocked", not execution.check_executable({**good, 'ask': 2.6}, __import__('datetime').datetime.now())[0])
ck("thin book blocked", not execution.check_executable({**good, 'bid_size': 1}, __import__('datetime').datetime.now())[0])
lp = execution.limit_price(good)
ck("limit price = mid+offset, capped at ask", good['bid'] <= lp <= good['ask'])
ck("slippage guard trips on a big move", not execution.slippage_ok(2.0, 2.5))
ck("slippage guard passes on a small move", execution.slippage_ok(2.0, 2.02))

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
