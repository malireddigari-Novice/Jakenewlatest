"""Live adapter: turns the engine's own Alpaca polls + reference fetches into recorded observations and feeds the
campaign-flow pipeline. The legacy policy and this policy therefore see the IDENTICAL time-stamped polls.

Recorded to `cf_obs/<session>.jsonl` (append-only). After a restart the session log is replayed in rebuild
mode (memory only; no decisions, orders or cards), so windows/clusters survive and nothing is duplicated.

Reference jobs (New York times, actual calendar):
  from 09:00 until the open  fetch the contract master (OI + oi date) for each ticker's nearest expirations,
                             prior-session 1-min bars (value references, baselines, previous-session volume)
  cutoff (open - 10 min) .. open   freeze the nearest-expiration OI chain once per ticker (a job that first runs
                             after the open records the context as MISSING; it is never backfilled)
  open + 60 s                pin the official regular-session open (first SIP 1-min bar) and the prior close
"""
import json
import logging
import os
import time
from datetime import date, datetime, timedelta

import pytz

from campaign_flow import calendar_ny as cal
from campaign_flow import settings as S
from campaign_flow.executor import AlpacaPaperBroker, SimBroker
from campaign_flow.journal import Journal
from campaign_flow.model import contract as mkcontract
from campaign_flow.model import series_key
from campaign_flow.pipeline import Pipeline

logger = logging.getLogger(__name__)

_DATA = 'https://data.alpaca.markets'
_PAPER = 'https://paper-api.alpaca.markets'


def _epoch(iso):
    if not iso:
        return None
    s = str(iso).replace('Z', '+00:00')
    if '.' in s:                                   # trim nanoseconds to microseconds
        head, frac = s.split('.', 1)
        tz = ''
        for sep in ('+', '-'):
            if sep in frac:
                frac, tz = frac.split(sep, 1)
                tz = sep + tz
                break
        s = f"{head}.{frac[:6]}{tz}"
    return datetime.fromisoformat(s).timestamp()


def add_held(t: str, held, contracts: dict) -> None:
    """Merge quotes for held contracts outside the polled band into a poll's contracts, marked held_only (the
    pipeline uses them to manage the position, never as flow). A contract already in the poll is left alone."""
    for (exp, strike, side), q in (held or {}).items():
        right = 'C' if side == 'CALL' else 'P'
        con = mkcontract(t, right, strike, exp)
        if con['occ'] in contracts:
            continue
        contracts[con['occ']] = {
            'right': right, 'strike': float(strike), 'expiry': exp, 'bid': q.get('bid'), 'ask': q.get('ask'),
            'bid_size': q.get('bid_size'), 'ask_size': q.get('ask_size'), 'quote_ts': _epoch(q.get('quote_ts')),
            'cum_volume': q.get('volume'), 'held_only': True}


