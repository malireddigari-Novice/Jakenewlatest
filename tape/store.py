"""
Storage (flow handoff §3, §10): an APPEND-ONLY raw archive plus one point-in-time state database.

Raw archive  — `ARCHIVE_DIR/<NY session>/events.jsonl` (plain, append-only, crash-safe: a torn last
               line is the only possible loss) and gzip-compressed to `events.jsonl.gz` at session close;
               one line per ORIGINAL provider message
               (trade, quote, spot, status) in arrival order with a global sequence number, receive time,
               source and checksum. Written BEFORE anything is derived. Replay reads it back in `seq`
               order, so a replay sees exactly what the live process saw.
State DB     — sqlite (`TAPE_DB`): derived, versioned records. Corrections never overwrite an original:
               a cancel marks its target CANCELLED and is itself stored as a CANCEL_RECORD.
"""
import glob
import gzip
import json
import os
import shutil
import sqlite3
import threading

from tape import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS prints (
    key TEXT PRIMARY KEY, slot TEXT, occ TEXT, underlying TEXT, expiry TEXT, right TEXT, strike REAL,
    price REAL, size INTEGER, exchange TEXT, cond TEXT, tags TEXT, event_ns INTEGER, recv_ns INTEGER,
    source TEXT, session TEXT, status TEXT, cancelled_by TEXT, side TEXT, side_reason TEXT,
    quote_bid REAL, quote_ask REAL, quote_age_ms REAL, spot REAL, spot_age_ms REAL, mech TEXT,
    late INTEGER, checksum TEXT, parser_version TEXT, cond_map_version TEXT, rule_version TEXT);
CREATE INDEX IF NOT EXISTS prints_occ ON prints(occ, session, event_ns);
CREATE INDEX IF NOT EXISTS prints_und ON prints(underlying, session, event_ns);
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, scope TEXT, start_ns INTEGER, end_ns INTEGER,
    detail TEXT, recovery TEXT, session TEXT);
CREATE TABLE IF NOT EXISTS contracts (
    occ TEXT PRIMARY KEY, underlying TEXT, root TEXT, expiry TEXT, right TEXT, strike REAL,
    multiplier REAL, adjusted INTEGER, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS oi_vintages (
    occ TEXT, oi_date TEXT, oi INTEGER, fetched_at TEXT, PRIMARY KEY (occ, oi_date));
CREATE TABLE IF NOT EXISTS daily_volume (
    occ TEXT, session TEXT, volume INTEGER, vwap REAL, source TEXT, PRIMARY KEY (occ, session));
CREATE TABLE IF NOT EXISTS baselines (
    scope TEXT, kind TEXT, for_session TEXT, value REAL, n_sessions INTEGER, as_of TEXT,
    available_at TEXT, status TEXT, detail TEXT, rule_version TEXT, PRIMARY KEY (scope, kind, for_session));
CREATE TABLE IF NOT EXISTS quiet_builds (
    occ TEXT, for_session TEXT, total INTEGER, sessions INTEGER, detail TEXT, PRIMARY KEY (occ, for_session));
CREATE TABLE IF NOT EXISTS packages (
    pkg_id TEXT PRIMARY KEY, underlying TEXT, session TEXT, start_ns INTEGER, end_ns INTEGER, legs TEXT,
    ratio TEXT, geometry TEXT, association TEXT, side_text TEXT, conditional_cashflow REAL,
    competing TEXT, status TEXT, rule_version TEXT);
CREATE TABLE IF NOT EXISTS package_prints (print_key TEXT PRIMARY KEY, pkg_id TEXT, allocated INTEGER);
CREATE TABLE IF NOT EXISTS observations (
    obs_id TEXT PRIMARY KEY, occ TEXT, session TEXT, version INTEGER, campaign_id TEXT, dims TEXT,
    created_ns INTEGER, updated_ns INTEGER);
CREATE TABLE IF NOT EXISTS observation_versions (
    obs_id TEXT, version INTEGER, at_ns INTEGER, dims TEXT, evidence_hash TEXT, reason TEXT,
    PRIMARY KEY (obs_id, version));
CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id TEXT PRIMARY KEY, underlying TEXT, expiry TEXT, right TEXT, direction TEXT, state TEXT,
    first_session TEXT, last_session TEXT, events TEXT);
