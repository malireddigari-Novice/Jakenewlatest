"""
Tape-lane runtime: the bounded universe, the recorder (archive FIRST, then derive), the live collector
with reconnect + backfill, and replay (flow handoff §3, §10, §11).

Collector rules
  • one options connection (OPRA, msgpack) + one SIP stock connection for spot; explicit subscription
    lists with acknowledgements — a contract not acknowledged is a SUBSCRIPTION_FAILED incident;
  • every message is archived before it is processed; a full in-process queue is a BUFFER_OVERFLOW
    incident and forces a reconnect+backfill rather than silently dropping data;
  • disconnect / stale feed → `feed_down`; after resubscribe → `feed_up`; then REST backfill of TRADES
    for the gap (quotes cannot be backfilled), spot backfill, and `backfill_done` with completeness.
    Prints inside the gap keep side UNKNOWN and their contracts are context only for the session.
Replay reads the archive in arrival order through the same Pipeline into a fresh DB seeded with the
point-in-time baselines, so it reaches the same versioned state as the live run.
"""
import asyncio
import json
import logging
import os
import shutil
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta

import msgpack

import config
import notify
from data import exchange_calendar as xcal
from tape import baseline, events, settings
from tape.pipeline import Pipeline
from tape.store import Store

logger = logging.getLogger('tape')

OPRA_WS = 'wss://stream.data.alpaca.markets/v1beta1/opra'
SIP_WS = 'wss://stream.data.alpaca.markets/v2/sip'


def now_ns() -> int:
    return time.time_ns()


# ── universe ───────────────────────────────────────────────────────────────────

def build_universe(store, rest, session: date, watched=()) -> tuple:
    """Bounded subscription universe with an explicit denominator. Watched contracts first, then per
    underlying the nearest expiries/strikes, round-robin across names up to MAX_CONTRACTS.
    Persists the contract master and today's dated OI vintages. Returns (contracts, denominators)."""
    fetched_at = datetime.now(events.NY).isoformat()
    eligible, per = {}, {}
    for und in settings.UNIVERSE:
        tr = rest.last_stock_trade(und)
        if not tr:
            logger.warning("universe: no spot for %s — skipped (counted as uncovered)", und)
            continue
        spot = float(tr['p'])
        lo, hi = round(spot * (1 - settings.STRIKE_BAND_PCT), 2), round(spot * (1 + settings.STRIKE_BAND_PCT), 2)
        rows = rest.contracts(und, session.isoformat(), (session + timedelta(days=settings.MAX_DTE)).isoformat(), lo, hi)
        lst = []
        for c in rows:
            occ = c['symbol']
            info = {'underlying': c['underlying_symbol'], 'root': c.get('root_symbol'), 'expiry': c['expiration_date'],
                    'right': 'C' if c['type'] == 'call' else 'P', 'strike': float(c['strike_price']),
                    'multiplier': float(c.get('multiplier') or 100),
                    'adjusted': int(c.get('root_symbol') != c.get('underlying_symbol') or float(c.get('multiplier') or 100) != 100)}
            store.x("INSERT OR REPLACE INTO contracts VALUES (?,?,?,?,?,?,?,?,?)",
                    (occ, info['underlying'], info['root'], info['expiry'], info['right'], info['strike'],
                     info['multiplier'], info['adjusted'], fetched_at))
            if c.get('open_interest') is not None and c.get('open_interest_date'):
                store.x("INSERT OR IGNORE INTO oi_vintages VALUES (?,?,?,?)",
                        (occ, c['open_interest_date'], int(c['open_interest']), fetched_at))
            eligible[occ] = info
            lst.append((date.fromisoformat(info['expiry']), abs(info['strike'] - spot), occ))
        per[und] = [o for _, _, o in sorted(lst)]
    chosen = [o for o in watched if o in eligible]
    queues = {u: [o for o in v if o not in chosen] for u, v in per.items()}
    while len(chosen) < settings.MAX_CONTRACTS and any(queues.values()):
        for u in list(queues):
            if queues[u] and len(chosen) < settings.MAX_CONTRACTS:
                chosen.append(queues[u].pop(0))
    store.flush()
    contracts = {o: eligible[o] for o in chosen}
    denom = {'eligible': len(eligible), 'subscribed': len(contracts), 'names': len(per),
             'by_name': {u: sum(1 for o in contracts if contracts[o]['underlying'] == u) for u in per}}
    logger.info("UNIVERSE %s: subscribed %d of %d eligible contracts (cap %d) — %s", session, len(contracts),
                len(eligible), settings.MAX_CONTRACTS, denom['by_name'])
    return contracts, denom


