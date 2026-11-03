"""PAPER-mode end-to-end check on SYNTHETIC TEST DATA (not market history, nothing leaves this machine):

    observation → proposal → AlpacaPaperBroker order → recorded fill/campaign → Discord outbox → delivered card

The production path is exercised unchanged: campaign_flow.Runner (PAPER mode, observation log + restart
rebuild), Pipeline, Router, executor.sync, AlpacaPaperBroker, cards.render, notify.enqueue/flush. Only the two
external endpoints are doubles: an Alpaca-paper REST double (rejects a reused client_order_id like Alpaca does)
and a local HTTP webhook that answers like Discord's `?wait=true` (returns a message id).

Also checked: a process restart mid-session (memory rebuilt from the session log, journal reopened), the feed
re-delivering already-processed polls, the broker reporting the same cumulative fill repeatedly, and the outbox
re-enqueueing an already-sent card — none may create a second order, fill or delivered card.
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
# These checks cover the base spec. The Mag 7 brief additions (conviction tiers, daily call/put cap,
# trailing stop, overnight carry) are pinned off here and covered by test_mag7_brief.py.
for _k, _v in (('CF_CONV_ENABLED', 'false'), ('CF_MAX_ENTRIES_PER_RIGHT_DAY', '0'),
               ('CF_TRAIL_ARM_GAIN', '0'), ('CF_OVERNIGHT_ENABLED', 'false')):
    os.environ.setdefault(_k, _v)

TMP = tempfile.mkdtemp(prefix='cf_e2e_')
_srv_hits = []


class _Hook(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        _srv_hits.append(body)
        out = json.dumps({'id': f"test-msg-{len(_srv_hits)}"}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


srv = HTTPServer(('127.0.0.1', 0), _Hook)
threading.Thread(target=srv.serve_forever, daemon=True).start()

# Environment BEFORE any project import (config/settings read it at import; load_dotenv never overrides).
os.environ.update({
    'CF_MODE': 'PAPER', 'CF_DISCORD_ENABLED': 'true', 'CF_RECORD_OBS': 'true',
    'CF_OBS_DIR': os.path.join(TMP, 'obs'), 'CF_JOURNAL_DB': os.path.join(TMP, 'cf.db'),
    'NOTIFY_OUTBOX_DB': os.path.join(TMP, 'outbox.db'),
    'DISCORD_WEBHOOK_URL': f"http://127.0.0.1:{srv.server_port}/test-webhook",
    'ALPACA_ENABLED': 'true', 'ALPACA_PAPER': 'true',
})

from datetime import datetime  # noqa: E402

import pytz  # noqa: E402

import notify  # noqa: E402
from campaign_flow import settings as S  # noqa: E402
from campaign_flow.model import contract, series_key  # noqa: E402
from campaign_flow.runner import Runner  # noqa: E402

FAILS = []
NY = pytz.timezone('America/New_York')
T0 = NY.localize(datetime(2026, 10, 19, 10, 0)).timestamp()
SESSION, EXP = '2026-10-19', '2026-10-23'
STRIKES = {'C': (345.0, 347.5), 'P': (340.0, 342.5)}


def check(cond, msg):
    print(f"  {'ok ' if cond else 'FAIL'} {msg}")
    if not cond:
        FAILS.append(msg)


class AlpacaPaperDouble:
    """Alpaca paper REST semantics the broker adapter relies on: a reused client_order_id is rejected (None,
    like a 422), lookups by client id, cancel; limit orders fill on the next status read."""

    def __init__(self):
        self.orders, self.submit_calls, self.rejected_reuse = {}, [], 0

    def submit_limit(self, occ, side, qty, limit_price, client_order_id):
        self.submit_calls.append(client_order_id)
        if client_order_id in self.orders:
            self.rejected_reuse += 1
            return None
        o = {'id': f"alp-{len(self.orders) + 1}", 'client_order_id': client_order_id, 'symbol': occ, 'side': side,
             'qty': str(qty), 'limit_price': f"{limit_price:.2f}", 'status': 'new', 'filled_qty': '0',
             'filled_avg_price': None, 'reads': 0}
        self.orders[client_order_id] = o
        return dict(o)

    def get_order_by_client_id(self, cid):
        o = self.orders.get(cid)
        if not o:
            return None
        o['reads'] += 1
        if o['status'] == 'new' and o['reads'] >= 2:          # accepted, then filled at the limit
            o.update(status='filled', filled_qty=o['qty'], filled_avg_price=o['limit_price'],
                     filled_at='2026-10-19T14:00:00Z')
        return dict(o)

    def cancel_order(self, oid):
        for o in self.orders.values():
            if o['id'] == oid and o['status'] not in ('filled', 'canceled'):
                o['status'] = 'canceled'
        return True


def build_stream():
    """SYNTHETIC TEST DATA: AAPL reference rows, then 5-second polls 10:00-10:14 with a concentrated call burst
    (minutes 1-2, rising spot) and a put burst (minutes 8-9, falling spot). Polls carry receipt-time stamps."""
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
    spot, burst = 346.0, {1: 'C', 2: 'C', 8: 'P', 9: 'P'}
    for i in range(0, 15 * 12):
        start = T0 + i * 5
        recv = start + 0.4                                   # data arrived 0.4 s after the cycle began
        minute, pos = divmod(i, 12)
        side = burst.get(minute)
        spot += 0.05 if minute < 6 else -0.05
        contracts = {}
        for (r, k) in cum:
            if side == r and pos < 3:
                cum[(r, k)] += (100, 40, 20)[pos]
                mid[(r, k)] += 0.05
                last_trade[(r, k)] = start - 1
            bid, ask = round(mid[(r, k)] - 0.05, 2), round(mid[(r, k)] + 0.05, 2)
            occ = contract('AAPL', r, k, EXP)['occ']
            contracts[occ] = {'right': r, 'strike': k, 'expiry': EXP, 'bid': bid, 'ask': ask, 'bid_size': 20,
                              'ask_size': 20, 'quote_ts': start + 0.2, 'cum_volume': cum[(r, k)], 'trade_px': ask,
                              'trade_ts': last_trade[(r, k)], 'trade_size': 20, 'trade_cond': 'I', 'iv': 0.3}
        obs.append({'kind': 'poll', 'ts': recv, 'ticker': 'AAPL', 'spot': round(spot, 2), 'expiries': [EXP],
                    'feed': 'opra', 'contracts': contracts, 'legacy': {'route_score': 0.45, 'attention_score': 70},
                    'timing': {'poll_start_ts': start, 'fetch_start_ts': start, 'recv_ts': recv, 'server_ts': None,
                               'basis': 'LOCAL_RECEIPT', 'test_data': 'SYNTHETIC'}})
    return obs


def outbox_rows():
    with notify._db() as con:
        return con.execute("SELECT signal_id, status, message_id, attempts FROM outbox").fetchall()


obs = build_stream()
alp = AlpacaPaperDouble()
print(f"── PAPER e2e on SYNTHETIC TEST DATA (tmp {TMP}) ──")
r1 = Runner(None, exec_client=alp)
check(r1.mode == 'PAPER' and r1.pipe.broker.source == 'ALPACA_PAPER',
      'runner is in PAPER mode with the Alpaca-paper broker adapter')
r1._start_session(SESSION)
half = len(obs) // 2 + 40
for ob in obs[:half]:
    r1.emit(ob)
mid_camps = r1.j.campaigns()
mid_cards = len(_srv_hits)
r1.j.close()
r1._fh.close()
r1._fh = None
print(f"  [restart after {half} observations: {len(mid_camps)} campaign(s), {mid_cards} card(s) delivered]")

r2 = Runner(None, exec_client=alp)                          # new process: same journal, log and broker account
r2._start_session(SESSION)                                  # rebuild memory from cf_obs/<session>.jsonl
for ob in obs[half - 30:]:                                  # the feed re-delivers 30 already-processed polls
    r2.emit(ob)
j = r2.j
camps = j.campaigns()
calls = [c for c in camps if c['direction'] == 'BULLISH']
puts = [c for c in camps if c['direction'] == 'BEARISH']

print('── proposal → paper execution → recorded campaign/fill ──')
check(len(calls) == 1 and calls[0]['state'] == 'CLOSED', 'call campaign proposed, filled and fully exited (CLOSED)')
check(len(puts) == 1 and puts[0]['source_campaign_id'] == calls[0]['campaign_id'],
      'opposite put campaign is a separate rotation entry referencing the closed call campaign')
ents = [c for c in alp.orders.values() if c['client_order_id'].endswith('-E')]
check(len(ents) == len(camps), f'one Alpaca-paper entry order per campaign ({len(ents)} for {len(camps)})')
check(alp.rejected_reuse == 0 and len(alp.submit_calls) == len(set(alp.submit_calls)),
      'no client_order_id was ever submitted twice (restart + re-delivered polls)')
fills = [f for f in j.fills() if f['accepted']]
check(fills and all(f['source'] == 'ALPACA_PAPER' for f in fills), 'fills recorded with source ALPACA_PAPER')
for c in camps:
    ef = [f for f in fills if f['campaign_id'] == c['campaign_id'] and f['kind'] == 'ENTRY']
    check(sum(f['qty'] for f in ef) == c['entry_filled_qty'] == c['planned_qty'],
          f"{c['direction']} entry fill recorded once ({c['entry_filled_qty']}/{c['planned_qty']} @ {c['avg_entry']})")
check(len(j.logs('POLL_REJECTED')) == 30, 're-delivered polls rejected as duplicates (30)')

print('── Discord outbox → delivered card ──')
cards = j.cards()
filled = [c for c in cards if c['label'].endswith('FILLED')]
check(filled and all(c['published'] == c['label'].endswith('FILLED') for c in cards),
      f'only FILLED cards published ({len(filled)} of {len(cards)}); proposals stay in the journal')
labels = [x['label'] for x in j.cards(calls[0]['campaign_id'])]
check(labels == ['ENTRY_PROPOSED', 'ENTRY_FILLED', 'EXIT_PROPOSED', 'EXIT_FILLED'], f'call card sequence {labels}')
ob_rows = outbox_rows()
check(len(ob_rows) == len(filled) and all(r[1] == 'SENT' and r[2] for r in ob_rows),
      f'outbox: {len(ob_rows)} row(s), all SENT with a webhook message id')
titles = [json.dumps(h.get('embeds'), sort_keys=True) for h in _srv_hits]
check(len(_srv_hits) == len(filled) and len(set(titles)) == len(titles),
      f'webhook received each filled card exactly once ({len(_srv_hits)} posts, {len(set(titles))} distinct)')
check(all(h.get('username') == 'Mag 7 Algo' for h in _srv_hits), 'posted under the "Mag 7 Algo" name')
_txt = json.dumps(_srv_hits)
check(not any(w in _txt for w in ('Actual fill', 'Planned contracts', 'awaiting fill', 'GREEN', 'RED EXIT',
                                  'Campaign ', 'Jakenew', 'Option return')),
      'member cards carry no trade-call titles, "Actual fill", planned contracts, returns, campaign ids or old name')
check(all(h.get('allowed_mentions') == {'parse': []} for h in _srv_hits), 'no card can ping anyone')
check(mid_cards > 0 and mid_cards < len(_srv_hits), 'cards were delivered both before and after the restart')

print('── duplicate events ──')
n_fills, n_hits = len(j.fills()), len(_srv_hits)
from campaign_flow import executor  # noqa: E402
for k in range(3):                                          # the broker keeps reporting the same cumulative fills
    for f in executor.sync(r2.pipe, obs[-1]['ts'] + 1 + k):
        (r2.pipe.router.entry_fill if f['kind'] == 'ENTRY' else r2.pipe.router.exit_fill)(f)
check(len(j.fills()) == n_fills, 'repeated broker status reads add no fill')
r2.pipe._card('ENTRY_PROPOSED', calls[0]['campaign_id'], obs[-1]['ts'], price=calls[0]['proposal_ask'],
              qty=calls[0]['planned_qty'], card_id=f"{calls[0]['campaign_id']}:EP")     # same card id again
notify.flush()
check(len(_srv_hits) == n_hits and len(outbox_rows()) == len(ob_rows),
      're-emitting an already-delivered card is a no-op (journal card id + outbox idempotency key)')

srv.shutdown()
print()
print(f"{len(FAILS)} failure(s)" if FAILS else "PAPER E2E CHECKS PASSED (synthetic test data)")
sys.exit(1 if FAILS else 0)
