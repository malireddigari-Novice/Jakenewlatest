"""
The tape-lane processor (flow handoff §3–§9). ONE deterministic pipeline for live capture and replay:
`dispatch(record)` consumes archive records in arrival order, so replaying an archive reproduces the
live process's state exactly.

Per print it answers four SEPARATE questions and never merges them:
  what printed            — the print, its condition tags, venue, corrections (prints table)
  who likely took liquidity — LIKELY_TAKER_BUY / LIKELY_TAKER_SELL / UNKNOWN (tape.side)
  open/close effect       — never known from the tape; only aggregate OI annotations next session
  separate trade merit    — not decided here (research outcome ledger only)

Observation dimensions are kept apart: rarity (screens), linkage (packages), side thesis (NEUTRAL /
WORKING_HYPOTHESIS), OI annotation, revisions, event (catalyst), urgency (DTE channel), executability
(quote), coverage (context_only). No single confidence number, no PROBABLE/LIKELY/CONFIRMED promotion.
"""
import hashlib
import json
import logging
from collections import defaultdict
from datetime import date

from analysis import catalyst as catalyst_mod
from analysis import channels
from tape import cards, conditions, events, oi as oi_mod, packages, settings
from tape.side import BUY, SELL, UNKNOWN, QuoteBook, SpotBook, SweepDetector, classify, spot_at

logger = logging.getLogger(__name__)

SCREENS = ('REL_VOLUME', 'REL_PREMIUM', 'VOL_GT_OI', 'QUOTE_SIDE', 'SHORT_DATED_OTM', 'REPEATED')


class _P:
    """Lightweight per-series print record (the full record lives in the prints table)."""
    __slots__ = ('key', 'size', 'price', 'side', 'exchange', 'event_ns', 'premium', 'spot', 'ordinary',
                 'stock_tied', 'counted')

    def __init__(self, key, size, price, side, exchange, event_ns, premium, spot, ordinary, stock_tied):
        self.key, self.size, self.price, self.side, self.exchange = key, size, price, side, exchange
        self.event_ns, self.premium, self.spot, self.ordinary = event_ns, premium, spot, ordinary
        self.stock_tied, self.counted = stock_tied, True


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


