"""Held contracts keep a live quote after the stock moves away from the strike (SYNTHETIC TEST DATA).

The 2026-11-05 case: TSLA 365C (exp 11-06) bought at 10:12 ET with TSLA ~349. After 11:42 TSLA fell into the 340s,
the 365 strike left the engine's spot band, campaign-flow had no quote, and no exit could fire — the 15:30
deadline exit waited for an executable quote until shutdown and the position was carried overnight by accident.

Checks:
  engine._fetch_held   fetches only held contracts the poll missed, and only the held right
  runner.add_held      merges them into the poll as held_only (never overwriting a polled contract)
  runner.held_contracts lists ACTIVE / ENTRY_PENDING / PROPOSED campaigns of the ticker
  pipeline             a held_only quote lets the pending deadline exit go out (same day and next morning);
                       held_only contracts never build windows, coverage, or entry choices

Run: python test_held_quotes.py
"""
import os
import tempfile
import types
from datetime import date, datetime

import pytz

os.environ['CF_MODE'] = 'SHADOW'
from campaign_flow import settings as S                 # noqa: E402
from campaign_flow.executor import SimBroker            # noqa: E402
from campaign_flow.journal import Journal               # noqa: E402
from campaign_flow.model import contract                # noqa: E402
from campaign_flow.pipeline import Pipeline             # noqa: E402
from campaign_flow.runner import Runner, add_held       # noqa: E402
import engine                                           # noqa: E402

NY = pytz.timezone('America/New_York')
FAILS = []
CON = contract('TSLA', 'C', 365.0, '2026-11-06')


def check(cond, msg):
    print(f"  {'ok ' if cond else 'FAIL'} {msg}")
    if not cond:
        FAILS.append(msg)


def ny(d, hh, mm, ss=0):
    return NY.localize(datetime(d.year, d.month, d.day, hh, mm, ss)).timestamp()


def iso(ts):
    return datetime.fromtimestamp(ts, pytz.utc).isoformat().replace('+00:00', 'Z')


print('── engine._fetch_held ──')
calls = []


class Data:
    def get_option_contract_snapshots(self, sym, exp, strikes):
        calls.append((sym, exp, sorted(strikes)))
        return {(k, s): {'bid': 0.40, 'ask': 0.45, 'bid_size': 30, 'quote_ts': '2026-11-05T20:30:04Z'}
                for k in strikes for s in ('CALL', 'PUT')}


fake = types.SimpleNamespace(data=Data())
band = {(345.0, 'CALL'): {}, (350.0, 'CALL'): {}}
held = [('2026-11-06', 365.0, 'CALL'), ('2026-11-06', 350.0, 'CALL')]
got = engine.AttentionEngine._fetch_held(fake, 'TSLA', held, date(2026, 11, 6), band, None)
check(calls == [('TSLA', '2026-11-06', [365.0])], f'only the strike outside the band is fetched ({calls})')
check(list(got) == [('2026-11-06', 365.0, 'CALL')], 'only the held right is returned (not the 365P)')
calls.clear()
got = engine.AttentionEngine._fetch_held(fake, 'TSLA', held, date(2026, 11, 5), {}, (date(2026, 11, 6), band))
check(calls == [('TSLA', '2026-11-06', [365.0])], "the next-expiration poll counts as covered too")
calls.clear()
check(engine.AttentionEngine._fetch_held(fake, 'TSLA', [], date(2026, 11, 6), band, None) == {} and calls == [],
      'nothing held: no extra request')


class Boom:
    def get_option_contract_snapshots(self, *a):
        raise ConnectionError('reset')


check(engine.AttentionEngine._fetch_held(types.SimpleNamespace(data=Boom()), 'TSLA', held[:1],
                                          date(2026, 11, 6), {}, None) == {},
      'a failed held-quote request is logged and skipped, never fatal to the poll')

print('── runner.add_held / held_contracts ──')
contracts = {contract('TSLA', 'C', 350.0, '2026-11-06')['occ']: {'strike': 350.0, 'bid': 1.0}}
add_held('TSLA', {('2026-11-06', 365.0, 'CALL'): {'bid': 0.4, 'ask': 0.45, 'bid_size': 30,
                                                   'quote_ts': '2026-11-05T20:30:04Z', 'volume': 900},
                  ('2026-11-06', 350.0, 'CALL'): {'bid': 9.9}}, contracts)
h = contracts.get(CON['occ']) or {}
check(h.get('held_only') is True and h['bid'] == 0.4 and h['quote_ts'] == datetime(2026, 11, 5, 20, 30, 4,
      tzinfo=pytz.utc).timestamp(), 'held contract merged as held_only with its quote time as epoch')
check(contracts[contract('TSLA', 'C', 350.0, '2026-11-06')['occ']] == {'strike': 350.0, 'bid': 1.0},
      'a contract already in the poll is not overwritten')

j = Journal(tempfile.mktemp(suffix='.db'))
base = {'ticker': 'TSLA', 'direction': 'BULLISH', 'session': '2026-11-05', 'contract': CON}
j.put_campaign({**base, 'campaign_id': 'a', 'state': 'ACTIVE', 'held_qty': 2, 'outstanding_entry_qty': 0})
j.put_campaign({**base, 'campaign_id': 'b', 'state': 'CLOSED', 'held_qty': 0, 'outstanding_entry_qty': 0,
                'contract': contract('TSLA', 'P', 340.0, '2026-11-06')})