def load_contracts(store, occs=None) -> dict:
    rows = store.q("SELECT occ, underlying, expiry, right, strike, multiplier, adjusted FROM contracts")
    out = {r[0]: {'underlying': r[1], 'expiry': r[2], 'right': r[3], 'strike': r[4], 'multiplier': r[5],
                  'adjusted': r[6]} for r in rows}
    return {o: out[o] for o in occs if o in out} if occs is not None else out


def load_watches(store) -> dict:
    legs = {}
    for wid, legs_s in store.q("SELECT watch_id, legs FROM watches WHERE active=1"):
        for l in json.loads(legs_s):
            legs.setdefault(l['occ'], []).append(wid)
    return legs


# ── recorder ───────────────────────────────────────────────────────────────────

class Recorder:
    """Archive the ORIGINAL message, then hand the archived record to the pipeline."""

    def __init__(self, store: Store, pipeline: Pipeline, session: date) -> None:
        self.store, self.pipe, self.session = store, pipeline, session.isoformat()

    def record(self, kind: str, norm, raw, source: str, recv_ns: int) -> None:
        payload = {'norm': norm if isinstance(norm, dict) else asdict(norm), 'raw': raw} if kind != 'status' else norm
        seq = self.store.archive(self.session, kind, recv_ns, source, payload, events.checksum(raw or norm))
        self.pipe.dispatch({'seq': seq, 'kind': kind, 'recv_ns': recv_ns, 'source': source, 'payload': payload})

    def status(self, event: str, **detail) -> None:
        self.record('status', {'event': event, **detail}, None, 'collector', now_ns())


def card_emitter(card: dict) -> None:
    """Deliver a stored card through the durable outbox when tape delivery is enabled."""
    if not settings.DISCORD_ENABLED:
        return
    alias = 'tape:private' if card.get('private') or card['channel'] == 'private' else f"tape:{card['channel']}"
    notify.enqueue(card['payload'], signal_id=f"tape|{card['signal_id']}", state_version=str(card['version']),
                   alias=alias)


def register_tape_webhooks() -> None:
    for b, url in settings.WEBHOOKS.items():
        notify.register_webhook(f'tape:{b}', url)
    notify.register_webhook('tape:private', settings.PRIVATE_WEBHOOK)


# ── live collector ─────────────────────────────────────────────────────────────