class Runner:

    def __init__(self, data_client, exec_client=None, journal_path=None, obs_dir=None) -> None:
        self.data = data_client
        mode = S.MODE
        if mode == 'PAPER':
            import config
            if not (exec_client and config.ALPACA_ENABLED and config.ALPACA_PAPER):
                logger.error("CF_MODE=PAPER needs ALPACA_ENABLED=true and ALPACA_PAPER=true — running SHADOW")
                mode = 'SHADOW'
        self.mode = mode
        self.j = Journal(journal_path)
        broker = AlpacaPaperBroker(exec_client) if mode == 'PAPER' else SimBroker()
        self.pipe = Pipeline(self.j, broker, publish=self._publish)
        self.sheet = None
        if mode == 'PAPER' and S.DISCORD_ENABLED:          # the alerts sheet mirrors what was published
            from campaign_flow import alerts_sheet
            self.sheet = alerts_sheet.start(self.j.path)
        self.obs_dir = obs_dir or S.OBS_DIR
        self.session = None
        self._contracts = {}           # ticker -> [contract-master rows] for this session
        self._loaded = set()           # series whose prior-session bars were fetched this session
        self._listing_sig = {}
        self._frozen = set()
        self._opened = set()
        self._fh = None
        self.polls = 0                 # live polls handed to the pipeline this process (EOD summary)
        logger.info("CAMPAIGN-FLOW %s  rules=%s  journal=%s", mode, S.RULE_VERSION, self.j.path)

    # ── observation log ────────────────────────────────────────────────────────
    def _path(self, session):
        return os.path.join(self.obs_dir, f"{session}.jsonl")

    def _start_session(self, session: str) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None
        self.session = session
        self._contracts.clear(); self._loaded.clear(); self._listing_sig.clear()
        self._frozen.clear(); self._opened.clear()
        p = self._path(session)
        if os.path.exists(p):                      # restart: rebuild memory from the session log
            n = 0
            self.pipe.rebuilding = True
            try:
                with open(p, encoding='utf-8') as fh:
                    for line in fh:
                        try:
                            ob = json.loads(line)
                        except ValueError:
                            continue               # a torn last line from a crash
                        self.pipe.feed(ob)
                        n += 1
                        if ob['kind'] == 'freeze':
                            self._frozen.add(ob['ticker'])
                        elif ob['kind'] == 'opening':
                            self._opened.add(ob['record']['ticker'])
                        elif ob['kind'] in ('value_refs', 'baseline'):
                            for row in ob.get('refs') or ob.get('rows') or []:
                                self._loaded.add(tuple(row[0]))
            finally:
                self.pipe.rebuilding = False
            logger.info("CAMPAIGN-FLOW rebuilt %d recorded observation(s) for %s", n, session)
        if S.RECORD_OBS:
            os.makedirs(self.obs_dir, exist_ok=True)
            self._fh = open(p, 'a', encoding='utf-8')

    def emit(self, ob: dict) -> None:
        if self._fh:
            self._fh.write(json.dumps(ob, default=str) + '\n')
            self._fh.flush()
        try:
            self.pipe.feed(ob)
        except Exception:
            logger.warning("CAMPAIGN-FLOW observation failed (%s)", ob.get('kind'), exc_info=True)

    def _publish(self, payload, card_id) -> None:
        import notify
        if notify.enqueue(payload, signal_id=card_id, state_version=S.RULE_VERSION):
            notify.flush()
        if self.sheet:
            self.sheet.kick()

    # ── REST helpers ───────────────────────────────────────────────────────────
    def _get(self, base, path, params):
        return self.data._get(base, path, params)

    def _contract_master(self, ticker, expiries) -> list:
        rows = []
        for e in expiries:
            page = None
            while True:
                params = {'underlying_symbols': ticker, 'expiration_date': e.isoformat(), 'limit': 1000,
                          'status': 'active'}
                if page:
                    params['page_token'] = page
                j = self._get(_PAPER, '/v2/options/contracts', params)
                if j is None:
                    return None                    # incomplete fetch → never claimed complete
                rows += j.get('option_contracts') or []
                page = j.get('next_page_token')
                if not page:
                    break
        return rows

    def _bars(self, occs, start_iso, end_iso) -> dict:
        out = {}
        for i in range(0, len(occs), 50):
            page = None
            while True:
                params = {'symbols': ','.join(occs[i:i + 50]), 'timeframe': '1Min', 'start': start_iso,
                          'end': end_iso, 'limit': 10000}
                if page:
                    params['page_token'] = page
                j = self._get(_DATA, '/v1beta1/options/bars', params)
                if not j:
                    break
                for k, v in (j.get('bars') or {}).items():
                    out.setdefault(k, []).extend(v)
                page = j.get('next_page_token')
                if not page:
                    break
        return out

    # ── reference jobs ─────────────────────────────────────────────────────────
    def tick(self, now: datetime) -> None:
        """Called every engine poll (also before the open). Runs the dated reference jobs once each."""
        ts = now.timestamp()
        d = cal.ny_day(ts)
        if not cal.is_trading_day(d):
            return
        if self.session != d.isoformat():
            self._start_session(d.isoformat())
        b = cal.bounds(d)
        if ts < b[0] - 30 * 60 or ts > b[1] + 300:
            return
        for t in S.UNIVERSE:
            try:
                if t not in self._contracts:
                    self._load_master(t, ts, d)
                if t not in self._frozen and ts >= cal.oi_cutoff(d):
                    self._frozen.add(t)
                    self.emit({'kind': 'freeze', 'ts': ts, 'ticker': t})
                if t not in self._opened and ts >= b[0] + 60:
                    self._pin_open(t, ts, d)
            except Exception:
                logger.warning("CAMPAIGN-FLOW reference job failed for %s", t, exc_info=True)

    def _load_master(self, t, ts, d):
        exps = [e for e in self.data.get_scan_expiries(t, 2) if e >= d][:2]
        rows = self._contract_master(t, exps) if exps else None
        self._contracts[t] = rows or []
        if not rows:
            self.j.log(ts, 'INCIDENT', {'kind': 'CONTRACT_MASTER_UNAVAILABLE', 'expiries': [str(e) for e in exps]}, ticker=t)
            return
        chain_rows = [{'expiry': r['expiration_date'], 'right': 'C' if r['type'] == 'call' else 'P',
                       'strike': float(r['strike_price']), 'oi': int(r['open_interest']) if r.get('open_interest') else None,
                       'oi_date': r.get('open_interest_date'), 'occ': r['symbol'],
                       'multiplier': int(float(r.get('multiplier') or 100)), 'root': r.get('root_symbol')}
                      for r in rows]
        both = {r['right'] for r in chain_rows} == {'C', 'P'}
        # complete = every page fetched, both rights present, ONE synchronized as-of date before the session
        # (a contract listed too recently to carry OI is kept with oi=None and can never be a level).
        dates = {r['oi_date'] for r in chain_rows if r['oi_date']}
        complete = both and len(dates) == 1 and min(dates) < d.isoformat()
        self.emit({'kind': 'chain', 'ts': ts, 'chain': {
            'ticker': t, 'session': d.isoformat(), 'rows': chain_rows, 'published_ts': ts, 'available_ts': ts,
            'source_id': 'alpaca-contracts-v2', 'complete': complete, 'both_sides': both,
            'oi_dates': sorted({r['oi_date'] for r in chain_rows if r['oi_date']})}})

    def _prior_bars(self, keys_occ, ts, d) -> None:
        """Value references, baselines and previous-session volume for series not loaded yet this session."""
        todo = [(k, o) for k, o in keys_occ if k not in self._loaded]
        if not todo:
            return
        for k, _ in todo:
            self._loaded.add(k)
        sessions, x = [], d
        for _ in range(max(1, S.VALUE_REF_SESSIONS)):
            x = cal.prev_trading_day(x)
            sessions.append(x)
        start = cal.bounds(sessions[-1])[0]
        end = cal.bounds(sessions[0])[1]
        iso = lambda e: datetime.fromtimestamp(e, tz=pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        bars = self._bars([o for _, o in todo], iso(start), iso(end))
        prev_o, prev_c = cal.bounds(sessions[0])
        refs, base, mem = [], [], []
        master = {r['symbol']: r for rows in self._contracts.values() for r in rows}
        from campaign_flow.pipeline import tod_bucket
        for k, o in todo:
            bl = bars.get(o) or []
            r = [{'series': list(k), 'ts': _epoch(b['t']) + 60, 'price': b['c'], 'basis': 'TRADE',
                  'source': 'ALPACA_1MIN_BAR_CLOSE'} for b in bl if b.get('c')]
            refs.append((list(k), r))
            prev = [b for b in bl if prev_o <= _epoch(b['t']) < prev_c]
            minutes = {'OPEN': 0, 'MID': 0, 'CLOSE': 0}
            vol = {'OPEN': 0, 'MID': 0, 'CLOSE': 0}
            m = prev_o
            while m < prev_c:
                minutes[tod_bucket(m)] += 1
                m += 60
            for b in prev:
                vol[tod_bucket(_epoch(b['t']))] += int(b.get('v') or 0)
            for bk in vol:
                if minutes[bk]:
                    base.append((list(k), bk, vol[bk] / minutes[bk] * (S.WINDOW_S / 60)))
            mr = master.get(o) or {}
            oi_cur = int(mr['open_interest']) if mr.get('open_interest') else None
            mem.append({'series': list(k), 'session': d.isoformat(), 'prev_volume': sum(int(b.get('v') or 0) for b in prev),
                        'prior_ref_premium': prev[-1]['c'] if prev else None, 'oi_current': oi_cur,
                        'oi_date': mr.get('open_interest_date'),
                        'oi_earlier': self.j.latest_oi(k, d.isoformat()), 'source': 'alpaca-bars+contracts',
                        'available_ts': ts})
        self.emit({'kind': 'value_refs', 'ts': ts, 'refs': refs})
        self.emit({'kind': 'baseline', 'ts': ts, 'rows': base})
        self.emit({'kind': 'turnover', 'ts': ts, 'records': [x for x in mem if x['oi_current'] is not None]})

    def _pin_open(self, t, ts, d):
        o, _ = cal.bounds(d)
        iso = datetime.fromtimestamp(o, tz=pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        j = self._get(_DATA, f'/v2/stocks/{t}/bars', {'timeframe': '1Min', 'start': iso, 'limit': 1, 'feed': 'sip'})
        bars = (j or {}).get('bars') or []
        if not bars or _epoch(bars[0]['t']) != o:
            return                                  # not available yet — retried next tick
        self._opened.add(t)
        self.emit({'kind': 'opening', 'ts': ts, 'record': {
            'ticker': t, 'session': d.isoformat(), 'price': float(bars[0]['o']), 'open_ts': o, 'available_ts': ts,
            'source': 'alpaca-sip-first-1min-bar-open'}})
        p = cal.prev_trading_day(d)
        j = self._get(_DATA, f'/v2/stocks/{t}/bars', {'timeframe': '1Day', 'start': p.isoformat(),
                                                      'end': p.isoformat(), 'feed': 'sip'})
        db = (j or {}).get('bars') or []
        if db:
            self.emit({'kind': 'prior_close', 'ts': ts, 'ticker': t, 'price': float(db[-1]['c']),
                       'session': p.isoformat()})

    # ── per-poll ───────────────────────────────────────────────────────────────
    @staticmethod
    def wants_next_expiry(expiry) -> bool:
        """Observe the next expiration too when the nearest one expires today (overnight carry)."""
        return S.OVERNIGHT_ENABLED and expiry == cal.ny_day(time.time())

    def held_contracts(self, t: str) -> list:
        """Contracts of `t` this policy holds (or is still buying), as [(expiry ISO, strike, 'CALL'|'PUT')].
        The engine fetches any of them that fall outside its spot band, so management always sees a live quote.
        Call on the thread that owns the journal (the engine main loop)."""
        out = []
        for c in self.j.campaigns(('ACTIVE', 'ENTRY_PENDING', 'PROPOSED')):
            if c['ticker'] == t and (c.get('held_qty') or c.get('outstanding_entry_qty')):
                k = c['contract']
                out.append((str(k['expiry']), float(k['strike']), 'CALL' if k['right'] == 'C' else 'PUT'))
        return sorted(set(out))

    def on_poll(self, now: datetime, t: str, spot: float, expiry, snaps: dict, legacy: dict = None,
                timing: dict = None, extra=None, held=None) -> None:
        """`timing` = the engine's per-ticker {poll_start_ts, fetch_start_ts, recv_ts, server_ts}. The observation
        (and every decision on it) is stamped at recv_ts — when ALL of this ticker's data had arrived. Without
        timing (an old caller) the cycle start is used and the poll is marked UNRECORDED. `extra` = [(expiry, snaps)] for further
        observed expirations (the next one, for overnight carry); they join the same poll observation.
        `held` = {(expiry ISO, strike, 'CALL'|'PUT'): quote} for held contracts outside the polled band; they are
        recorded with held_only=True and used only to manage the position (never as flow)."""
        ts = float(timing['recv_ts']) if timing and timing.get('recv_ts') else now.timestamp()
        self.polls += 1
        tm = {**(timing or {'poll_start_ts': now.timestamp()}),
              'basis': 'LOCAL_RECEIPT' if timing and timing.get('recv_ts') else 'UNRECORDED'}
        d = cal.ny_day(ts)
        if self.session != d.isoformat():
            self._start_session(d.isoformat())
        contracts, keys, exps = {}, [], []
        for e, sn in [(expiry, snaps)] + list(extra or []):
            exp = e.isoformat() if hasattr(e, 'isoformat') else str(e)
            exps.append(exp)
            for (strike, side), q in sn.items():
                right = 'C' if side == 'CALL' else 'P'
                con = mkcontract(t, right, strike, exp)
                contracts[con['occ']] = {
                    'right': right, 'strike': float(strike), 'expiry': exp, 'bid': q.get('bid'), 'ask': q.get('ask'),
                    'bid_size': q.get('bid_size'), 'ask_size': q.get('ask_size'), 'quote_ts': _epoch(q.get('quote_ts')),
                    'cum_volume': q.get('volume'), 'trade_px': q.get('trade_px'), 'trade_ts': _epoch(q.get('trade_ts')),
                    'trade_size': q.get('trade_size'), 'trade_cond': q.get('trade_cond'), 'iv': q.get('implied_vol')}
                keys.append((series_key(con), con['occ']))
            rows = [r for r in self._contracts.get(t) or [] if r['expiration_date'] == exp]
            if rows:
                band = S_band(spot)
                lst = {'C': sorted(float(r['strike_price']) for r in rows if r['type'] == 'call' and band[0] <= float(r['strike_price']) <= band[1]),
                       'P': sorted(float(r['strike_price']) for r in rows if r['type'] == 'put' and band[0] <= float(r['strike_price']) <= band[1])}
                sig = (lst['C'][:1], lst['C'][-1:], lst['P'][:1], lst['P'][-1:], len(lst['C']), len(lst['P']))
                if self._listing_sig.get((t, exp)) != sig:
                    self._listing_sig[(t, exp)] = sig
                    self.emit({'kind': 'listing', 'ts': ts, 'ticker': t, 'expiry': exp, **lst, 'band': list(band)})
        add_held(t, held, contracts)
        try:
            self._prior_bars(keys, ts, d)
        except Exception:
            logger.warning("CAMPAIGN-FLOW prior-bar fetch failed for %s", t, exc_info=True)
        self.emit({'kind': 'poll', 'ts': ts, 'ticker': t, 'spot': spot, 'expiries': exps, 'feed': 'opra',
                   'contracts': contracts, 'legacy': legacy or {}, 'timing': tm})


def S_band(spot):
    """The engine's snapshot strike band (get_option_snapshots: spot × (1 ± 1.5 × PREMIUM_BAND_PCT))."""
    import config
    b = config.PREMIUM_BAND_PCT * 1.5
    return round(spot * (1 - b), 2), round(spot * (1 + b), 2)
