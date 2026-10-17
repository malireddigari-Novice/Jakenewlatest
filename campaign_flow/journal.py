"""§14/§16 Durable journal: append-only decisions and evidence + transactional campaign state (SQLite).

A NEW database (`jakenew_campaign_flow.db`) — it never reuses the legacy engine's state or prototype tables.
`schema_version` is checked on open; an unknown version is refused rather than silently reused.

Idempotency: every externally triggered operation carries a stable event_id. `once(event_id, fn)` runs fn
inside one IMMEDIATE transaction and stores its result; a repeat returns the recorded result unchanged.
"""
import json
import sqlite3
import time

from campaign_flow import settings as S

SCHEMA_VERSION = 'cf-journal-1'

_DDL = [
    "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)",
    "CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, kind TEXT, ts REAL, result TEXT, "
    "rule_version TEXT, created REAL)",
    "CREATE TABLE IF NOT EXISTS log (seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, ticker TEXT, "
    "ref TEXT, body TEXT, rule_version TEXT)",
    "CREATE INDEX IF NOT EXISTS log_kind ON log(kind, ts)",
    "CREATE TABLE IF NOT EXISTS campaigns (campaign_id TEXT PRIMARY KEY, ticker TEXT, direction TEXT, "
    "session TEXT, state TEXT, body TEXT, updated REAL)",
    "CREATE TABLE IF NOT EXISTS proposal_count (ticker TEXT, session TEXT, n INTEGER, PRIMARY KEY (ticker, session))",
    "CREATE TABLE IF NOT EXISTS fills (fill_id TEXT PRIMARY KEY, campaign_id TEXT, kind TEXT, qty INTEGER, "
    "price REAL, ts REAL, order_id TEXT, source TEXT, accepted INTEGER, body TEXT)",
    "CREATE TABLE IF NOT EXISTS orders (order_key TEXT PRIMARY KEY, campaign_id TEXT, kind TEXT, "
    "client_order_id TEXT, broker_order_id TEXT, qty INTEGER, limit_price REAL, status TEXT, "
    "filled_qty INTEGER, avg_price REAL, submitted_ts REAL, body TEXT)",
    "CREATE TABLE IF NOT EXISTS oi_chains (seq INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, session TEXT, body TEXT)",
    "CREATE TABLE IF NOT EXISTS oi_freeze (ticker TEXT, session TEXT, body TEXT, PRIMARY KEY (ticker, session))",
    "CREATE TABLE IF NOT EXISTS opening (ticker TEXT, session TEXT, body TEXT, PRIMARY KEY (ticker, session))",
    "CREATE TABLE IF NOT EXISTS turnover_mem (seq INTEGER PRIMARY KEY AUTOINCREMENT, series TEXT, session TEXT, "
    "available_ts REAL, body TEXT)",
    "CREATE TABLE IF NOT EXISTS cohorts (series TEXT, session TEXT, body TEXT, PRIMARY KEY (series, session))",
    "CREATE TABLE IF NOT EXISTS cards (card_id TEXT PRIMARY KEY, campaign_id TEXT, label TEXT, ts REAL, "
    "published INTEGER, body TEXT)",
    "CREATE TABLE IF NOT EXISTS marks (mark_id TEXT PRIMARY KEY, ref TEXT, occ TEXT, label TEXT, due_ts REAL, "
    "done INTEGER, body TEXT)",
]