class Collector:

    def __init__(self, rec: Recorder, rest, contracts: dict, session: date) -> None:
        self.rec, self.rest, self.contracts, self.session = rec, rest, contracts, session
        self.q: asyncio.Queue = None
        self.last_msg = time.time()
        self.overflow = False
        self.gap_start = None
        self.spot_gap_start = None
        self.stop = False

    def _session_end(self) -> datetime:
        return xcal.session_bounds(self.session, events.NY)[1] + timedelta(minutes=5)

    async def run(self) -> None:
        import websockets
        self.q = asyncio.Queue(maxsize=settings.QUEUE_MAX)
        tasks = [asyncio.create_task(self._options(websockets)), asyncio.create_task(self._spot(websockets)),
                 asyncio.create_task(self._consume()), asyncio.create_task(self._flush_loop())]
        while datetime.now(events.NY) < self._session_end() and not self.stop:
            await asyncio.sleep(1)
        self.stop = True
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        while not self.q.empty():
            self._handle(*self.q.get_nowait())

    def _put(self, item) -> None:
        try:
            self.q.put_nowait(item)
        except asyncio.QueueFull:
            self.overflow = True               # the options loop sees this and forces reconnect + backfill

    async def _consume(self) -> None:
        while True:
            item = await self.q.get()
            try:
                self._handle(*item)
            except Exception:
                logger.exception("tape: event processing failed (archived; continuing)")

    def _handle(self, kind, msg, recv_ns) -> None:
        if kind == 'opt':
            t = msg.get('T')
            if t == 't':
                self.rec.record('trade', events.trade_from_stream(msg, recv_ns), msg, 'stream', recv_ns)
            elif t == 'q':
                self.rec.record('quote', events.quote_from_stream(msg, recv_ns), msg, 'stream', recv_ns)
        elif kind == 'spot':
            self.rec.record('spot', events.spot_from_sip(msg, recv_ns), msg, 'stream', recv_ns)
        elif kind == 'status':
            self.rec.record('status', dict(msg), None, 'collector', recv_ns)

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(2)
            self.rec.store.flush()
            await asyncio.to_thread(notify.flush)

    async def _options(self, websockets) -> None:
        occs = sorted(self.contracts)
        backoff = 1
        while not self.stop:
            try:
                async with websockets.connect(OPRA_WS, max_size=2 ** 24, ping_interval=20) as ws:
                    msgpack.unpackb(await ws.recv())
                    await ws.send(msgpack.packb({'action': 'auth', 'key': config.ALPACA_API_KEY,
                                                 'secret': config.ALPACA_SECRET_KEY}))
                    auth = msgpack.unpackb(await ws.recv())
                    if not any(m.get('T') == 'success' and m.get('msg') == 'authenticated' for m in auth):
                        raise RuntimeError(f"auth failed: {auth}")
                    acked_t, acked_q = set(), set()
                    for i in range(0, len(occs), 200):
                        await ws.send(msgpack.packb({'action': 'subscribe', 'trades': occs[i:i + 200],
                                                     'quotes': occs[i:i + 200]}))
                    deadline = time.time() + 10
                    while time.time() < deadline and (len(acked_t) < len(occs) or len(acked_q) < len(occs)):
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.time()))
                        except asyncio.TimeoutError:
                            break
                        for m in msgpack.unpackb(raw, timestamp=2):
                            if m.get('T') == 'subscription':
                                acked_t |= set(m.get('trades') or []); acked_q |= set(m.get('quotes') or [])
                            elif m.get('T') == 'error':
                                logger.error("tape: stream error %s", m)
                            else:
                                self._put(('opt', m, now_ns()))
                    missing = sorted(set(occs) - (acked_t & acked_q))
                    if missing:
                        self._put(('status', {'event': 'subscription_failed', 'contracts': missing,
                                              'scope': 'subscription', 'n': len(missing)}, now_ns()))
                    self._put(('status', {'event': 'feed_up', 'subscribed': len(occs) - len(missing)}, now_ns()))
                    backoff = 1
                    if self.gap_start is not None:
                        asyncio.create_task(self._backfill(self.gap_start, now_ns()))
                        self.gap_start = None
                    self.last_msg = time.time()
                    while not self.stop:
                        if self.overflow:
                            self.overflow = False
                            self._put(('status', {'event': 'buffer_overflow', 'scope': '*'}, now_ns()))
                            raise ConnectionError('buffer overflow — reconnect and backfill')
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=settings.STALE_S)
                        except asyncio.TimeoutError:
                            if xcal.session_bounds(self.session, events.NY)[0] <= datetime.now(events.NY):
                                raise ConnectionError('stale feed')
                            continue
                        recv = now_ns()
                        self.last_msg = time.time()
                        for m in msgpack.unpackb(raw, timestamp=2):
                            if m.get('T') == 'error':
                                logger.error("tape: stream error %s", m)
                                continue
                            self._put(('opt', m, recv))
            except asyncio.CancelledError:
                return
            except Exception as exc:
                if self.stop:
                    return
                if self.gap_start is None:
                    self.gap_start = now_ns()
                    self._put(('status', {'event': 'feed_down', 'reason': f"{type(exc).__name__}: {exc}"},
                               self.gap_start))
                logger.warning("tape: options feed down (%s) — reconnecting in %ss", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(settings.RECONNECT_MAX_S, backoff * 2)

    async def _backfill(self, gap_start_ns: int, gap_end_ns: int) -> None:
        """REST trades for the gap (+2s margin). Quotes are not recoverable. Dedupe is by print identity."""
        start = events.ns_to_iso(gap_start_ns - 2 * 10 ** 9)
        end = events.ns_to_iso(gap_end_ns + 2 * 10 ** 9)

        def fetch():
            rows = list(self.rest.option_trades(sorted(self.contracts), start, end))
            return rows, self.rest.complete

        complete = False
        try:
            rows, complete = await asyncio.to_thread(fetch)
            for occ, r in rows:
                recv = now_ns()
                self.rec.record('trade', events.trade_from_rest(occ, r, recv), {'S': occ, **r}, 'backfill', recv)
        except Exception:
            logger.exception("tape: trade backfill failed")
            complete = False
        self._put(('status', {'event': 'backfill_done', 'gap_start_ns': gap_start_ns, 'gap_end_ns': gap_end_ns,
                              'complete': complete}, now_ns()))

    async def _spot(self, websockets) -> None:
        backoff = 1
        unds = sorted({c['underlying'] for c in self.contracts.values()})
        while not self.stop:
            try:
                async with websockets.connect(SIP_WS, max_size=2 ** 22, ping_interval=20) as ws:
                    await ws.recv()
                    await ws.send(json.dumps({'action': 'auth', 'key': config.ALPACA_API_KEY,
                                              'secret': config.ALPACA_SECRET_KEY}))
                    await ws.recv()
                    await ws.send(json.dumps({'action': 'subscribe', 'trades': unds}))
                    if self.spot_gap_start is not None:
                        asyncio.create_task(self._spot_backfill(self.spot_gap_start, now_ns(), unds))
                        self.spot_gap_start = None
                    backoff = 1
                    async for raw in ws:
                        recv = now_ns()
                        for m in json.loads(raw):
                            if m.get('T') == 't':
                                self._put(('spot', m, recv))
            except asyncio.CancelledError:
                return
            except Exception as exc:
                if self.stop:
                    return
                if self.spot_gap_start is None:
                    self.spot_gap_start = now_ns()
                logger.warning("tape: spot feed down (%s) — reconnecting", exc)
                await asyncio.sleep(backoff)
                backoff = min(settings.RECONNECT_MAX_S, backoff * 2)

    async def _spot_backfill(self, a_ns, b_ns, unds) -> None:
        for u in unds:
            try:
                rows = await asyncio.to_thread(self.rest.stock_trades, u, events.ns_to_iso(a_ns), events.ns_to_iso(b_ns))
            except Exception:
                logger.warning("tape: spot backfill failed for %s (spot stays missing in the gap)", u)
                continue
            for r in rows:
                self._put(('spot', {'S': u, **r}, now_ns()))


# ── entry points ──────────────────────────────────────────────────────────────

def make_pipeline(store, session: date, contracts: dict, denom: dict = None, emit=card_emitter) -> Pipeline:
    pipe = Pipeline(store, session, baseline.Baselines(store, session), contracts,
                    universe_size=(denom or {}).get('subscribed') or len(contracts), emit=emit,
                    catalyst_rows=None)
    pipe.watch_legs = load_watches(store)
    return pipe


def close_session(store, session: date) -> None:
    """Session close: persist each name's premium histogram (captured prints) for future baselines."""
    for und in settings.UNIVERSE:
        n = baseline.store_session_histogram(store, und, session.isoformat(), 'capture')
        logger.info("SESSION-CLOSE %s %s: %d counted prints in premium histogram", session, und, n)
    store.flush()
    store.compress(session.isoformat())


def replay(session: str, src_db: str = None, out_db: str = None, archive_dir: str = None, emit=None) -> Pipeline:
    """Re-run an archived session through a fresh pipeline. Point-in-time inputs (contracts, OI vintages,
    baselines for that session, daily volumes, premium histograms) are copied from the source DB; derived
    tables are rebuilt from the archive alone."""
    src = src_db or settings.DB_PATH
    out = out_db or f"replay_{session}.db"
    if os.path.exists(out):
        os.remove(out)
    store = Store(out, archive_dir or settings.ARCHIVE_DIR)
    s = Store(src, archive_dir or settings.ARCHIVE_DIR)
    for tbl in ('contracts', 'oi_vintages', 'daily_volume', 'quiet_builds', 'watches'):
        for row in s.q(f"SELECT * FROM {tbl}"):
            store.x(f"INSERT OR REPLACE INTO {tbl} VALUES ({','.join('?' * len(row))})", row)
    for row in s.q("SELECT * FROM baselines WHERE for_session=?", (session,)):
        store.x(f"INSERT OR REPLACE INTO baselines VALUES ({','.join('?' * len(row))})", row)
    d = date.fromisoformat(session)
    pipe = make_pipeline(store, d, load_contracts(store), emit=emit or (lambda c: None))
    for rec in s.read_archive(session):
        pipe.dispatch(rec)
    pipe.finish()
    s.close()
    return pipe


def state_digest(store, session: str) -> dict:
    """Comparable summary of derived state (used to prove replay == live)."""
    obs = store.q("SELECT obs_id, version, dims FROM observations WHERE session=? ORDER BY obs_id", (session,))
    prints = store.q("SELECT status, side, COUNT(*), SUM(size) FROM prints WHERE session=? GROUP BY status, side "
                     "ORDER BY status, side", (session,))
    pk = store.q("SELECT pkg_id, ratio, geometry, association, status FROM packages WHERE session=? ORDER BY pkg_id",
                 (session,))
    return {'observations': [(o, v, json.loads(d)['rarity'], json.loads(d)['side_thesis'].get('state'),
                              json.loads(d)['coverage']) for o, v, d in obs],
            'prints': prints, 'packages': pk}
