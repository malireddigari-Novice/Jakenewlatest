"""§13/§14 Order routing and fill reconciliation — kept separate from the decision to request an order.

One entry order per campaign (order key `<campaign>:E`, broker client_order_id `cf-<campaign>-E`) and exit
orders `<campaign>:X<n>`; keys are persisted before submission and the broker rejects a reused client id, so
repeated observations or a restart can never create a duplicate order. Fills are derived from the broker's
cumulative filled quantity; each increment becomes one fill event `<broker id>:<cumulative qty>` (idempotent).

  SimBroker          SHADOW mode. Fills against the observed quote only (buy fills when ask <= limit, sell when
                     bid >= limit); fills are tagged source=SIM and are never published as executions.
  AlpacaPaperBroker  PAPER mode. Real Alpaca paper limit orders, statuses and cancellations.
"""
import logging

from campaign_flow import settings as S
from campaign_flow.model import stable_id

logger = logging.getLogger(__name__)

EXIT_REPRICE_S = 30
FINAL = ('FILLED', 'CANCELED', 'EXPIRED', 'REJECTED')


class SimBroker:
    source = 'SIM'

    def submit(self, o, pipe) -> dict:
        return {'broker_order_id': 'sim-' + o['client_order_id'], 'status': 'SUBMITTED'}

    def status(self, o, pipe, ts) -> dict:
        if o['status'] == 'CANCEL_REQUESTED':
            return {'status': 'CANCELED', 'filled_qty': o['filled_qty'], 'avg_price': o.get('avg_price')}
        q = pipe._quotes.get(o['occ']) or {}
        fresh = q.get('ts') is not None and 0 <= ts - q['ts'] <= S.QUOTE_MAX_AGE_S
        if fresh and o['side'] == 'buy' and q.get('ask') and q['ask'] <= o['limit_price'] and (q.get('ask_size') or 0) >= 1:
            return {'status': 'FILLED', 'filled_qty': o['qty'], 'avg_price': o['limit_price']}
        if fresh and o['side'] == 'sell' and q.get('bid') and q['bid'] >= o['limit_price'] and (q.get('bid_size') or 0) >= 1:
            return {'status': 'FILLED', 'filled_qty': o['qty'], 'avg_price': o['limit_price']}
        return {'status': o['status'], 'filled_qty': o['filled_qty'], 'avg_price': o.get('avg_price')}

    def cancel(self, o) -> bool:
        return True


class AlpacaPaperBroker:
    source = 'ALPACA_PAPER'

    def __init__(self, client) -> None:
        self.c = client

    def submit(self, o, pipe) -> dict:
        r = self.c.submit_limit(o['occ'], o['side'], o['qty'], o['limit_price'], o['client_order_id'])
        if r is None:
            existing = self.c.get_order_by_client_id(o['client_order_id'])     # submitted before a crash?
            if existing:
                r = existing
        if r is None:
            return {'broker_order_id': None, 'status': 'REJECTED'}
        return {'broker_order_id': r.get('id'), 'status': 'SUBMITTED'}

    def status(self, o, pipe, ts) -> dict:
        r = self.c.get_order_by_client_id(o['client_order_id'])
        if not r:
            return {'status': o['status'], 'filled_qty': o['filled_qty'], 'avg_price': o.get('avg_price')}
        st = (r.get('status') or '').lower()
        mapped = {'filled': 'FILLED', 'canceled': 'CANCELED', 'expired': 'EXPIRED', 'rejected': 'REJECTED',
                  'partially_filled': 'PARTIAL', 'done_for_day': 'EXPIRED'}.get(st, o['status'])
        fq = int(float(r.get('filled_qty') or 0))
        ap = float(r['filled_avg_price']) if r.get('filled_avg_price') else None
        return {'status': mapped, 'filled_qty': fq, 'avg_price': ap, 'broker_ts': r.get('filled_at') or r.get('updated_at')}

    def cancel(self, o) -> bool:
        return bool(o.get('broker_order_id')) and self.c.cancel_order(o['broker_order_id'])