CREATE TABLE IF NOT EXISTS cards (
    signal_id TEXT, version INTEGER, channel TEXT, payload TEXT, evidence_hash TEXT, created_ns INTEGER,
    outbox_key TEXT, kind TEXT, PRIMARY KEY (signal_id, version, channel));
CREATE TABLE IF NOT EXISTS watches (
    watch_id TEXT PRIMARY KEY, owner TEXT, structure TEXT, legs TEXT, entry_ns INTEGER, fill TEXT,
    fill_verified INTEGER, rules TEXT, active INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS outcomes (
    obs_id TEXT, horizon_min INTEGER, entry_ask REAL, exit_bid REAL, net_per_contract REAL,
    underlying_move REAL, status TEXT, detail TEXT, PRIMARY KEY (obs_id, horizon_min));
"""


class Store:

    def __init__(self, db_path: str = None, archive_dir: str = None) -> None:
        self.db_path = db_path or settings.DB_PATH
        self.archive_dir = archive_dir or settings.ARCHIVE_DIR
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self._lock = threading.Lock()
        self._fh = None
        self._fh_session = None
        self._seq = 0

    # ── raw archive ───────────────────────────────────────────────────────────

    def _open(self, session: str):
        if self._fh_session == session and self._fh:
            return self._fh
        if self._fh:
            self._fh.close()
        d = os.path.join(self.archive_dir, session)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, 'events.jsonl')
        self._seq = max((r['seq'] for r in self.read_archive(session)), default=0)
        self._fh = open(path, 'a', encoding='utf-8')
        self._fh_session = session
        return self._fh

    def archive(self, session: str, kind: str, recv_ns: int, source: str, payload: dict, checksum: str) -> int:
        """Append one ORIGINAL message. Returns its sequence number."""
        with self._lock:
            fh = self._open(session)
            self._seq += 1
            fh.write(json.dumps({'seq': self._seq, 'kind': kind, 'recv_ns': recv_ns, 'source': source,
                                 'checksum': checksum, 'payload': payload}, default=str) + '\n')
            return self._seq

    def flush(self) -> None:
        with self._lock:
            if self._fh:
                self._fh.flush()
            self.db.commit()

    def close(self) -> None:
        self.flush()
        if self._fh:
            self._fh.close()
            self._fh = None

    def read_archive(self, session: str):
        base = os.path.join(self.archive_dir, session, 'events.jsonl')
        if os.path.exists(base):
            f = open(base, 'r', encoding='utf-8')
        elif os.path.exists(base + '.gz'):
            f = gzip.open(base + '.gz', 'rt', encoding='utf-8')
        else:
            return
        with f:
            try:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            return                  # a torn final line after a crash ends the archive
            except EOFError:
                return

    def compress(self, session: str) -> None:
        """Session close: gzip the day's plain archive (atomic replace; the plain file is removed last)."""
        if self._fh_session == session and self._fh:
            self._fh.close()
            self._fh, self._fh_session = None, None
        base = os.path.join(self.archive_dir, session, 'events.jsonl')
        if not os.path.exists(base):
            return
        with open(base, 'rb') as src, gzip.open(base + '.gz.tmp', 'wb') as dst:
            shutil.copyfileobj(src, dst)
        os.replace(base + '.gz.tmp', base + '.gz')
        os.remove(base)

    def sessions(self) -> list:
        return sorted({os.path.basename(os.path.dirname(p))
                       for p in glob.glob(os.path.join(self.archive_dir, '*', 'events.jsonl*'))})

    # ── db helpers ────────────────────────────────────────────────────────────

    def q(self, sql, args=()):
        return self.db.execute(sql, args).fetchall()

    def x(self, sql, args=()):
        with self._lock:
            return self.db.execute(sql, args)

    def incident(self, kind, scope, start_ns, end_ns, detail, recovery, session) -> int:
        cur = self.x("INSERT INTO incidents (kind, scope, start_ns, end_ns, detail, recovery, session) "
                     "VALUES (?,?,?,?,?,?,?)", (kind, scope, start_ns, end_ns, json.dumps(detail, default=str),
                                                 recovery, session))
        return cur.lastrowid