class Pipeline:

    def __init__(self, store, session: date, baselines, contracts: dict, *, universe_size: int = 0,
                 emit=None, catalyst_rows=None) -> None:
        self.store, self.session, self.base = store, session, baselines
        self.contracts = contracts                    # occ -> {underlying, expiry, right, strike, multiplier, adjusted}
        self.universe_size = universe_size or len(contracts)
        self.emit = emit or (lambda card: None)       # delivery hook (outbox); cards are stored regardless
        self.catalyst_rows = catalyst_rows
        self.quotes, self.spots, self.sweeps = QuoteBook(), SpotBook(), SweepDetector()
        self.grouper = packages.Grouper()
        self.series = defaultdict(lambda: {'prints': [], 'earned': {}, 'obs': None, 'agg': None})
        self.seen_stream, self.seen_bf = defaultdict(int), defaultdict(int)
        self.last_ns = {}
        self.watermark = 0
        self.gaps = []                                # [{start_ns, end_ns, trades_recovered}]
        self.context_only = {}                        # occ -> reason
        self.feed_up = False
        self.watch_legs = {}                          # occ -> [watch_id]
        self.pending_outcomes = []
        self.stats = defaultdict(int)
        self._campaign_last_post = {}

    # ── dispatch (live + replay share this) ──────────────────────────────────

    def dispatch(self, rec: dict) -> None:
        kind, p, recv = rec['kind'], rec['payload'], rec['recv_ns']
        if kind == 'quote':
            self.on_quote(events.Quote(**p['norm']))
        elif kind == 'spot':
            self.on_spot(events.Spot(**p['norm']))
        elif kind == 'trade':
            self.on_trade(events.Trade(**p['norm']))
        elif kind == 'status':
            self.on_status(p, recv)

    # ── coverage ──────────────────────────────────────────────────────────────

    def on_status(self, p: dict, recv_ns: int) -> None:
        ev = p.get('event')
        if ev == 'feed_up':
            if self.gaps and self.gaps[-1]['end_ns'] is None:
                self.gaps[-1]['end_ns'] = recv_ns
            self.feed_up = True
        elif ev == 'feed_down':
            self.feed_up = False
            self.gaps.append({'start_ns': recv_ns, 'end_ns': None, 'trades_recovered': False,
                              'reason': p.get('reason')})
            self.store.incident('FEED_DISCONNECT', '*', recv_ns, None, p, 'PENDING', self.session.isoformat())
            self._emit(cards.degradation(self.session, p, recv_ns))
        elif ev == 'backfill_done':
            gap = next((g for g in reversed(self.gaps) if g['start_ns'] == p.get('gap_start_ns')), None)
            if gap:
                gap['trades_recovered'] = bool(p.get('complete'))
            rec = 'TRADES_BACKFILLED_QUOTES_MISSING' if p.get('complete') else 'INCOMPLETE'
            self.store.x("UPDATE incidents SET end_ns=?, recovery=? WHERE kind='FEED_DISCONNECT' AND start_ns=?",
                         (p.get('gap_end_ns'), rec, p.get('gap_start_ns')))
            if not p.get('complete'):
                for occ in self.contracts:
                    self.context_only.setdefault(occ, 'trade backfill incomplete')
        elif ev in ('subscription_failed', 'buffer_overflow', 'stale_feed', 'conflict'):
            self.store.incident(ev.upper(), p.get('scope', '*'), recv_ns, recv_ns, p, 'NONE', self.session.isoformat())
            for occ in p.get('contracts') or ([] if p.get('scope', '*') != '*' else self.contracts):
                self.context_only.setdefault(occ, ev)

    def _in_gap(self, ns: int) -> dict | None:
        for g in self.gaps:
            if g['start_ns'] <= ns and (g['end_ns'] is None or ns <= g['end_ns']):
                return g
        return None

    # ── books ─────────────────────────────────────────────────────────────────

    def on_quote(self, q) -> None:
        self.quotes.add(q.occ, q.event_ns, q)
        self._advance(q.event_ns)

    def on_spot(self, s) -> None:
        self.spots.add(s.symbol, s.event_ns, s.price)
        self._advance(s.event_ns)

    def _advance(self, ns: int) -> None:
        if ns > self.watermark:
            self.watermark = ns
            for u, sess, win in self.grouper.flush(ns):
                self._packages(u, sess, win)
            self._outcomes(ns)

    # ── prints ────────────────────────────────────────────────────────────────

    def on_trade(self, t) -> None:
        info = self.contracts.get(t.occ)
        parsed = events.parse_occ(t.occ)
        if info is None and parsed:
            info = {'underlying': parsed[0], 'expiry': parsed[1].isoformat(), 'right': parsed[2],
                    'strike': parsed[3], 'multiplier': None, 'adjusted': None}
        if info is None:
            self.stats['unparsable'] += 1
            return
        # Alpaca prints carry no trade id/sequence: identical prints at the same nanosecond on the same
        # venue are routinely DISTINCT fills (auction allocations, sweeps). So a print is a duplicate only
        # when a BACKFILL copy re-delivers one the STREAM already gave us — matched with multiplicity.
        k = t.key
        if t.source == 'backfill':
            self.seen_bf[k] += 1
            if self.seen_bf[k] <= self.seen_stream[k]:
                self.stats['duplicate'] += 1
                return
        else:
            self.seen_stream[k] += 1
            if self.seen_stream[k] <= self.seen_bf[k]:
                self.stats['duplicate'] += 1          # backfill got there first; the stream copy is the dup
                return
        n = self.seen_stream[k] + self.seen_bf[k]
        t.dup_index = n                               # distinguishes identical simultaneous fills in the DB
        tg = t.tags
        if conditions.is_cancel(tg):
            self._cancel(t, info)
            return
        out_of_order = t.source == 'stream' and t.event_ns < self.last_ns.get(t.occ, 0)
        self.last_ns[t.occ] = max(self.last_ns.get(t.occ, 0), t.event_ns)
        gap = self._in_gap(t.event_ns)
        side = classify(t, self.quotes.at(t.occ, t.event_ns), quote_covered=(gap is None))
        if gap is not None:
            self.context_only.setdefault(t.occ, 'print inside a feed gap (quotes not recoverable)')
        sp = spot_at(self.spots, info['underlying'], t.event_ns)
        mech = []
        sweep_keys = self.sweeps.add(t)
        if sweep_keys:
            mech.append('RAPID_SWEEP_CANDIDATE')
            for sk in sweep_keys:
                self.store.x("UPDATE prints SET mech=CASE WHEN mech LIKE '%RAPID_SWEEP%' THEN mech ELSE "
                             "TRIM(COALESCE(mech,'')||' RAPID_SWEEP_CANDIDATE') END WHERE key=?", (sk,))
        med = self.base.series_median(t.occ)
        if t.size >= settings.BLOCK_MIN and med['value'] is not None and t.size >= settings.BLOCK_REL * max(med['value'], 1):
            mech.append('RELATIVE_BLOCK_CANDIDATE')
        if side['side'] == UNKNOWN:
            mech.append('NO_SIDE')
        rec = self._store_print(t, info, status='COUNTED', side=side, spot=sp, mech=mech, late='LATE' in tg,
                                out_of_order=out_of_order)
        self.stats['counted'] += 1
        s = self.series[t.occ]
        p = _P(rec['key'], t.size, t.price, side['side'], t.exchange, t.event_ns,
               t.price * t.size * (info.get('multiplier') or 100), sp.get('spot'),
               conditions.side_eligible(tg), 'STOCK_TIED' in tg)
        s['prints'].append(p)
        self._agg_add(s, p, info, med)
        self._evaluate(t.occ, info, at_ns=t.event_ns, reason='PRINT')
        self._watch_hit(t, info, rec)
        # package windows run in event time behind a watermark
        self._advance(t.event_ns)
        for u, sess, win in self.grouper.add({**rec, 'tags': tg, 'multiplier': info.get('multiplier')},
                                             self.watermark):
            self._packages(u, sess, win)

    def _store_print(self, t, info, *, status, side, spot=None, mech=(), late=False, out_of_order=False) -> dict:
        prov = events.provenance(t.event_ns)
        key = t.key + (f"#{t.dup_index}" if getattr(t, 'dup_index', 1) > 1 else '')
        rec = {'key': key, 'slot': t.slot, 'occ': t.occ, 'underlying': info['underlying'],
               'expiry': info['expiry'], 'right': info['right'], 'strike': info['strike'], 'price': t.price,
               'size': t.size, 'exchange': t.exchange, 'cond': t.cond, 'event_ns': t.event_ns,
               'recv_ns': t.recv_ns, 'source': t.source, 'session': prov['session'], 'status': status,
               'side': side['side'], 'side_reason': side.get('reason'), 'mech': ' '.join(mech)
               + (' OUT_OF_ORDER' if out_of_order else '')}
        self.store.x("INSERT OR IGNORE INTO prints VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            key, t.slot, t.occ, info['underlying'], info['expiry'], info['right'], info['strike'], t.price,
            t.size, t.exchange, t.cond, ','.join(sorted(t.tags)), t.event_ns, t.recv_ns, t.source,
            prov['session'], status, None, side['side'], side.get('reason'), side.get('bid'), side.get('ask'),
            side.get('age_ms'), (spot or {}).get('spot'), (spot or {}).get('age_ms'), rec['mech'].strip(),
            int(late), events.checksum(t.payload), prov['parser_version'], prov['cond_map_version'],
            prov['rule_version']))
        return rec

    def _cancel(self, t, info) -> None:
        """A cancel never deletes: it marks the most recent matching COUNTED original CANCELLED and is
        stored as a CANCEL_RECORD (both kept, never both counted). Affected state is recomputed."""
        s = self.series[t.occ]
        target = None
        for p in reversed(s['prints']):
            if (p.counted and p.exchange == t.exchange and p.price == t.price and p.size == t.size
                    and p.event_ns <= t.event_ns):
                target = p
                break
        self._store_print(t, info, status='CANCEL_RECORD' if target else 'UNMATCHED_CANCEL',
                          side={'side': UNKNOWN, 'reason': 'cancel_record'})
        if not target:
            self.stats['unmatched_cancel'] += 1
            self.store.incident('UNMATCHED_CANCEL', t.occ, t.event_ns, t.event_ns, {'key': t.key}, 'NONE',
                                self.session.isoformat())
            return
        target.counted = False
        self.store.x("UPDATE prints SET status='CANCELLED', cancelled_by=? WHERE key=?", (t.key, target.key))
        self.stats['cancelled'] += 1
        # corrections are the one case where earned screens are re-derived from scratch
        s['agg'] = None
        s['earned'] = {}
        med = self.base.series_median(t.occ)
        for p in s['prints']:
            if p.counted:
                self._agg_add(s, p, info, med)
        self._evaluate(t.occ, info, at_ns=self.watermark, reason='CORRECTION')

    # ── screens + observation ─────────────────────────────────────────────────

    @staticmethod
    def _agg_add(s, p, info, med) -> None:
        """Running per-series totals — O(1) per print (a full rebuild happens only on a correction)."""
        a = s.get('agg')
        if a is None:
            a = s['agg'] = {'cum': 0, 'buy': 0, 'sell': 0, 'n': 0, 'ord_n': 0, 'ord_qty': 0, 'best_prem': 0.0,
                            'meaningful': 0, 'otm': False, 'spot_any': False, 'stock_tied': False, 'last_price': None}
        a['cum'] += p.size
        a['n'] += 1
        if p.side == BUY:
            a['buy'] += p.size
        elif p.side == SELL:
            a['sell'] += p.size
        if p.ordinary:
            a['ord_n'] += 1
            a['ord_qty'] += p.size
        a['best_prem'] = max(a['best_prem'], p.premium)
        if med['value'] is not None and p.size >= max(settings.REPEAT_MIN_QTY, settings.REPEAT_MED_FRAC * med['value']):
            a['meaningful'] += 1
        if p.spot is not None:
            a['spot_any'] = True
            if (info['right'] == 'C' and info['strike'] > p.spot) or (info['right'] == 'P' and info['strike'] < p.spot):
                a['otm'] = True
        a['stock_tied'] = a['stock_tied'] or p.stock_tied
        a['last_price'] = p.price

    def _screens(self, occ, info, at_ns):
        a = self.series[occ].get('agg') or {'cum': 0, 'buy': 0, 'sell': 0, 'n': 0, 'ord_n': 0, 'ord_qty': 0,
                                            'best_prem': 0.0, 'meaningful': 0, 'otm': False, 'spot_any': False,
                                            'stock_tied': False, 'last_price': None}
        cum = a['cum']
        med = self.base.series_median(occ)
        prem = self.base.name_premium(info['underlying'])
        oi = self.base.prior_oi(occ, at_ns=at_ns)
        missing, passed = {}, {}
        if med['value'] is None:
            missing['series_median'] = med['status'] + (f": {med['reason']}" if med.get('reason') else '')
        elif cum >= settings.REL_VOL_MULT * max(med['value'], 1.0):
            passed['REL_VOLUME'] = round(cum / max(med['value'], 1.0), 1)
        if prem['value'] is None:
            missing['name_premium'] = prem['status']
        elif a['best_prem'] >= settings.REL_PREM_MULT * prem['value']:
            passed['REL_PREMIUM'] = round(a['best_prem'] / prem['value'], 1)
        if oi['value'] is None:
            missing['prior_oi'] = oi['status']
        elif cum > oi['value']:
            passed['VOL_GT_OI'] = oi['value']
        if a['buy'] or a['sell']:
            passed['QUOTE_SIDE'] = True
        dte = channels.dte_ny(info['expiry'], events.ny_dt(at_ns))
        if dte is not None and 0 <= dte <= settings.OTM_MAX_DTE:
            if a['otm']:
                passed['SHORT_DATED_OTM'] = True
            elif not a['spot_any']:
                missing['spot'] = 'no spot ≤5s at or before any print'
        if med['value'] is not None and a['meaningful'] >= settings.REPEAT_MIN_PRINTS:
            passed['REPEATED'] = True
        return a, cum, med, prem, oi, dte, passed, missing

    def _evaluate(self, occ, info, *, at_ns, reason) -> None:
        s = self.series[occ]
        a, cum, med, prem, oi, dte, passed, missing = self._screens(occ, info, at_ns)
        for k, v in passed.items():
            s['earned'].setdefault(k, {'at_ns': at_ns, 'value': v})     # earned screens are sticky
        earned = set(s['earned'])
        candidate = len(earned) >= 2 and bool(earned & {'REL_VOLUME', 'REL_PREMIUM'})
        if not candidate and s['obs'] is None:
            return
        captured = cum or 1
        buy, sell = a['buy'], a['sell']
        unk = cum - buy - sell
        ctx = self.context_only.get(occ)
        gate = self._leading_read(candidate, ctx, a, oi, bool(s.get('pkg_ids')))
        thesis = None
        if gate['pass']:
            thesis = {'state': 'WORKING_HYPOTHESIS', 'side': gate['side'], **cards.thesis_text(info['right'], gate['side'])}
            if info['right'] == 'C' and gate['side'] == BUY and a['last_price'] is not None:
                bb = oi_mod.buyback_alternative(self.store, occ, 'C', self.session.isoformat(), BUY, a['last_price'])
                if bb:
                    thesis['extra_alternative'] = bb['text']
        q = self.quotes.at(occ, at_ns)
        execu = None
        if q:
            qq = q[1]
            execu = {'bid': qq.bid, 'ask': qq.ask, 'bid_size': qq.bid_size, 'ask_size': qq.ask_size,
                     'age_ms': round((at_ns - q[0]) / 1e6, 1),
                     'width': round((qq.ask - qq.bid) / (0.5 * (qq.ask + qq.bid)), 3) if qq.ask > 0 and qq.bid > 0 else None}
        cat = catalyst_mod.assess(info['underlying'], events.ny_dt(at_ns), info['expiry'], rows=self.catalyst_rows)
        dims = {
            'occ': occ, 'underlying': info['underlying'], 'expiry': info['expiry'], 'right': info['right'],
            'strike': info['strike'],
            'rarity': {'screens': {k: v['value'] for k, v in sorted(s['earned'].items())}, 'candidate': candidate,
                       'missing': missing, 'universe': self.universe_size},
            'linkage': sorted(s.get('pkg_ids') or []),
            'side_thesis': thesis or {'state': 'NEUTRAL'},
            'side_mix': {'captured': cum, 'buy': buy, 'sell': sell, 'unknown': unk,
                         'buy_share': round(buy / captured, 3), 'sell_share': round(sell / captured, 3),
                         'unknown_share': round(unk / captured, 3), 'prints': a['n'],
                         'ordinary_prints': a['ord_n'], 'ordinary_qty': a['ord_qty']},
            'baseline': {'median': med['value'], 'median_n': med.get('n'), 'prior_oi': oi['value'],
                         'oi_as_of': oi.get('as_of'), 'name_p95': prem['value']},
            'event': {'status': cat['status'], 'sentence': cat['sentence'], 'mismatch': cat['mismatch']},
            'urgency': {'dte': dte, 'channel': channels.dte_bucket(dte)},
            'executability': execu,
            'coverage': {'context_only': bool(ctx), 'reason': ctx},
            'revisions': list((s['obs'] or {}).get('dims', {}).get('revisions', [])),
            'oi_annotation': (s['obs'] or {}).get('dims', {}).get('oi_annotation'),
            'leading_read_fail': gate['fails'],
        }
        if s['obs'] and s['obs']['dims']['rarity']['candidate'] and not candidate:
            dims['revisions'].append({'kind': 'INVALIDATED', 'at_ns': at_ns, 'reason': reason})
        prev_state = (s['obs'] or {}).get('dims', {}).get('side_thesis', {}).get('state')
        if prev_state == 'WORKING_HYPOTHESIS' and not thesis:
            dims['revisions'].append({'kind': 'THESIS_WEAKENED', 'at_ns': at_ns,
                                      'reason': ','.join(gate['fails']) or reason})
        self._version(occ, info, dims, at_ns, reason)

    def _leading_read(self, candidate, ctx, a, oi, in_pkg) -> dict:
        """Provisional leading-read gate (§6). The side evidence must come from ORDINARY ELECTRONIC prints
        (≥ LR_MIN_PRINTS of them, ≥ LR_MIN_QTY contracts); every other print counts as unknown-side volume,
        which may be at most LR_MAX_UNKNOWN of everything captured."""
        cum, buy, sell = a['cum'], a['buy'], a['sell']
        unk = cum - buy - sell
        fails = []
        if not candidate:
            fails.append('not_uoa_candidate')
        if ctx:
            fails.append('feed_not_healthy')
        if a['ord_n'] < settings.LR_MIN_PRINTS:
            fails.append('too_few_ordinary_prints')
        if a['ord_qty'] < settings.LR_MIN_QTY:
            fails.append('too_few_contracts')
        if oi['value'] is None:
            fails.append('prior_oi_missing')
        elif cum <= settings.LR_OI_MULT * oi['value']:
            fails.append('volume_not_3x_oi')
        side = BUY if buy >= sell else SELL
        if not cum or max(buy, sell) / cum < settings.LR_SIDE_SHARE:
            fails.append('no_dominant_side')
        if cum and unk / cum > settings.LR_MAX_UNKNOWN:
            fails.append('too_much_unknown_side')
        if in_pkg:
            fails.append('suspected_package')
        if a['stock_tied']:
            fails.append('stock_tied')
        return {'pass': not fails, 'side': side, 'fails': fails}

    def _material(self, dims) -> dict:
        """The part of the dimensions whose change is a NEW VERSION (facts like cum volume are not)."""
        return {'screens': sorted(dims['rarity']['screens']), 'candidate': dims['rarity']['candidate'],
                'linkage': dims['linkage'], 'thesis': dims['side_thesis'].get('state'),
                'thesis_side': dims['side_thesis'].get('side'), 'context_only': dims['coverage']['context_only'],
                'revisions': [r['kind'] for r in dims['revisions']], 'oi': dims.get('oi_annotation')}

    def _version(self, occ, info, dims, at_ns, reason) -> None:
        s = self.series[occ]
        obs = s['obs']
        mat = self._material(dims)
        if obs is None:
            obs_id = _h([occ, self.session.isoformat()])
            camp = self._campaign(info, dims, obs_id, at_ns)
            obs = s['obs'] = {'obs_id': obs_id, 'version': 0, 'campaign_id': camp, 'material': None, 'dims': dims}
            self.store.x("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?,?)",
                         (obs_id, occ, self.session.isoformat(), 0, camp, json.dumps(dims, default=str), at_ns, at_ns))
            self._schedule_outcomes(obs_id, occ, info, at_ns)
        obs['dims'] = dims
        if mat == obs['material']:
            self.store.x("UPDATE observations SET dims=?, updated_ns=? WHERE obs_id=?",
                         (json.dumps(dims, default=str), at_ns, obs['obs_id']))
            return
        prev = obs['material']
        obs['material'] = mat
        obs['version'] += 1
        ev_hash = _h(dims)
        self.store.x("INSERT OR REPLACE INTO observation_versions VALUES (?,?,?,?,?,?)",
                     (obs['obs_id'], obs['version'], at_ns, json.dumps(dims, default=str), ev_hash, reason))
        self.store.x("UPDATE observations SET version=?, dims=?, updated_ns=? WHERE obs_id=?",
                     (obs['version'], json.dumps(dims, default=str), at_ns, obs['obs_id']))
        kind = self._card_kind(prev, mat)
        if kind:
            self._post(cards.observation(obs, kind, at_ns), campaign=obs['campaign_id'], kind=kind)

    @staticmethod
    def _card_kind(prev, mat):
        if prev is None:
            return 'NEW_OBSERVATION' if mat['candidate'] else None
        if len(mat['revisions']) > len(prev['revisions']):
            return mat['revisions'][-1]                      # INVALIDATED / THESIS_WEAKENED / … (material)
        if mat['thesis'] == 'WORKING_HYPOTHESIS' and (prev['thesis'] != 'WORKING_HYPOTHESIS'
                                                      or prev['thesis_side'] != mat['thesis_side']):
            return 'WORKING_HYPOTHESIS'
        if mat['linkage'] != prev['linkage']:
            return 'CONVEXITY_CONTEXT_CHANGED'
        if mat['oi'] != prev['oi'] and mat['oi']:
            return 'OI_ANNOTATION'
        if mat['context_only'] and not prev['context_only']:
            return 'DEGRADED'
        if not prev['candidate'] and mat['candidate']:
            return 'NEW_OBSERVATION'
        return None                                          # screen growth etc.: new version, no post

    # ── campaigns ─────────────────────────────────────────────────────────────

    def _campaign(self, info, dims, obs_id, at_ns) -> str:
        mix = dims['side_mix']
        direction = ('BUY_SIDE' if mix['buy_share'] >= settings.LR_SIDE_SHARE else
                     'SELL_SIDE' if mix['sell_share'] >= settings.LR_SIDE_SHARE else 'MIXED')
        key = [info['underlying'], info['expiry'], info['right'], direction]
        rows = self.store.q("SELECT campaign_id, events FROM campaigns WHERE underlying=? AND expiry=? AND right=? "
                            "AND direction=? AND state IN ('OPEN','WEAKENED')", tuple(key))
        if rows:
            cid, evs = rows[0]
            evs = json.loads(evs or '[]') + [obs_id]
            self.store.x("UPDATE campaigns SET last_session=?, events=? WHERE campaign_id=?",
                         (self.session.isoformat(), json.dumps(evs), cid))
            return cid
        cid = _h(key + [self.session.isoformat(), at_ns])
        self.store.x("INSERT INTO campaigns VALUES (?,?,?,?,?,?,?,?,?)",
                     (cid, info['underlying'], info['expiry'], info['right'], direction, 'OPEN',
                      self.session.isoformat(), self.session.isoformat(), json.dumps([obs_id])))
        return cid

    # ── packages ──────────────────────────────────────────────────────────────

    def _packages(self, underlying, session, win) -> None:
        live = [p for p in win if p.get('status') == 'COUNTED' and not p.get('late_for_package')]
        assigned = {r[0] for r in self.store.q(
            "SELECT print_key FROM package_prints WHERE print_key IN (%s)" % ','.join('?' * len(live)),
            tuple(p['key'] for p in live))} if live else set()
        live = [p for p in live if p['key'] not in assigned]           # one print, one package
        for pkg in packages.group_window(underlying, session, live):
            self.store.x("INSERT OR IGNORE INTO packages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                pkg['pkg_id'], underlying, session, pkg['start_ns'], pkg['end_ns'],
                json.dumps(pkg['legs'], default=str), pkg['ratio'], pkg['geometry'], pkg['association'],
                pkg['side_text'], pkg['conditional_cashflow'], json.dumps(pkg['competing']), pkg['status'],
                pkg['rule_version']))
            if pkg['status'] != 'CANDIDATE':
                self.stats['package_abstain'] += 1
                continue
            self.stats['packages'] += 1
            for leg in pkg['legs']:
                for k in leg['print_keys']:
                    self.store.x("INSERT OR IGNORE INTO package_prints VALUES (?,?,?)", (k, pkg['pkg_id'], 1))
            card = cards.package(pkg, self.catalyst_rows)
            if pkg['association'][0] > settings.PKG_POST_MIN_GRADE:
                card['suppressed'] = f"association {pkg['association']} below post grade"   # stored, not posted
            self._post(card, campaign=pkg['pkg_id'], kind='PACKAGE')
            for leg in pkg['legs']:                                     # later sibling leg → earlier signal revised
                s = self.series[leg['occ']]
                s.setdefault('pkg_ids', set()).add(pkg['pkg_id'])
                if s['obs'] is not None:
                    info = self.contracts.get(leg['occ']) or {'underlying': underlying, 'expiry': leg['expiry'],
                                                              'right': leg['right'], 'strike': leg['strike']}
                    self._evaluate(leg['occ'], info, at_ns=pkg['end_ns'], reason=f"package {pkg['pkg_id']}")

    # ── watches (private) ─────────────────────────────────────────────────────

    def _watch_hit(self, t, info, rec) -> None:
        for wid in self.watch_legs.get(t.occ, []):
            k = f"watch|{wid}|{t.occ}"
            last = self._campaign_last_post.get(k, 0)
            if t.event_ns - last < settings.CAMPAIGN_COOLDOWN_S * 1e9:
                continue
            self._campaign_last_post[k] = t.event_ns
            self._emit(cards.watched_activity(wid, rec), private=True)

    # ── outcomes (research ledger, precommitted) ──────────────────────────────

    def _schedule_outcomes(self, obs_id, occ, info, at_ns) -> None:
        q = self.quotes.at(occ, at_ns)
        sp = spot_at(self.spots, info['underlying'], at_ns)
        for h in settings.OUTCOME_HORIZONS_MIN:
            self.pending_outcomes.append({'obs_id': obs_id, 'occ': occ, 'h': h, 'due_ns': at_ns + h * 60 * 10**9,
                                          'entry_ask': q[1].ask if q and q[1].ask > 0 else None,
                                          'entry_age_ms': (at_ns - q[0]) / 1e6 if q else None,
                                          'spot0': sp.get('spot'), 'und': info['underlying'],
                                          'mult': info.get('multiplier') or 100})

    def _outcomes(self, now_ns) -> None:
        if not self.pending_outcomes:
            return
        keep = []
        for o in self.pending_outcomes:
            if o['due_ns'] > now_ns:
                keep.append(o)
                continue
            q = self.quotes.at(o['occ'], o['due_ns'])
            sp = spot_at(self.spots, o['und'], o['due_ns'])
            fresh = q and (o['due_ns'] - q[0]) / 1e6 <= 60_000
            if o['entry_ask'] is None or o['entry_age_ms'] is None or o['entry_age_ms'] > settings.QUOTE_MAX_AGE_MS:
                status, net, xb = 'NO_ENTRY_QUOTE', None, None
            elif not fresh or not q[1].bid:
                status, net, xb = 'NO_EXIT_QUOTE', None, None
            else:
                xb = q[1].bid
                net = round((xb - o['entry_ask']) * o['mult'] - 2 * settings.FEE_PER_CONTRACT, 2)
                status = 'OK'
            move = (round(sp['spot'] / o['spot0'] - 1, 5) if sp.get('spot') and o['spot0'] else None)
            self.store.x("INSERT OR REPLACE INTO outcomes VALUES (?,?,?,?,?,?,?,?)",
                         (o['obs_id'], o['h'], o['entry_ask'], xb, net, move, status,
                          'long the observed contract: buy ask at observation, sell bid at horizon, fees both sides'))
        self.pending_outcomes = keep

    # ── OI annotation (next session) ──────────────────────────────────────────

    def annotate_prior_sessions(self) -> int:
        """Attach the aggregate OI annotation to earlier observations whose session now has a published
        vintage. 0DTE observations never get one (no next-session OI before expiry)."""
        n = 0
        rows = self.store.q("SELECT obs_id, occ, session, version, dims FROM observations WHERE session<?",
                            (self.session.isoformat(),))
        for obs_id, occ, sess, ver, dims_s in rows:
            dims = json.loads(dims_s)
            if dims.get('oi_annotation'):
                continue
            if dims['urgency']['dte'] == 0:
                dims['oi_annotation'] = {'label': 'NO_OI_CONFIRMATION_0DTE'}
            else:
                prior = self.store.q("SELECT MAX(oi_date) FROM oi_vintages WHERE occ=? AND oi_date<?", (occ, sess))[0][0]
                if not prior or not self.store.q("SELECT 1 FROM oi_vintages WHERE occ=? AND oi_date=?", (occ, sess)):
                    continue
                rec = oi_mod.interval(self.store, occ, prior, sess)
                if rec['label'] == 'INCONCLUSIVE':
                    continue
                dims['oi_annotation'] = {k: rec.get(k) for k in ('label', 'delta', 'volume', 'bounds', 'rule_version')}
            ver += 1
            self.store.x("UPDATE observations SET version=?, dims=? WHERE obs_id=?",
                         (ver, json.dumps(dims, default=str), obs_id))
            self.store.x("INSERT OR REPLACE INTO observation_versions VALUES (?,?,?,?,?,?)",
                         (obs_id, ver, 0, json.dumps(dims, default=str), _h(dims), 'OI_ANNOTATION'))
            if dims['oi_annotation']['label'] != 'NO_OI_CONFIRMATION_0DTE':
                self._post(cards.observation({'obs_id': obs_id, 'version': ver, 'dims': dims}, 'OI_ANNOTATION', 0),
                           campaign=obs_id, kind='OI_ANNOTATION')
            n += 1
        return n

    # ── delivery ──────────────────────────────────────────────────────────────

    def _post(self, card: dict, *, campaign: str, kind: str) -> None:
        """Rate-limit routine repeats per campaign; material updates bypass the cooldown."""
        routine = kind in ('NEW_OBSERVATION', 'PACKAGE')
        ts = card.get('at_ns') or self.watermark
        if routine:
            last = self._campaign_last_post.get(campaign)
            if last is not None and ts - last < settings.CAMPAIGN_COOLDOWN_S * 1e9 and kind == 'NEW_OBSERVATION':
                self.stats['suppressed_routine'] += 1
                card['suppressed'] = 'campaign cooldown'
            self._campaign_last_post[campaign] = ts
        self._emit(card)

    def _emit(self, card: dict, private: bool = False) -> None:
        card['private'] = private
        self.store.x("INSERT OR IGNORE INTO cards VALUES (?,?,?,?,?,?,?,?)",
                     (card['signal_id'], card['version'], card['channel'], json.dumps(card['payload'], default=str),
                      card['evidence_hash'], card.get('at_ns') or 0, None, card['kind']))
        self.stats['cards'] += 1
        if not card.get('suppressed'):
            try:
                self.emit(card)
            except Exception:
                logger.warning("card emit failed (stored; not lost)", exc_info=True)

    def finish(self) -> None:
        for u, sess, win in self.grouper.flush(self.watermark, force=True):
            self._packages(u, sess, win)
        self.store.flush()