def _submit(pipe, c, kind, n, side, qty, limit, ts):
    key = f"{c['campaign_id']}:{kind}{n if kind == 'X' else ''}"
    if pipe.j.order(key):
        return
    o = {'order_key': key, 'campaign_id': c['campaign_id'], 'kind': 'ENTRY' if kind == 'E' else 'EXIT',
         'client_order_id': f"cf-{c['campaign_id']}-{kind}{n if kind == 'X' else ''}", 'occ': c['contract']['occ'],
         'side': side, 'qty': int(qty), 'limit_price': round(float(limit), 2), 'status': 'NEW', 'filled_qty': 0,
         'avg_price': None, 'submitted_ts': ts}
    pipe.j.put_order(o)                                 # persisted BEFORE the broker sees it
    r = pipe.broker.submit(o, pipe)
    o.update(r)
    pipe.j.put_order(o)
    pipe.j.log(ts, 'ORDER_SUBMITTED', {k: o[k] for k in ('order_key', 'client_order_id', 'side', 'qty',
                                                          'limit_price', 'status')} | {'source': pipe.broker.source},
               ticker=c['ticker'], ref=c['campaign_id'])


def sync(pipe, ts: float) -> list:
    """Submit what decisions require, then reconcile every open order. Returns fill/cancel events."""
    j, events = pipe.j, []
    pending = getattr(pipe, 'pending_exit', {}) or {}
    for c in j.campaigns(('PROPOSED', 'ACTIVE', 'ENTRY_PENDING')):
        if c['state'] == 'PROPOSED' and c['outstanding_entry_qty'] > 0:
            _submit(pipe, c, 'E', 0, 'buy', c['outstanding_entry_qty'], c['proposal_ask'], ts)
        p = pending.get(c['campaign_id'])
        if c.get('exit_pending') and c['held_qty'] > 0 and p and p[2] == ts:
            exits = [o for o in j.orders(c['campaign_id']) if o['kind'] == 'EXIT']
            if not any(o['status'] not in FINAL for o in exits):
                _submit(pipe, c, 'X', len(exits) + 1, 'sell', c['held_qty'], p[1], ts)
    for o in j.orders(open_only=True):
        st = pipe.broker.status(o, pipe, ts)
        fq = int(st.get('filled_qty') or 0)
        if fq > o['filled_qty'] and st.get('avg_price') is not None:
            d = fq - o['filled_qty']
            px = (st['avg_price'] * fq - (o.get('avg_price') or 0) * o['filled_qty']) / d
            events.append({'event_id': f"{o.get('broker_order_id') or o['client_order_id']}:{fq}",
                           'campaign_id': o['campaign_id'], 'kind': o['kind'], 'qty': d, 'price': round(px, 4),
                           'ts': ts, 'order_id': o.get('broker_order_id'), 'source': pipe.broker.source,
                           'broker_ts': st.get('broker_ts')})
            o['filled_qty'], o['avg_price'] = fq, st['avg_price']
        if st['status'] in FINAL:
            o['status'] = st['status']
            if o['kind'] == 'ENTRY' and fq < o['qty']:
                events.append({'event_id': f"{o['order_key']}:cancel", 'campaign_id': o['campaign_id'],
                               'kind': 'CANCEL', 'ts': ts})
        else:
            if st['status'] in ('PARTIAL',) and o['status'] != 'CANCEL_REQUESTED':
                o['status'] = 'PARTIAL'
            age = ts - o['submitted_ts']
            limit_age = S.ENTRY_ORDER_TTL_S if o['kind'] == 'ENTRY' else EXIT_REPRICE_S
            if age > limit_age and o['status'] != 'CANCEL_REQUESTED':
                if pipe.broker.cancel(o):
                    o['status'] = 'CANCEL_REQUESTED'
        j.put_order(o)
    return events


def order_event_id(*parts) -> str:
    return stable_id('order', *parts)