j.put_campaign({**base, 'campaign_id': 'c', 'state': 'ACTIVE', 'held_qty': 1, 'outstanding_entry_qty': 0,
                'ticker': 'NVDA', 'contract': contract('NVDA', 'C', 205.0, '2026-11-06')})
check(Runner.held_contracts(types.SimpleNamespace(j=j), 'TSLA') == [('2026-11-06', 365.0, 'CALL')],
      'held_contracts: the open TSLA campaign only (closed and other tickers excluded)')

print('── pipeline: the pending deadline exit goes out once a quote arrives ──')


def stuck_campaign(j):
    """The live 11-05 state: ACTIVE, 2 held at 1.84, 15:30 deadline exit pending, no quote since 11:42."""
    entry = ny(date(2026, 11, 5), 10, 12)
    j.put_campaign({'campaign_id': '99bb', 'ticker': 'TSLA', 'direction': 'BULLISH', 'session': '2026-11-05',
                    'state': 'ACTIVE', 'horizon': 'INTRADAY', 'contract': CON, 'planned_qty': 2,
                    'outstanding_entry_qty': 0, 'held_qty': 2, 'entry_filled_qty': 2, 'entry_cost': 3.68,
                    'avg_entry': 1.84, 'first_entry_ts': entry, 'exit_filled_qty': 0, 'realized': 0.0,
                    'proposal_ts': entry - 1, 'proposal_ask': 1.92, 'reservation': 384,
                    'planned_end': ny(date(2026, 11, 5), 15, 30),
                    'exit_pending': {'reasons': ['PLANNED_OR_EXPIRY_EXIT_DEADLINE'],
                                     'primary': 'PLANNED_OR_EXPIRY_EXIT_DEADLINE',
                                     'requested_ts': ny(date(2026, 11, 5), 15, 30, 5), 'event_id': 'x',
                                     'rotation_direction': None}})


def poll(ts, contracts, spot=343.0):
    return {'kind': 'poll', 'ts': ts, 'ticker': 'TSLA', 'spot': spot, 'expiries': ['2026-11-06'], 'feed': 'opra',
            'contracts': contracts, 'legacy': {}}


def held_row(ts, bid=0.40):
    c = {}
    add_held('TSLA', {('2026-11-06', 365.0, 'CALL'): {'bid': bid, 'ask': bid + 0.05, 'bid_size': 30,
                                                       'quote_ts': iso(ts - 1), 'volume': 900}}, c)
    return c


in_band = {contract('TSLA', 'C', 345.0, '2026-11-06')['occ']: {
    'right': 'C', 'strike': 345.0, 'expiry': '2026-11-06', 'bid': 3.0, 'ask': 3.1, 'bid_size': 20, 'ask_size': 20,
    'quote_ts': None, 'cum_volume': 100}}


def exit_orders(j):
    return [o for o in j.orders('99bb') if o['kind'] == 'EXIT']


# before the fix: the poll carries only in-band strikes → the exit can never be submitted
j = Journal(tempfile.mktemp(suffix='.db'))
P = Pipeline(j, SimBroker())
stuck_campaign(j)
t = ny(date(2026, 11, 5), 15, 40)
P.feed(poll(t, dict(in_band)))
check(exit_orders(j) == [] and any(r.get('campaign_id') == '99bb' for r in j.logs('EXIT_PENDING_EXECUTABLE_QUOTE')),
      'control (no held quote, as live on 11-05): exit stays EXIT_PENDING_EXECUTABLE_QUOTE')

# with the fix, same afternoon
P.feed(poll(t + 10, {**in_band, **held_row(t + 10)}))
xo = exit_orders(j)
check(len(xo) == 1 and xo[0]['qty'] == 2 and xo[0]['limit_price'] == 0.40,
      'held quote present: one sell order for both contracts at the live bid ($0.40)')

# the real case for 11-06: a fresh process the next morning, the 11-05 campaign still ACTIVE
j = Journal(tempfile.mktemp(suffix='.db'))
P = Pipeline(j, SimBroker())
stuck_campaign(j)
t = ny(date(2026, 11, 6), 9, 31)
P.feed(poll(t, {**in_band, **held_row(t, bid=0.15)}))
xo = exit_orders(j)
c = j.campaign('99bb')
check(not j.logs('RECONCILIATION_EXCEPTION') and len(xo) == 1 and xo[0]['limit_price'] == 0.15
      and c['state'] == 'CLOSED' and c['held_qty'] == 0 and c['realized'] == round((0.15 - 1.84) * 100 * 2, 2),
      f"next open: not reconciled away; exits both at the live $0.15 bid (realized {c['realized']})")
check(not [w for w in j.logs('WINDOW') if (w.get('contract') or {}).get('strike') == 365.0],
      'the held_only contract builds no flow windows')
snap = P._snapshot['TSLA']
check(365.0 not in [k for k in (snap['coverage'].get('rights') or {})] and
      P._choices('TSLA', [{'expiry': '2026-11-06', 'strikes': [365.0]}], 'C') == [],
      'held_only contracts are never offered as entry choices')

print()
if FAILS:
    print(f"{len(FAILS)} HELD-QUOTE CHECK(S) FAILED")
    raise SystemExit(1)
print('ALL HELD-QUOTE CHECKS PASSED (synthetic test data)')
