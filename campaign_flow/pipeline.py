"""Deterministic processor: observations in → windows, board, clusters, proposals, management, orders, cards.

Live and replay feed the SAME observation stream (recorded by the runner), so a replay of a session reproduces
its decisions exactly. Observation kinds (all carry `ts` = when the data became AVAILABLE to the bot):

  poll        one ticker's option snapshot: spot, covered expirations, listed strikes, per-contract quote/trade/
              cumulative volume, plus the legacy engine's route/attention score for side-by-side comparison
  listing     listed contracts per ticker/expiry inside the scan band (strike-coverage assertion)
  chain       a published OI chain (all expirations; adapter-verified completeness)
  turnover    exact-contract memory: previous-session volume, prior reference premium, morning OI
  value_refs  earlier exact-series marks (trade basis) with their own timestamps
  baseline    comparable-window baselines per series and time-of-day bucket
  opening     the actual regular-session opening price (pinned once)
  prior_close the prior regular-session close

SNAPSHOT ADAPTER DEFINITIONS (§21 — documented, not inferred from the source package):
  window       aligned CF_WINDOW_S slot; start/end = the polls bracketing it (identical for every contract of a
               ticker, so multi-strike slots match); bins = the per-poll increments (disjoint, sum = volume)
  near-ask     a poll interval's increment counts as near-ask when the interval's newest print is an ordinary
               electronic print located >= CF_NEAR_ASK_LOCATION inside the latest quote at/before it
               (provenance SNAPSHOT_LAST_PRINT_PER_POLL_INTERVAL — a proxy, weaker than a trade-by-trade tape)
  prints       lower bound: poll intervals that carried a new print
  largest print lower bound: largest newest-print size seen
  complex      MIXED if any observed print has a complex/stock-tied condition, else UNAVAILABLE (never SIMPLE)
  baseline     same contract's mean volume per window in the same time-of-day bucket of the prior session
               (1-min bars); fallback prior-session daily volume spread evenly; floor CF_BASELINE_FLOOR
  value refs   prior-session 1-min bar closes + today's observed prints, trade basis; event premium = the
               window's newest print (trade basis); acceptance uses quote mids at the window bounds
  underlying   engine rule dS over CF_UNDERLYING_WINDOW_S; bullish if > 0, bearish if < 0 (flat confirms neither)
  sync         share of contracts whose quote is <= CF_QUOTE_MAX_AGE_S old and not future-dated (beyond
               CF_QUOTE_CLOCK_TOL_S) >= CF_SYNC_MIN_FRESH_FRAC
  poll ts      the local RECEIPT time of the ticker's last snapshot response (`timing.recv_ts`), never the
               poll-cycle start: tickers are fetched sequentially, so a cycle-start stamp precedes quotes that
               arrived up to ~30 s later and makes them look future-dated. `timing` keeps the cycle start,
               fetch start, receipt and server HTTP Date for audit; quotes that still lead the receipt time
               are counted (`future_quotes`, `max_quote_lead_s`) and journaled as QUOTE_TIMING
"""
import logging
from collections import defaultdict, deque
from datetime import date

from campaign_flow import board as boardmod
from campaign_flow import calendar_ny as cal
from campaign_flow import cards
from campaign_flow import clusters
from campaign_flow import conviction
from campaign_flow import oi_ref
from campaign_flow import settings as S
from campaign_flow import shock
from campaign_flow import turnover
from campaign_flow import value_gate
from campaign_flow.model import contract as mkcontract
from campaign_flow.model import series_key, stable_id
from campaign_flow.policy import OPEN_STATES, Router
from tape import conditions as cond

logger = logging.getLogger(__name__)

MARK_OFFSETS = (('+5m', 300), ('+15m', 900), ('+30m', 1800))


def tod_bucket(ts: float) -> str:
    t = cal.ny_dt(ts)
    m = t.hour * 60 + t.minute
    return 'OPEN' if m < 10 * 60 else ('CLOSE' if m >= 15 * 60 else 'MID')