class Journal:

    def __init__(self, path: str = None) -> None:
        self.path = path or S.JOURNAL_DB
        self.con = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        for d in _DDL:
            self.con.execute(d)
        v = self.con.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone()
        if v is None:
            self.con.execute("INSERT INTO meta VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        elif v[0] != SCHEMA_VERSION:
            raise RuntimeError(f"journal {self.path} has schema {v[0]}, expected {SCHEMA_VERSION} — "
                               f"migrate explicitly or use a new journal")

    def close(self) -> None:
        self.con.close()

    # ── transactions / idempotency ─────────────────────────────────────────────
    def once(self, event_id: str, kind: str, ts: float, fn):
        """Run fn() exactly once per event_id inside an IMMEDIATE transaction; repeats return the stored
        result. fn must only touch the journal through this connection."""
        row = self.con.execute("SELECT result FROM events WHERE event_id=?", (event_id,)).fetchone()
        if row:
            return {**json.loads(row[0]), 'duplicate': True}
        self.con.execute("BEGIN IMMEDIATE")
        try:
            row = self.con.execute("SELECT result FROM events WHERE event_id=?", (event_id,)).fetchone()
            if row:
                self.con.execute("COMMIT")
                return {**json.loads(row[0]), 'duplicate': True}
            result = fn()
            self.con.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",
                             (event_id, kind, ts, json.dumps(result, default=str), S.RULE_VERSION, time.time()))
            self.con.execute("COMMIT")
            return result
        except BaseException:
            self.con.execute("ROLLBACK")
            raise

    def event(self, event_id):
        row = self.con.execute("SELECT result FROM events WHERE event_id=?", (event_id,)).fetchone()
        return json.loads(row[0]) if row else None

    # ── append-only evidence log ───────────────────────────────────────────────
    def log(self, ts, kind, body, ticker=None, ref=None) -> None:
        self.con.execute("INSERT INTO log (ts, kind, ticker, ref, body, rule_version) VALUES (?,?,?,?,?,?)",
                         (ts, kind, ticker, ref, json.dumps(body, default=str), S.RULE_VERSION))

    def logs(self, kind=None, ticker=None):
        q, a = "SELECT ts, kind, ticker, ref, body FROM log WHERE 1=1", []
        if kind:
            q += " AND kind=?"; a.append(kind)
        if ticker:
            q += " AND ticker=?"; a.append(ticker)
        return [{'ts': r[0], 'kind': r[1], 'ticker': r[2], 'ref': r[3], **json.loads(r[4])}
                for r in self.con.execute(q + " ORDER BY seq", a)]

    # ── campaigns ──────────────────────────────────────────────────────────────
    def put_campaign(self, c: dict) -> None:
        self.con.execute("INSERT OR REPLACE INTO campaigns VALUES (?,?,?,?,?,?,?)",
                         (c['campaign_id'], c['ticker'], c['direction'], c['session'], c['state'],
                          json.dumps(c, default=str), time.time()))

    def campaign(self, cid):
        r = self.con.execute("SELECT body FROM campaigns WHERE campaign_id=?", (cid,)).fetchone()
        return json.loads(r[0]) if r else None

    def campaigns(self, states=None):
        rows = self.con.execute("SELECT body FROM campaigns ORDER BY rowid").fetchall()
        out = [json.loads(r[0]) for r in rows]
        return [c for c in out if not states or c['state'] in states]

    def proposals(self, ticker, session) -> int:
        r = self.con.execute("SELECT n FROM proposal_count WHERE ticker=? AND session=?", (ticker, session)).fetchone()
        return r[0] if r else 0

    def bump_proposals(self, ticker, session) -> None:
        self.con.execute("INSERT INTO proposal_count VALUES (?,?,1) ON CONFLICT(ticker, session) "
                         "DO UPDATE SET n=n+1", (ticker, session))

    # ── fills / orders ─────────────────────────────────────────────────────────
    def put_fill(self, f: dict, accepted: bool) -> None:
        self.con.execute("INSERT OR IGNORE INTO fills VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (f['event_id'], f['campaign_id'], f['kind'], f['qty'], f['price'], f['ts'],
                          f.get('order_id'), f.get('source'), int(accepted), json.dumps(f, default=str)))

    def fills(self, campaign_id=None):
        q = "SELECT body, accepted FROM fills" + (" WHERE campaign_id=?" if campaign_id else "") + " ORDER BY ts"
        return [{**json.loads(r[0]), 'accepted': bool(r[1])}
                for r in self.con.execute(q, (campaign_id,) if campaign_id else ())]

    def put_order(self, o: dict) -> None:
        self.con.execute("INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (o['order_key'], o['campaign_id'], o['kind'], o['client_order_id'],
                          o.get('broker_order_id'), o['qty'], o.get('limit_price'), o['status'],
                          o.get('filled_qty') or 0, o.get('avg_price'), o['submitted_ts'],
                          json.dumps(o, default=str)))

    def order(self, key):
        r = self.con.execute("SELECT body FROM orders WHERE order_key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else None

    def orders(self, campaign_id=None, open_only=False):
        rows = [json.loads(r[0]) for r in self.con.execute("SELECT body FROM orders ORDER BY submitted_ts")]
        if campaign_id:
            rows = [o for o in rows if o['campaign_id'] == campaign_id]
        if open_only:
            rows = [o for o in rows if o['status'] in ('NEW', 'SUBMITTED', 'PARTIAL', 'CANCEL_REQUESTED')]
        return rows

    # ── OI / opening / turnover / cohorts ──────────────────────────────────────
    def add_chain(self, chain: dict) -> None:
        self.con.execute("INSERT INTO oi_chains (ticker, session, body) VALUES (?,?,?)",
                         (chain['ticker'], chain['session'], json.dumps(chain, default=str)))

    def chains(self, ticker, session):
        return [json.loads(r[0]) for r in self.con.execute(
            "SELECT body FROM oi_chains WHERE ticker=? AND session=? ORDER BY seq", (ticker, session))]

    def put_freeze(self, f: dict) -> dict:
        """Write-once per ticker/session; returns what is stored (never refreshed intraday)."""
        self.con.execute("INSERT OR IGNORE INTO oi_freeze VALUES (?,?,?)",
                         (f['ticker'], f['session'], json.dumps(f, default=str)))
        return self.freeze(f['ticker'], f['session'])

    def freeze(self, ticker, session):
        r = self.con.execute("SELECT body FROM oi_freeze WHERE ticker=? AND session=?", (ticker, session)).fetchone()
        return json.loads(r[0]) if r else None

    def put_opening(self, o: dict) -> dict:
        self.con.execute("INSERT OR IGNORE INTO opening VALUES (?,?,?)",
                         (o['ticker'], o['session'], json.dumps(o, default=str)))
        return self.opening(o['ticker'], o['session'])

    def opening(self, ticker, session):
        r = self.con.execute("SELECT body FROM opening WHERE ticker=? AND session=?", (ticker, session)).fetchone()
        return json.loads(r[0]) if r else None

    def add_turnover(self, mem: dict) -> None:
        self.con.execute("INSERT INTO turnover_mem (series, session, available_ts, body) VALUES (?,?,?,?)",
                         (json.dumps(list(mem['series'])), mem['session'], mem['available_ts'],
                          json.dumps(mem, default=str)))

    def turnover(self, series, as_of_ts: float):
        """Latest memory for the series that was AVAILABLE by as_of_ts (point in time)."""
        r = self.con.execute("SELECT body FROM turnover_mem WHERE series=? AND available_ts<=? "
                             "ORDER BY available_ts DESC, seq DESC LIMIT 1",
                             (json.dumps(list(series)), as_of_ts)).fetchone()
        return json.loads(r[0]) if r else None

    def latest_oi(self, series, before_session: str):
        """The most recent morning OI recorded for a series in an EARLIER session (for oi_earlier)."""
        r = self.con.execute("SELECT body FROM turnover_mem WHERE series=? AND session<? "
                             "ORDER BY session DESC, seq DESC LIMIT 1",
                             (json.dumps(list(series)), before_session)).fetchone()
        return json.loads(r[0]).get('oi_current') if r else None

    def put_cohort(self, series, session, body) -> dict:
        self.con.execute("INSERT OR IGNORE INTO cohorts VALUES (?,?,?)",
                         (json.dumps(list(series)), session, json.dumps(body, default=str)))
        return self.cohort(series, session)

    def cohort(self, series, session):
        r = self.con.execute("SELECT body FROM cohorts WHERE series=? AND session=?",
                             (json.dumps(list(series)), session)).fetchone()
        return json.loads(r[0]) if r else None

    # ── cards / marks ──────────────────────────────────────────────────────────
    def put_card(self, card_id, campaign_id, label, ts, body, published=False) -> bool:
        cur = self.con.execute("INSERT OR IGNORE INTO cards VALUES (?,?,?,?,?,?)",
                               (card_id, campaign_id, label, ts, int(published), json.dumps(body, default=str)))
        return cur.rowcount == 1

    def cards(self, campaign_id=None):
        q = "SELECT label, ts, body, published FROM cards" + (" WHERE campaign_id=?" if campaign_id else "") + " ORDER BY ts, rowid"
        return [{'label': r[0], 'ts': r[1], 'published': bool(r[3]), **json.loads(r[2])}
                for r in self.con.execute(q, (campaign_id,) if campaign_id else ())]

    def add_mark(self, mark_id, ref, occ, label, due_ts, body) -> None:
        self.con.execute("INSERT OR IGNORE INTO marks VALUES (?,?,?,?,?,0,?)",
                         (mark_id, ref, occ, label, due_ts, json.dumps(body, default=str)))

    def due_marks(self, now_ts):
        return [{'mark_id': r[0], 'ref': r[1], 'occ': r[2], 'label': r[3], 'due_ts': r[4], **json.loads(r[6])}
                for r in self.con.execute("SELECT * FROM marks WHERE done=0 AND due_ts<=? ORDER BY due_ts", (now_ts,))]

    def complete_mark(self, mark_id, body) -> None:
        self.con.execute("UPDATE marks SET done=1, body=? WHERE mark_id=?", (json.dumps(body, default=str), mark_id))

    def marks(self, ref=None):
        q = "SELECT * FROM marks" + (" WHERE ref=?" if ref else "") + " ORDER BY due_ts"
        return [{'mark_id': r[0], 'ref': r[1], 'occ': r[2], 'label': r[3], 'due_ts': r[4], 'done': bool(r[5]),
                 **json.loads(r[6])} for r in self.con.execute(q, (ref,) if ref else ())]
