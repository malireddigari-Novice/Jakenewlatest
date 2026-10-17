"""End-to-end check of the campaign-flow pipeline on SYNTHETIC 5-second polls (test data, not market history):
snapshot windows → value gate → clusters → proposal → simulated fill → opposite cluster → rotation exit →
full close → separate opposite entry; plus restart/replay determinism and duplicate-free orders/cards."""
import os
import sys
import tempfile
from datetime import datetime

import pytz

os.environ['CF_MODE'] = 'SHADOW'
from campaign_flow import settings as S
from campaign_flow.executor import SimBroker
from campaign_flow.journal import Journal
from campaign_flow.model import contract, series_key
from campaign_flow.pipeline import Pipeline

NY = pytz.timezone('America/New_York')
T0 = NY.localize(datetime(2026, 10, 19, 10, 0)).timestamp()
EXP = '2026-10-23'
FAILS = []
STRIKES = {'C': (345.0, 347.5), 'P': (340.0, 342.5)}


def check(cond, msg):
    print(f"  {'ok ' if cond else 'FAIL'} {msg}")
    if not cond:
        FAILS.append(msg)


def build_stream():
    """Observation stream: reference data, then polls 10:00-10:14 every 5 s."""
    obs = [{'kind': 'listing', 'ts': T0 - 600, 'ticker': 'AAPL', 'expiry': EXP,
            'C': list(STRIKES['C']), 'P': list(STRIKES['P'])}]
    refs, base = [], []
    for right, ks in STRIKES.items():
        for k in ks:
            key = list(series_key(contract('AAPL', right, k, EXP)))
            refs.append((key, [{'series': key, 'ts': T0 - 86400 + i * 60, 'price': 5.0, 'basis': 'TRADE'}
                               for i in range(30)]))
            base.append((key, 'MID', 10.0))
    obs += [{'kind': 'value_refs', 'ts': T0 - 590, 'refs': refs}, {'kind': 'baseline', 'ts': T0 - 590, 'rows': base}]
    cum = {(r, k): 1000 for r, ks in STRIKES.items() for k in ks}
    mid = {(r, k): 2.0 for r, ks in STRIKES.items() for k in ks}
    last_trade = {key: T0 - 300 for key in cum}
    spot = 346.0
    burst = {1: 'C', 2: 'C', 8: 'P', 9: 'P'}             # minute → which side gets a concentrated burst
    for i in range(0, 15 * 12):
        ts = T0 + i * 5
        minute, pos = divmod(i, 12)
        side = burst.get(minute)
        spot += 0.05 if minute < 6 else -0.05
        contracts = {}
        for (r, k) in cum:
            if side == r and pos < 3:
                cum[(r, k)] += (100, 40, 20)[pos]
                mid[(r, k)] += 0.05
                last_trade[(r, k)] = ts - 1
            bid, ask = round(mid[(r, k)] - 0.05, 2), round(mid[(r, k)] + 0.05, 2)
            occ = contract('AAPL', r, k, EXP)['occ']
            contracts[occ] = {'right': r, 'strike': k, 'expiry': EXP, 'bid': bid, 'ask': ask, 'bid_size': 20,
                              'ask_size': 20, 'quote_ts': ts - 2, 'cum_volume': cum[(r, k)], 'trade_px': ask,
                              'trade_ts': last_trade[(r, k)], 'trade_size': 20, 'trade_cond': 'I', 'iv': 0.3}
        obs.append({'kind': 'poll', 'ts': ts, 'ticker': 'AAPL', 'spot': round(spot, 2), 'expiries': [EXP],
                    'feed': 'opra', 'contracts': contracts, 'legacy': {'route_score': 0.45, 'attention_score': 70}})
    return obs


def run(obs, path):
    j = Journal(path)
    p = Pipeline(j, SimBroker())
    for ob in obs:
        p.feed(ob)
    return j


obs = build_stream()
path = tempfile.mktemp(suffix='.db')
j = run(obs, path)
camps = j.campaigns()
calls = [c for c in camps if c['direction'] == 'BULLISH']
puts = [c for c in camps if c['direction'] == 'BEARISH']
print('── pipeline ──')
check(len(j.logs('WINDOW')) > 0 and any(w['qual']['accepted'] for w in j.logs('WINDOW')),
      'snapshot adapter builds accepted windows (near-ask proxy, bins, lower-bound prints)')
check(len(calls) == 1 and calls[0]['source_campaign_id'] is None, 'call pair cluster + rising spot → one call campaign')
c = calls[0]
check(c['state'] == 'CLOSED' and c['entry_filled_qty'] == c['planned_qty'] and c['exit_filled_qty'] == c['planned_qty'],
      f"call campaign filled (SIM) then fully exited → CLOSED (realized {c['realized']})")
check(c['exit_pending']['primary'] == 'CONFIRMED_OPPOSITE_CLUSTER_ROTATION',
      'exit was the confirmed opposite put cluster, not premium noise')
check(len(puts) == 1 and puts[0]['source_campaign_id'] == c['campaign_id'],
      'opposite entry is a separate campaign referencing the closed source')
check(puts[0]['proposal_ts'] > c['closed_ts'], 'opposite entry proposed only after the full exit was confirmed')
check(len(j.logs('CANDIDATE_WATCH')) >= 0 and all(x['decision'] == 'WATCH' for x in j.logs('CANDIDATE_WATCH')),
      'ordinary opposite proposal blocked while the call campaign was open (rotation path only)')
orders = j.orders()
check(len([o for o in orders if o['campaign_id'] == c['campaign_id'] and o['kind'] == 'ENTRY']) == 1,
      'exactly one entry order for the campaign despite many polls')