class Pipeline:

    def __init__(self, journal, broker, publish=None) -> None:
        self.j = journal
        self.router = Router(journal)
        self.broker = broker
        self.publish = publish                      # callable(card_payload, card_id) for public delivery
        self.session = None
        self._samples = defaultdict(deque)          # series -> deque of sample dicts (this session)
        self._contract = {}                         # series -> contract dict
        self._slot = {}                             # ticker -> current aligned slot start
        self._items = defaultdict(list)             # ticker -> [{'w','q','res'}] in lookback
        self._spot = defaultdict(deque)             # ticker -> (ts, spot)
        self._snapshot = {}                         # ticker -> latest full flow snapshot
        self._quotes = {}                           # occ -> latest quote dict
        self._listing = {}                          # (ticker, expiry) -> {'C': set, 'P': set}
        self._refs = defaultdict(list)              # series -> value references
        self._baseline = {}                         # (series, bucket) -> per-window baseline
        self._daily_base = {}                       # series -> prev-session daily volume
        self._prior_close = {}                      # ticker -> {'price', 'ts'}
        self._legacy = {}                           # ticker -> legacy scores at the latest poll
        self._last_board = None
        self._last_poll = {}                        # ticker -> ts of the last processed poll
        self._timing_logged = {}                    # ticker -> slot of the last QUOTE_TIMING journal row
        self._conv = {}                             # ticker -> conviction.assess() at the latest evaluation
        self._side_hist = defaultdict(list)         # (ticker, right) -> [(window end, near-money volume)] today
        self._range = {}                            # ticker -> [session high, session low] of observed spot
        self.rebuilding = False                     # True while replaying the session log after a restart

    # ── session ────────────────────────────────────────────────────────────────
    def _roll(self, ts):
        d = cal.ny_day(ts).isoformat()
        if d != self.session:
            self.session = d
            for x in (self._samples, self._items, self._spot, self._refs):
                x.clear()
            for x in (self._slot, self._snapshot, self._quotes, self._listing, self._baseline,
                      self._daily_base, self._legacy, self._prior_close, self._last_poll, self._conv,
                      self._side_hist, self._range):
                x.clear()
            self.router.reconcile_prior_sessions(d, ts)

    def feed(self, ob: dict) -> None:
        self._roll(ob['ts'])
        getattr(self, '_on_' + ob['kind'])(ob)

    # ── reference data ─────────────────────────────────────────────────────────
    def _on_listing(self, ob):
        self._listing[(ob['ticker'], ob['expiry'])] = {'C': set(map(float, ob['C'])), 'P': set(map(float, ob['P'])),
                                                       'band': ob.get('band')}

    def _on_chain(self, ob):
        self.j.add_chain(ob['chain'])

    def _on_turnover(self, ob):
        for m in ob['records']:
            self.j.add_turnover(m)
            if m.get('prev_volume') is not None:
                self._daily_base[tuple(m['series'])] = m['prev_volume']

    def _on_value_refs(self, ob):
        for key, refs in ob['refs']:
            self._refs[tuple(key)].extend(refs)

    def _on_baseline(self, ob):
        for key, bucket, per_window in ob['rows']:
            self._baseline[(tuple(key), bucket)] = per_window

    def _on_opening(self, ob):
        rec = self.j.put_opening(ob['record'])
        self.j.log(ob['ts'], 'OPENING_PRICE', rec, ticker=rec['ticker'])

    def _on_prior_close(self, ob):
        self._prior_close[ob['ticker']] = {'price': ob['price'], 'ts': ob['ts'], 'session': ob.get('session')}

    def _on_freeze(self, ob):
        d = date.fromisoformat(self.session)
        f = oi_ref.freeze(self.j.chains(ob['ticker'], self.session), ob['ticker'], d, ob['ts'])
        stored = self.j.put_freeze(f)
        self.j.log(ob['ts'], 'OI_FREEZE' if not f['missing'] else 'OI_FREEZE_MISSING',
                   {k: stored.get(k) for k in ('expiry', 'reason', 'source_id', 'published_ts', 'cutoff_ts',
                                               'invoked_ts', 'missing')} | {'rows': len(stored.get('rows') or [])},
                   ticker=ob['ticker'])

    # ── polls ──────────────────────────────────────────────────────────────────
    def _on_poll(self, ob):
        t, ts = ob['ticker'], float(ob['ts'])
        if self._last_poll.get(t) is not None and ts <= self._last_poll[t]:
            if not self.rebuilding:
                self.j.log(ts, 'POLL_REJECTED', {'reason': 'DUPLICATE_OR_OUT_OF_ORDER_POLL'}, ticker=t)
            return
        self._last_poll[t] = ts
        self._spot[t].append((ts, ob['spot']))
        rg = self._range.setdefault(t, [ob['spot'], ob['spot']])
        rg[0], rg[1] = max(rg[0], ob['spot']), min(rg[1], ob['spot'])
        while self._spot[t] and ts - self._spot[t][0][0] > 600:
            self._spot[t].popleft()
        self._legacy[t] = ob.get('legacy') or {}
        slot = int(ts // S.WINDOW_S) * S.WINDOW_S
        prev_slot = self._slot.get(t)
        closed = []
        if prev_slot is not None and slot != prev_slot:
            closed = self._close_windows(t, prev_slot)
        self._slot[t] = slot
        fresh, n, future, lead = 0, 0, 0, None
        for occ, c in ob['contracts'].items():
            con = mkcontract(t, c['right'], c['strike'], c['expiry'], c.get('adj', ''), c.get('multiplier', 100))
            key = series_key(con)
            self._contract[key] = con
            smp = {'ts': ts, 'slot': slot, 'cum': c.get('cum_volume'), 'bid': c.get('bid'), 'ask': c.get('ask'),
                   'bid_size': c.get('bid_size'), 'ask_size': c.get('ask_size'), 'qts': c.get('quote_ts'),
                   'trade_ts': c.get('trade_ts'), 'trade_px': c.get('trade_px'), 'trade_size': c.get('trade_size'),
                   'trade_cond': c.get('trade_cond'), 'iv': c.get('iv'), 'day_volume': c.get('cum_volume')}
            dq = self._samples[key]
            if dq and smp['trade_ts'] and smp['trade_ts'] != dq[-1].get('trade_ts') and smp['trade_px']:
                self._refs[key].append({'series': list(key), 'ts': smp['trade_ts'], 'price': smp['trade_px'],
                                        'basis': 'TRADE', 'source': 'POLL_LATEST_TRADE'})
            dq.append(smp)
            while dq and ts - dq[0]['ts'] > S.SHOCK_MAX_WINDOW_S + 2 * S.WINDOW_S:
                dq.popleft()
            self._quotes[occ] = {'bid': c.get('bid'), 'ask': c.get('ask'), 'bid_size': c.get('bid_size'),
                                 'ask_size': c.get('ask_size'), 'ts': c.get('quote_ts'), 'feed': ob.get('feed'),
                                 'contract': con, 'day_volume': c.get('cum_volume')}
            n += 1
            if c.get('quote_ts') is not None:
                age = ts - c['quote_ts']
                lead = -age if lead is None else max(lead, -age)
                if age < -S.QUOTE_CLOCK_TOL_S:
                    future += 1
                elif age <= S.QUOTE_MAX_AGE_S:
                    fresh += 1
        self._snapshot[t] = self._build_snapshot(t, ob, ts, fresh, n, future, lead)
        if future and not self.rebuilding and self._timing_logged.get(t) != slot:
            self._timing_logged[t] = slot                 # at most one row per ticker per window slot
            self.j.log(ts, 'QUOTE_TIMING', {'future_quotes': future, 'contracts': n,
                                            'max_quote_lead_s': round(lead, 3), 'timing': ob.get('timing')},
                       ticker=t)
        if closed:
            self._evaluate(t, ts, closed)
        if not self.rebuilding:                     # a rebuild never decides, talks to the broker or fills marks
            self._manage(t, ts)
            self._marks(ts)
            self._sync_orders(ts)

    def _build_snapshot(self, t, ob, ts, fresh, n, future=0, lead=None) -> dict:
        exps = [str(e) for e in ob.get('expiries') or []]
        rights, complete = {}, bool(exps)
        have = defaultdict(lambda: {'C': set(), 'P': set()})
        for c in ob['contracts'].values():
            have[str(c['expiry'])][c['right']].add(float(c['strike']))
        for e in exps:
            rights[e] = sorted(r for r in ('C', 'P') if have[e][r])
            lst = self._listing.get((t, e))
            if not lst or not (lst['C'] <= have[e]['C'] and lst['P'] <= have[e]['P']):
                complete = False
        u = self._underlying(t, ts)
        return {'ticker': t, 'available_ts': ts, 'feed_ids': [ob.get('feed')],
                'coverage': {'expirations': exps, 'rights': rights, 'strikes_complete': complete,
                             'trade_quote_synced': n > 0 and fresh / n >= S.SYNC_MIN_FRESH_FRAC,
                             'evidence': {'fresh_quotes': fresh, 'contracts': n, 'future_quotes': future,
                                          'max_quote_lead_s': None if lead is None else round(lead, 3),
                                          'ts_basis': (ob.get('timing') or {}).get('basis', 'UNRECORDED')}},
                'underlying': u, 'oi_context': self.j.freeze(t, self.session)}

    def _underlying(self, t, ts) -> dict:
        then = None
        for s_ts, px in self._spot[t]:
            if s_ts <= ts - S.UNDERLYING_WINDOW_S:
                then = (s_ts, px)
        if then is None or not self._spot[t]:
            return {'bullish': False, 'bearish': False, 'evidence': {}}
        now_px = self._spot[t][-1][1]
        vel = now_px - then[1]
        return {'bullish': vel > 0, 'bearish': vel < 0,
                'evidence': {'rule': 'ENGINE_DS_WINDOW_FAST_STRICT', 'value': round(vel, 4),
                             'window_s': S.UNDERLYING_WINDOW_S, 'spot_now': now_px, 'spot_then': then[1],
                             'then_ts': then[0]}}

    # ── windows ────────────────────────────────────────────────────────────────
    def _close_windows(self, t, slot) -> list:
        out = []
        for key, dq in self._samples.items():
            if key[0] != t:
                continue
            inside = [s for s in dq if s['slot'] == slot]
            before = [s for s in dq if s['slot'] < slot]
            if not inside or not before or inside[-1]['cum'] is None or before[-1]['cum'] is None:
                continue
            w = self._window(key, before[-1], inside)
            if w is not None:
                out.append(w)
        return out

    def _window(self, key, anchor, inside):
        con = self._contract[key]
        chain = [anchor] + inside
        vol = int(chain[-1]['cum']) - int(anchor['cum'])
        if vol < 0:
            return None
        bins, near, prints, largest, complex_seen, last_trade = [], 0, 0, None, False, None
        for a, b in zip(chain, chain[1:]):
            inc = max(0, int(b['cum']) - int(a['cum']))
            bins.append(inc)
            new_trade = b.get('trade_ts') and b['trade_ts'] != a.get('trade_ts') and b['trade_ts'] > a['ts'] - 1e-9
            if not new_trade:
                continue
            prints += 1
            largest = max(largest or 0, int(b.get('trade_size') or 0))
            tags = cond.tags(b.get('trade_cond'))
            if 'COMPLEX' in tags or 'STOCK_TIED' in tags:
                complex_seen = True
            last_trade = b
            q = next((x for x in (b, a) if x.get('qts') is not None and x['qts'] <= b['trade_ts']
                      and x.get('bid') is not None and x.get('ask') and x['ask'] > x['bid']), None)
            if inc and q is not None and cond.side_eligible(tags):
                loc = (float(b['trade_px']) - q['bid']) / (q['ask'] - q['bid'])
                if loc >= S.NEAR_ASK_LOCATION:
                    near += inc
        if sum(bins) != vol:            # a reset/decrease inside the slot: the window cannot be trusted
            return None
        mid = lambda s: (s['bid'] + s['ask']) / 2 if (s.get('bid') is not None and s.get('ask')) else None
        start, end = anchor['ts'], chain[-1]['ts']
        bucket = tod_bucket(end)
        base, method = self._baseline.get((key, bucket)), 'PRIOR_SESSION_SAME_TOD_BUCKET_MEAN'
        if base is None and self._daily_base.get(key) is not None:
            o_c = cal.bounds(cal.ny_day(end))
            mins = (o_c[1] - o_c[0]) / 60 if o_c else 390
            base, method = self._daily_base[key] / mins * (S.WINDOW_S / 60), 'FALLBACK_PRIOR_DAILY_EVEN'
        if base is not None:
            base = max(S.BASELINE_FLOOR, base * (end - start) / S.WINDOW_S)
        exp_close = cal.bounds(date.fromisoformat(con['expiry']))
        w = {'contract': con, 'start': start, 'end': end, 'volume': vol, 'bins': bins,
             'prints': prints, 'prints_provenance': 'LOWER_BOUND_POLL_INTERVALS_WITH_NEW_PRINT',
             'largest_print': largest, 'largest_print_provenance': 'LOWER_BOUND_NEWEST_PRINT_PER_POLL',
             'near_ask': near, 'near_ask_provenance': 'SNAPSHOT_LAST_PRINT_PER_POLL_INTERVAL',
             'baseline': base, 'baseline_method': method if base is not None else None,
             'prem_start': mid(anchor), 'prem_end': mid(chain[-1]), 'prem_basis': 'QUOTE_MID',
             'event_premium': (last_trade or {}).get('trade_px'), 'event_premium_basis': 'TRADE',
             'spot': self._spot_at(con['ticker'], end), 'iv': chain[-1].get('iv'),
             'secs_to_last_trade': (exp_close[1] - end) if exp_close else None,
             'cum_volume': int(chain[-1]['cum']), 'complex_status': 'MIXED' if complex_seen else 'UNAVAILABLE',
             'available_ts': end, 'tod_bucket': bucket}
        w['value'] = value_gate.classify(con, w['event_premium'], self._refs.get(key, ()), start, 'TRADE')
        return w

    def _spot_at(self, t, ts):
        v = None
        for s_ts, px in self._spot[t]:
            if s_ts <= ts:
                v = px
        return v

    # ── evaluation ─────────────────────────────────────────────────────────────
    def _evaluate(self, t, ts, new_windows) -> None:
        keep = [it['w'] for it in self._items[t] if ts - float(it['w']['end']) <= S.FLOW_LOOKBACK_S]
        known = {w['id'] for w in keep}
        valid, rejected = shock.validate_windows(keep + new_windows, ts)
        for w, why in rejected:
            if w.get('id') not in known and not self.rebuilding:
                self.j.log(ts, 'WINDOW_REJECTED', {'occ': w['contract']['occ'], 'start': w['start'],
                                                   'end': w['end'], 'reasons': why}, ticker=t)
        old = {it['w']['id']: it for it in self._items[t]}
        items = []
        for w in valid:
            if w['id'] in old:
                it = old[w['id']]
                it['q'] = shock.qualify(w, ts)          # recency/lookback move with time
                items.append(it)
                continue
            key = series_key(w['contract'])
            mem = self.j.turnover(key, float(w['start']))
            coh = self.j.cohort(key, self.session)
            q = shock.qualify(w, ts)
            res = turnover.resemblance(w, mem, coh)
            if q['eligible'] and w['contract']['expiry'] == self.session and coh is None:
                self.j.put_cohort(key, self.session, {'window_id': w['id'], 'volume': w['volume'],
                                                      'anchor_cum': w['cum_volume'], 'end': w['end'],
                                                      'ref_premium': w['event_premium'], 'session': self.session})
            items.append({'w': w, 'q': q, 'res': res})
            if w['volume'] > 0 and not self.rebuilding:
                self.j.log(ts, 'WINDOW', {'occ': w['contract']['occ'], 'id': w['id'], 'start': w['start'],
                                          'end': w['end'], 'volume': w['volume'], 'bins': w['bins'],
                                          'prints': w['prints'], 'near_ask': w['near_ask'],
                                          'largest_print': w['largest_print'], 'baseline': w['baseline'],
                                          'baseline_method': w['baseline_method'], 'prem': [w['prem_start'], w['prem_end']],
                                          'event_premium': w['event_premium'], 'value': w['value'],
                                          'complex_status': w['complex_status'], 'qual': q, 'turnover': res},
                           ticker=t, ref=w['id'])
        self._items[t] = items
        spot = self._spot[t][-1][1] if self._spot[t] else None
        b = cal.bounds(cal.ny_day(ts))
        for right in ('C', 'P'):
            for (st, en), tot in conviction.slot_totals(new_windows, right, spot).items():
                if b and st >= b[0]:                # regular-session windows only (pre-open polls carry no flow)
                    self._side_hist[(t, right)].append((en, tot['vol']))
        cut = ts - S.CONV_SPAN_S
        self._conv[t] = conviction.assess(items, ts, spot, {r: [v for e, v in self._side_hist[(t, r)] if e < cut]
                                                            for r in ('C', 'P')})
        snap = self._snapshot.get(t)
        a = clusters.assess(snap, items, ts)
        self._states = {**getattr(self, '_states', {}), t: a['state']}
        if self.rebuilding:          # a restart rebuild only reconstructs memory: no decisions against
            return                   # journal state that is already ahead of the replay clock
        self._board(ts, {t: a['state']})
        self._rotation_entries(t, ts, a, snap)
        if a['calls_clustered'] or a['puts_clustered']:
            self._candidates(t, ts, a, snap)

    def _board(self, ts, states):
        self._states = {**getattr(self, '_states', {}), **states}
        ev = [(it['w'], it['q'], it['res']) for its in self._items.values() for it in its
              if ts - float(it['w']['end']) <= S.FLOW_LOOKBACK_S]
        b = boardmod.build(ev, ts, self._states)
        sig = (b['order'], [(t, b['rows'][t]['ticker_raw'], b['rows'][t]['ticker_discounted'], b['rows'][t]['state'])
                            for t in b['order']])
        if sig != self._last_board:
            self._last_board = sig
            self.j.log(ts, 'BOARD', b)
        self.board = b

    # ── candidates ─────────────────────────────────────────────────────────────
    def _choices(self, t, cl_list, right):
        """Contracts at the clusters' own (expiration, strike): a cluster never selects another expiration."""
        keys = {(str(cl['expiry']), float(k)) for cl in cl_list for k in cl['strikes']}
        out = []
        for occ, q in self._quotes.items():
            c = q['contract']
            if c['ticker'] == t and c['right'] == right and (str(c['expiry']), float(c['strike'])) in keys:
                out.append({'contract': c, 'quote': {k: q[k] for k in ('bid', 'ask', 'bid_size', 'ask_size', 'ts', 'feed')},
                            'day_volume': q.get('day_volume'), 'oi': None, 'utility': None})
        return out

    @staticmethod
    def _cluster_id(t, direction, cl) -> str:
        return stable_id('cluster', t, direction, cl['expiry'], cl['members'][0])

    def _consumed(self) -> set:
        return {x for c in self.j.campaigns() for x in c.get('cluster_ids') or []}

    def _horizon(self, t, ts, cls) -> tuple:
        """(horizon, clusters) for one side. When the nearest observed expiration expires today, flow in a
        LATER expiration is overnight positioning: proposed as OVERNIGHT only when the carry rule holds
        (CF_OVERNIGHT_*), otherwise journaled (OVERNIGHT_NOT_TAKEN) and not traded. Same-day flow, and every
        cluster on a day whose nearest expiration is tomorrow's (Tue/Thu), keeps the default horizon."""
        exps = (self._snapshot.get(t) or {}).get('coverage', {}).get('expirations') or []
        later = [cl for cl in cls if str(cl['expiry']) > self.session]
        if not S.OVERNIGHT_ENABLED or not later or self.session not in [str(e) for e in exps]:
            return S.DEFAULT_HORIZON, cls
        today = [cl for cl in cls if str(cl['expiry']) <= self.session]
        if today:
            return S.DEFAULT_HORIZON, today
        why = []
        if cal.ny_dt(ts).strftime('%H:%M') < S.OVERNIGHT_FROM_NY:
            why.append('OVERNIGHT_BEFORE_WINDOW')
        op = self.j.opening(t, self.session)
        rg = self._range.get(t)
        if not op or not rg:
            why.append('OVERNIGHT_RANGE_UNKNOWN')
        elif (rg[0] - rg[1]) / float(op['price']) > S.OVERNIGHT_MAX_RANGE_PCT:
            why.append('OVERNIGHT_DAY_NOT_CONSOLIDATED')
        if why:
            self.j.log(ts, 'OVERNIGHT_NOT_TAKEN', {'reasons': why, 'expiries': sorted({c['expiry'] for c in later}),
                                                   'range': rg, 'open': (op or {}).get('price')}, ticker=t)
            return None, []
        return 'OVERNIGHT', later

    def _candidates(self, t, ts, a, snap):
        consumed = self._consumed()
        for right, direction in (('C', 'BULLISH'), ('P', 'BEARISH')):
            horizon, cls = self._horizon(t, ts, a['clusters'][right])
            if not cls:
                continue
            ids = [self._cluster_id(t, direction, cl) for cl in cls]
            if any(i in consumed for i in ids):
                continue                                   # this evidence already produced a campaign
            first = min(cls, key=lambda c: (c['first_start'], c['expiry'], c['strikes']))
            eid = stable_id('cand', t, direction, first['expiry'], first['strikes'], first['members'][0])
            lg = self._legacy.get(t) or {}
            cand = {'event_id': eid, 'ts': ts, 'ticker': t, 'direction': direction, 'snapshot': snap,
                    'items': self._items[t], 'choices': self._choices(t, cls, right),
                    'route_score': lg.get('route_score'), 'attention_score': lg.get('attention_score'),
                    'stock_price': self._spot[t][-1][1] if self._spot[t] else None,
                    'upstream_vetoes': [], 'evidence_times': [snap['available_ts']], 'cluster_ids': ids,
                    'horizon': horizon, 'conviction': (self._conv.get(t) or {}).get(right)}
            prior = self.j.event(eid)
            if prior and prior.get('decision') == 'PROPOSE':
                continue                                   # this cluster already produced its proposal
            if prior:                                      # re-evaluate the same cluster as it develops
                cand['event_id'] = eid = stable_id('cand', eid, ts)
            r = self.router.propose(cand)
            if r.get('duplicate'):
                continue
            if r['decision'] == 'PROPOSE':
                self._card('ENTRY_PROPOSED', r['campaign_id'], ts, price=r['indicative_ask'], qty=r['qty'],
                           card_id=f"{r['campaign_id']}:EP")
                self._schedule_marks(r['campaign_id'], r['contract']['occ'], ts, r['indicative_ask'], 'PROPOSAL')
            else:
                best = max(cls, key=lambda c: c['latest_end'])
                occs = [q['contract']['occ'] for q in self._choices(t, [best], right)]
                for occ in occs[:2]:
                    self._schedule_marks(eid, occ, ts, (self._quotes.get(occ) or {}).get('ask'), 'SUPPRESSED')

    def _rotation_entries(self, t, ts, a, snap):
        for src in self.j.campaigns(('CLOSED',)):
            d = src.get('closed_rotation_direction')
            if src['ticker'] != t or not d or src.get('rotation_entry'):
                continue
            right = 'C' if d == 'BULLISH' else 'P'
            horizon, cls = self._horizon(t, ts, a['clusters'][right])
            eid = stable_id('rot', src['campaign_id'], ts)
            cand = {'event_id': eid, 'ts': ts, 'ticker': t, 'direction': d, 'snapshot': snap,
                    'items': self._items[t], 'choices': self._choices(t, cls, right) if cls else [],
                    'route_score': (self._legacy.get(t) or {}).get('route_score'),
                    'stock_price': self._spot[t][-1][1] if self._spot[t] else None,
                    'source_campaign_id': src['campaign_id'], 'evidence_times': [snap['available_ts']],
                    'cluster_ids': [self._cluster_id(t, d, cl) for cl in cls], 'horizon': horizon,
                    'conviction': (self._conv.get(t) or {}).get(right)}
            r = self.router.propose(cand)
            if r.get('decision') == 'PROPOSE':
                src['rotation_entry'] = r['campaign_id']
                self.j.put_campaign(src)
                self._card('ENTRY_PROPOSED', r['campaign_id'], ts, price=r['indicative_ask'], qty=r['qty'],
                           card_id=f"{r['campaign_id']}:EP")

    # ── management ─────────────────────────────────────────────────────────────
    def _manage(self, t, ts):
        snap = self._snapshot.get(t)
        op = self.j.opening(t, self.session)
        pc = self._prior_close.get(t)
        for c in self.j.campaigns(('ACTIVE', 'ENTRY_PENDING')):
            if c['ticker'] != t:
                continue
            q = self._quotes.get(c['contract']['occ'])
            u = (snap or {}).get('underlying') or {}
            obs = {'event_id': stable_id('mg', c['campaign_id'], ts), 'ts': ts, 'campaign_id': c['campaign_id'],
                   'quote': q, 'stock_price': self._spot[t][-1][1] if self._spot[t] else None,
                   'structural_break': {'bullish': u.get('bullish'), 'bearish': u.get('bearish'),
                                        'evidence': u.get('evidence')},
                   'snapshot': snap, 'items': self._items[t],
                   'prior_close': (pc or {}).get('price'),
                   'open_price': (op or {}).get('price') if op and float(op['available_ts']) <= ts else None,
                   'open_time': (op or {}).get('open_ts'), 'conviction': self._conv.get(t)}
            was_pending = bool(c.get('exit_pending'))
            r = self.router.manage(obs)
            if r['decision'] in ('EXIT_REQUEST', 'EXIT_PENDING_EXECUTABLE_QUOTE') and not was_pending:
                ref_px = (q or {}).get('bid')
                self._card('EXIT_PROPOSED', c['campaign_id'], ts, price=ref_px if ref_px else None,
                           qty=c['held_qty'], reasons=r['reasons'], card_id=f"{c['campaign_id']}:XP")
            if r['decision'] == 'EXIT_REQUEST':
                self.pending_exit = getattr(self, 'pending_exit', {})
                self.pending_exit[c['campaign_id']] = (r['qty'], r['reference_bid'], ts)
            elif r['decision'] == 'EXIT_PENDING_EXECUTABLE_QUOTE':
                self.j.log(ts, 'EXIT_PENDING_EXECUTABLE_QUOTE', {'campaign_id': c['campaign_id'],
                                                                 'quote': q and {k: q.get(k) for k in ('bid', 'bid_size', 'ts')}},
                           ticker=t, ref=c['campaign_id'])

    # ── orders / fills ─────────────────────────────────────────────────────────
    def _sync_orders(self, ts):
        from campaign_flow import executor
        for f in executor.sync(self, ts):
            c = self.j.campaign(f['campaign_id'])
            if f['kind'] == 'ENTRY':
                r = self.router.entry_fill(f)
                if r.get('accepted') and not r.get('duplicate'):
                    self._card('ENTRY_FILLED', c['campaign_id'], f['ts'], price=f['price'], qty=f['qty'],
                               card_id=f"{f['event_id']}:EF", source=f.get('source'))
            elif f['kind'] == 'EXIT':
                r = self.router.exit_fill(f)
                if r.get('accepted') and not r.get('duplicate'):
                    c2 = self.j.campaign(f['campaign_id'])
                    self._card('EXIT_FILLED', c['campaign_id'], f['ts'], price=f['price'], qty=f['qty'],
                               reasons=(c2.get('exit_pending') or {}).get('reasons'), avg=c2['avg_entry'],
                               remaining=c2['held_qty'] or None, card_id=f"{f['event_id']}:XF",
                               source=f.get('source'))
            elif f['kind'] == 'CANCEL':
                self.router.cancel_confirmed(f)

    # ── cards / marks ──────────────────────────────────────────────────────────
    def _card(self, label, cid, ts, *, price=None, qty=None, reasons=None, avg=None, remaining=None,
              card_id, source=None):
        c = self.j.campaign(cid)
        try:
            payload = cards.render(label, c, ts=ts, price=price, qty=qty, reasons=reasons, avg_entry=avg,
                                   partial_remaining=remaining)
        except cards.CardError as exc:
            self.j.log(ts, 'CARD_REJECTED', {'label': label, 'error': str(exc)}, ticker=c['ticker'], ref=cid)
            return
        public = (S.MODE == 'PAPER' and S.DISCORD_ENABLED and source != 'SIM' and self.publish is not None
                  and (label.endswith('FILLED') or S.PUBLISH_PROPOSED))
        sheet = {'price': price, 'qty': qty, 'remaining': remaining, 'avg': avg, 'reasons': reasons}
        if self.j.put_card(card_id, cid, label, ts, {**payload, 'sheet': sheet}, published=public) and public:
            self.publish(payload, card_id)

    def _schedule_marks(self, ref, occ, ts, ask, kind):
        for label, off in MARK_OFFSETS:
            self.j.add_mark(stable_id('mk', ref, occ, label), ref, occ, label, ts + off,
                            {'kind': kind, 'origin_ts': ts, 'origin_ask': ask})
        d = cal.ny_day(ts)
        b = cal.bounds(d)
        if b:
            self.j.add_mark(stable_id('mk', ref, occ, 'close'), ref, occ, 'session_close', b[1] - 60,
                            {'kind': kind, 'origin_ts': ts, 'origin_ask': ask})
            nb = cal.bounds(cal.next_trading_day(d))
            self.j.add_mark(stable_id('mk', ref, occ, 'next_open'), ref, occ, 'next_open', nb[0] + 60,
                            {'kind': kind, 'origin_ts': ts, 'origin_ask': ask})

    def _marks(self, ts):
        for m in self.j.due_marks(ts):
            q = self._quotes.get(m['occ'])
            if q is None:
                if ts - m['due_ts'] > 600:
                    self.j.complete_mark(m['mark_id'], {**m, 'issue': 'NO_QUOTE_OBSERVED'})
                continue
            issue = None
            if q.get('ts') is None or ts - q['ts'] > S.QUOTE_MAX_AGE_S:
                issue = 'DELAYED_QUOTE'
            elif not q.get('bid'):
                issue = 'ZERO_BID'
            self.j.complete_mark(m['mark_id'], {**m, 'observed_ts': ts, 'bid': q.get('bid'), 'ask': q.get('ask'),
                                                'quote_ts': q.get('ts'), 'feed': q.get('feed'), 'issue': issue,
                                                'note': 'shadow mark — an observation, never a fill'})