labels = [x['label'] for x in j.cards(c['campaign_id'])]
check(labels == ['ENTRY_PROPOSED', 'ENTRY_FILLED', 'EXIT_PROPOSED', 'EXIT_FILLED'], f'card sequence {labels}')
check(not any(x['published'] for x in j.cards()), 'SHADOW/SIM cards are journaled, never published')
check(len(j.marks()) >= 5, 'shadow marks scheduled for proposals')
check(any(b for b in j.logs('BOARD')), 'board (raw + discounted) journaled')

print('── replay determinism / restart ──')
path2 = tempfile.mktemp(suffix='.db')
j2 = run(obs, path2)
sig = lambda jj: [(x['campaign_id'], x['state'], x['realized'], x['entry_filled_qty']) for x in jj.campaigns()]
check(sig(j) == sig(j2), 'replaying the recorded observations reproduces the same campaigns')
path3 = tempfile.mktemp(suffix='.db')
half = len(obs) // 2 + 40
j3 = run(obs[:half], path3)
j3.close()
j3 = Journal(path3)
p3 = Pipeline(j3, SimBroker())
p3.rebuilding = True                                   # restart: replay the recorded session log first
for ob in obs[:half]:
    p3.feed(ob)
p3.rebuilding = False
for ob in obs[half - 30:]:                             # the feed re-delivers 30 polls already processed
    p3.feed(ob)
check(len(j3.logs('POLL_REJECTED')) == 30, 're-delivered polls are rejected as duplicates')
check([(x['campaign_id'], x['state']) for x in j3.campaigns()] == [(x['campaign_id'], x['state']) for x in j.campaigns()],
      'restart mid-session (with re-delivered polls) ends in the same campaign states')
check(len(j3.orders()) == len(j.orders()) and len(j3.cards()) == len(j.cards()),
      'no duplicate orders or cards after the restart')

print('── executor: partial fills, TTL cancel, duplicate-free ──')
from campaign_flow import executor
from campaign_flow.policy import Router


class ScriptedBroker:
    """Broker double: first status = 2 of 3 filled at 2.10, then (after a cancel) CANCELED with 2 filled."""
    source = 'ALPACA_PAPER'

    def __init__(self):
        self.submitted, self.cancels = [], 0

    def submit(self, o, pipe):
        self.submitted.append(o['client_order_id'])
        return {'broker_order_id': 'b-' + o['client_order_id'], 'status': 'SUBMITTED'}

    def status(self, o, pipe, ts):
        if o['kind'] == 'EXIT':
            return {'status': 'FILLED', 'filled_qty': o['qty'], 'avg_price': 2.5}
        if o['status'] == 'CANCEL_REQUESTED':
            return {'status': 'CANCELED', 'filled_qty': 2, 'avg_price': 2.10}
        return {'status': 'PARTIAL', 'filled_qty': 2, 'avg_price': 2.10}

    def cancel(self, o):
        self.cancels += 1
        return True


jx = Journal(tempfile.mktemp(suffix='.db'))
px = Pipeline(jx, ScriptedBroker())
px._roll(T0)
R = Router(jx)
con = contract('AAPL', 'C', 345.0, EXP)
ts0 = T0 + 600
jx.put_campaign({'campaign_id': 'cx1', 'ticker': 'AAPL', 'direction': 'BULLISH', 'right': 'C', 'contract': con,
                 'horizon': 'INTRADAY', 'planned_end': ts0 + 18000, 'risk_plan': {}, 'state': 'PROPOSED',
                 'session': '2026-10-19', 'proposal_ts': ts0, 'proposal_event': 'x', 'proposal_ask': 2.10,
                 'proposal_quote': {}, 'planned_qty': 3, 'outstanding_entry_qty': 3, 'held_qty': 0,
                 'entry_filled_qty': 0, 'entry_cost': 0.0, 'avg_entry': None, 'first_entry_ts': None,
                 'exit_filled_qty': 0, 'realized': 0.0, 'exit_pending': None, 'source_campaign_id': None,
                 'marks': {}, 'cluster_ids': []})
for k in range(4):                                   # four syncs inside the TTL: one order, one fill event
    for f in executor.sync(px, ts0 + 1 + k):
        (R.entry_fill if f['kind'] == 'ENTRY' else R.cancel_confirmed)(f)
c = jx.campaign('cx1')
check(len(px.broker.submitted) == 1 and c['held_qty'] == 2 and c['outstanding_entry_qty'] == 1 and c['state'] == 'ACTIVE',
      'partial entry fill (2 of 3) applied once across repeated syncs; remainder outstanding')
for k in (S.ENTRY_ORDER_TTL_S + 5, S.ENTRY_ORDER_TTL_S + 10):
    for f in executor.sync(px, ts0 + k):
        (R.entry_fill if f['kind'] == 'ENTRY' else R.cancel_confirmed)(f)
c = jx.campaign('cx1')
check(px.broker.cancels == 1 and c['outstanding_entry_qty'] == 0 and c['state'] == 'ACTIVE' and c['held_qty'] == 2,
      'unfilled remainder cancelled after the TTL; reservation released; held contracts still managed')
px2 = Pipeline(jx, px.broker)                        # restart with the same journal
for k in range(3):
    executor.sync(px2, ts0 + 200 + k)
check(len(px.broker.submitted) == 1, 'no duplicate entry order after a restart')


print()
print(f"{len(FAILS)} failure(s)" if FAILS else "PIPELINE CHECKS PASSED")
sys.exit(1 if FAILS else 0)
