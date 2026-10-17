"""
Discord notifications for the Attention Engine — rich embed "cards", not plain lines.

Every trade the engine takes is the output of the whole attention hierarchy, so the card
shows the *evidence*, not just the fill: the cross-symbol attention board (why THIS name won
the tape), the within-name control, the contract, and the exit plan. Exit cards close the
loop — P&L, hold time, and a plain-English reason (including where attention rotated to).

No-op when DISCORD_WEBHOOK_URL is unset, so the engine runs fine without it.

Delivery is a durable, transactional OUTBOX (sqlite, `NOTIFY_OUTBOX_DB`), not fire-and-forget:
every card is saved PENDING under an idempotency key sha256(signal_id|state_version|evidence_hash|
channel) BEFORE the webhook is attempted, and marked SENT only after Discord accepts it and returns a
message id (`?wait=true`). A 429 honours Discord's retry_after; timeouts / 5xx back off exponentially;
a permanent 4xx or too many attempts lands in DEAD. The engine calls `flush()` every poll, so a card
that failed during an outage is retried later instead of being lost. Re-enqueueing the same key is a
no-op, so a retry can never produce a second card. No card ever pings (`allowed_mentions` is empty).
"""
import hashlib
import json
import logging
import sqlite3
import time
from datetime import datetime
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)

_GREEN  = 0x2ECC71
_RED    = 0xE74C3C
_AMBER  = 0xF1C40F
_BLUE   = 0x5865F2

# Exit reason → human sentence. `{leader}` is filled with the new attention leader.
_REASON_TEXT = {
    'STRUCTURAL_TP1':        "Banked the first slice at the structural target.",
    'STRUCTURAL_TP2':        "Full structural objective reached — position closed.",
    'TRAIL_GIVEBACK':        "Trailing stop — gave back too much of the peak gain.",
    'ATTENTION_ROTATED_AWAY': "Institutional attention rotated away{to_leader}.",
    'CONTROL_FLIPPED':       "Within-name call/put control flipped against the position.",
    'EOD_FLATTEN':           "End-of-day flatten — 0DTE convexity is never carried overnight.",
    # base wave exits
    'STOP_LOSS':             "Hard risk stop — capped the loss.",
    'CONTROL_TRANSFER':      "Control transferred to the other side — thesis dead.",
    'CONTROL_FLIP_OVERWHELMING': "Opposite side seized control overwhelmingly.",
    'ROTATION':              "Attention rotated to a stronger campaign{to_leader}.",
    'STATISTICAL_EXHAUSTION': "Campaign statistically exhausted.",
    'DISTRIBUTION_REDUCE':   "Trimmed — distribution probability rose off the peak.",
    'DISTRIBUTION_EXIT':     "Closed the runner — coherent distribution / exit flow.",
    'RUNNER_TRAIL':          "Runner trailing stop protected the extended run.",
    # follow-up §20 campaign-confidence exits
    'VERIFIED_DISTRIBUTION':               "Verified distribution — inventory being sold.",
    'PERSISTENT_CONTROL_TRANSFER':         "Control persistently transferred to the other side.",
    'OPPOSITE_SIDE_CAMPAIGN_CONFIRMED':    "A coherent opposite-side campaign took over.",
    'ROTATION_WITH_CURRENT_CAMPAIGN_FAILURE': "Rotation AND the current campaign deteriorated{to_leader}.",
    'PREMIUM_STRUCTURE_FAILURE':           "Premium structure broke — higher lows failed.",
    'RESILIENCE_FAILURE':                  "Campaign resilience collapsed — no recovery.",
    'TRUE_MULTI_VARIABLE_EXHAUSTION':      "Genuine multi-variable exhaustion (not just cooling).",
}


RESEARCH_FOOTER = "For research only. Not investment advice. Verify fills and manage your own risk."

# ── outbox (durable delivery) ─────────────────────────────────────────────────

_SCHEMA = """CREATE TABLE IF NOT EXISTS outbox (
    key TEXT PRIMARY KEY, signal_id TEXT, state_version TEXT, evidence_hash TEXT, channel TEXT,
    payload TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL, last_error TEXT, message_id TEXT,
    created_at TEXT NOT NULL, sent_at TEXT)"""


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(config.NOTIFY_OUTBOX_DB, timeout=5)
    con.execute(_SCHEMA)
    return con


def _channel() -> str:
    """Stable, non-secret identity of the destination webhook (never store the token itself)."""
    return hashlib.sha256(config.DISCORD_WEBHOOK_URL.encode()).hexdigest()[:12]


def idempotency_key(signal_id: str, state_version: str, evidence_hash: str, channel: str) -> str:
    return hashlib.sha256(f"{signal_id}|{state_version}|{evidence_hash}|{channel}".encode()).hexdigest()


def _evidence_hash(payload: dict) -> str:
    """Hash of the card's content EXCLUDING its render timestamp — the same evidence re-rendered a
    second later is the same card."""
    body = json.loads(json.dumps(payload, default=str))
    for e in body.get('embeds') or []:
        e.pop('timestamp', None)
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def enqueue(payload: dict, *, signal_id: str, state_version: str = '1') -> Optional[str]:
    """Persist one message as PENDING (idempotent on its key). Returns the key, or None when
    Discord is not configured / the outbox is unwritable."""
    if not config.DISCORD_WEBHOOK_URL:
        return None
    payload = {**payload, 'allowed_mentions': {'parse': []}}     # never @everyone / @here / roles
    ev = _evidence_hash(payload)
    ch = _channel()
    key = idempotency_key(signal_id, state_version, ev, ch)
    try:
        with _db() as con:
            con.execute("INSERT OR IGNORE INTO outbox (key, signal_id, state_version, evidence_hash, "
                        "channel, payload, status, next_attempt_at, created_at) "
                        "VALUES (?,?,?,?,?,?,'PENDING',?,?)",
                        (key, signal_id, state_version, ev, ch, json.dumps(payload, default=str),
                         time.time(), datetime.now().astimezone().isoformat()))
    except Exception as exc:
        logger.warning("notify: outbox write failed (%s) — card not queued: %s", exc, signal_id)
        return None
    return key


def _deliver_one(con, key: str, payload: str, attempts: int) -> bool:
    """Attempt one webhook POST and record the outcome. Returns False when the caller should stop
    this flush (rate-limited or Discord unreachable) so later cards wait their turn."""
    now = time.time()
    attempts += 1
    try:
        r = requests.post(config.DISCORD_WEBHOOK_URL, params={'wait': 'true'},
                          json=json.loads(payload), timeout=config.NOTIFY_TIMEOUT_S)
    except Exception as exc:                                  # timeout / connection error: transient
        _retry_later(con, key, attempts, now, f"{type(exc).__name__}: {exc}")
        return False
    if 200 <= r.status_code < 300:
        mid = None
        try:
            mid = str((r.json() or {}).get('id') or '') or None
        except Exception:
            pass
        con.execute("UPDATE outbox SET status='SENT', attempts=?, message_id=?, sent_at=?, last_error=NULL "
                    "WHERE key=?", (attempts, mid, datetime.now().astimezone().isoformat(), key))
        return True
    if r.status_code == 429:
        try:
            wait = float((r.json() or {}).get('retry_after'))
        except Exception:
            wait = float(r.headers.get('Retry-After') or 5)
        # A rate limit is Discord's pacing, not a failed delivery — it does not consume an attempt.
        con.execute("UPDATE outbox SET next_attempt_at=?, last_error=? WHERE key=?",
                    (now + max(wait, 0.5), f"429 retry_after={wait}", key))
        return False
    if r.status_code >= 500:
        _retry_later(con, key, attempts, now, f"HTTP {r.status_code}")
        return False
    # Any other 4xx is permanent (bad webhook / malformed card) — dead-letter it, keep flushing.
    con.execute("UPDATE outbox SET status='DEAD', attempts=?, last_error=? WHERE key=?",
                (attempts, f"HTTP {r.status_code}: {r.text[:300]}", key))
    logger.warning("notify: card dead-lettered (HTTP %s) key=%s", r.status_code, key[:12])
    return True


def _retry_later(con, key, attempts, now, err) -> None:
    if attempts >= config.NOTIFY_MAX_ATTEMPTS:
        con.execute("UPDATE outbox SET status='DEAD', attempts=?, last_error=? WHERE key=?",
                    (attempts, err, key))
        logger.warning("notify: card dead-lettered after %d attempts (%s) key=%s", attempts, err, key[:12])
        return
    backoff = min(config.NOTIFY_BACKOFF_MAX_S, config.NOTIFY_BACKOFF_BASE_S * (2 ** (attempts - 1)))
    con.execute("UPDATE outbox SET attempts=?, next_attempt_at=?, last_error=? WHERE key=?",
                (attempts, now + backoff, err, key))
    logger.debug("notify: delivery failed (%s) — retry in %.0fs", err, backoff)


def flush(limit: int = None) -> int:
    """Deliver due PENDING cards oldest-first. Never raises. Returns the number of cards SENT."""
    if not config.DISCORD_WEBHOOK_URL:
        return 0
    limit = limit or config.NOTIFY_FLUSH_LIMIT
    sent = 0
    try:
        with _db() as con:
            # A 429 rate-limits the whole webhook: hold every card until it lifts so order is kept.
            held = con.execute("SELECT MAX(next_attempt_at) FROM outbox WHERE status='PENDING' "
                               "AND last_error LIKE '429%'").fetchone()[0]
            if held and held > time.time():
                return 0
            rows = con.execute("SELECT key, payload, attempts FROM outbox WHERE status='PENDING' "
                               "AND next_attempt_at<=? ORDER BY created_at LIMIT ?",
                               (time.time(), limit)).fetchall()
            for key, payload, attempts in rows:
                if not _deliver_one(con, key, payload, attempts):
                    break
                con.commit()
                sent += con.execute("SELECT status='SENT' FROM outbox WHERE key=?", (key,)).fetchone()[0]
    except Exception as exc:
        logger.debug("notify: flush failed: %s", exc)
    return sent


def outbox_stats() -> dict:
    """{status: count} — for the EOD summary / monitoring of the delivery backlog."""
    try:
        with _db() as con:
            return dict(con.execute("SELECT status, COUNT(*) FROM outbox GROUP BY status").fetchall())
    except Exception:
        return {}


# ── low-level ─────────────────────────────────────────────────────────────────

def _post(embed: dict, *, signal_id: str = None) -> None:
    """Queue an embed card and try to deliver it now (it stays PENDING for the next flush on failure)."""
    sid = signal_id or f"{embed.get('title', '')}|{datetime.now().date().isoformat()}"
    if enqueue({'embeds': [embed]}, signal_id=sid):
        flush()


def send(text: str, *, signal_id: str = None) -> None:
    """Plain-content fallback (kept for ad-hoc messages). Same text on the same day is one card
    unless the caller passes a distinguishing signal_id."""
    sid = signal_id or f"text|{datetime.now().date().isoformat()}|{text}"
    if enqueue({'content': text}, signal_id=sid):
        flush()


# ── helpers ───────────────────────────────────────────────────────────────────

def _board_table(board: dict, highlight: str = None, top: int = 7) -> str:
    """Monospace attention board — the ranked pool, traded name marked with a caret."""
    rows = (board.get('ranked') or [])[:top]
    if not rows:
        return "```(no board)```"
    out = ["  #  SYM    SCORE  SHARE  CTRL"]
    for r in rows:
        caret = '>' if r['symbol'] == highlight else ' '
        out.append(f"{caret} {r['rank']:<2} {r['symbol']:<5} {r['attention_score']:>4.0f}"
                   f"  {100 * r['share']:>3.0f}%  {r.get('control_side') or '-'}")
    return "```\n" + "\n".join(out) + "\n```"


def _hold(opened_at_iso: str, now: datetime) -> str:
    try:
        opened = datetime.fromisoformat(opened_at_iso)
        mins = int((now - opened).total_seconds() // 60)
        return f"{mins // 60}h {mins % 60:02d}m" if mins >= 60 else f"{mins}m"
    except Exception:
        return "?"


def _exit_plan_text() -> str:
    return (f"Scale ½ at +{config.TAKE_PROFIT_1_PCT*100:.0f}% · rest at "
            f"+{config.TAKE_PROFIT_2_PCT*100:.0f}% · trail {config.TRAIL_GIVEBACK_PCT*100:.0f}% "
            f"off peak (arms +{config.TRAIL_ARM_PCT*100:.0f}%)\n"
            f"Rotation / control-flip exit after {config.ATTENTION_EXIT_SUSTAIN} sustained polls")


def _mode_tag(mode: str) -> str:
    paper = "paper" if config.ALPACA_PAPER else "LIVE $"
    return f"{mode} · Alpaca {paper}"


# ── cards ─────────────────────────────────────────────────────────────────────

def entry_card(board: dict, *, symbol: str, side: str, strike: float, expiry: str,
               qty: int, price: float, row: dict, spot: Optional[float], mode: str,
               now: datetime) -> None:
    """The reason we're in: attention leader + control + contract + plan + the full board."""
    direction = 'BULLISH' if side == 'CALL' else 'BEARISH'
    thesis = (f"**{symbol}** owns **{100*row['share']:.0f}%** of the Mag-7 fresh-premium pool "
              f"and **{side}s control it** ({direction.lower()}). Buying the convexity.")
    spend = qty * price * 100
    fields = [
        {'name': 'Attention',
         'value': f"score **{row['attention_score']:.0f}** · rank **#{row['rank']}** · "
                  f"share **{100*row['share']:.0f}%**", 'inline': True},
        {'name': 'Control',
         'value': f"**{side}** · dominance {row['control_dominance']:.2f}", 'inline': True},
        {'name': 'Pool',
         'value': f"${board.get('total_premium', 0):,} fresh", 'inline': True},
        {'name': 'Contract',
         'value': f"{symbol} {strike:g}{side[0]} exp {expiry}" +
                  (f"\nspot ${spot:.2f}" if spot else ""), 'inline': True},
        {'name': 'Entry',
         'value': f"${price:.2f} × {qty}  =  ${spend:,.0f}", 'inline': True},
        {'name': '​', 'value': '​', 'inline': True},
        {'name': 'Exit plan', 'value': _exit_plan_text(), 'inline': False},
        {'name': 'Attention board', 'value': _board_table(board, highlight=symbol), 'inline': False},
    ]
    _post({
        'title': f"🟢 ENTER  {symbol} {side} {strike:g}",
        'description': thesis,
        'color': _GREEN if side == 'CALL' else _RED,
        'fields': fields,
        'footer': {'text': f"Jakenew Attention Engine · {_mode_tag(mode)}"},
        'timestamp': now.astimezone().isoformat(),
    }, signal_id=f"entry|{symbol}|{side}|{strike:g}|{expiry}|{now.isoformat()}")


def near_miss_card(*, sym: str, side: str, strike, route: str, score: float, threshold: float,
                   shortfall, value_state, qual_control, dist_prob, archetype, info_rank,
                   acceptance, top_drag: str, now: datetime) -> None:
    """🟡 RESEARCH-ONLY near-miss WATCH — a genuinely-scored candidate just under the execution
    boundary. Explicitly NOT a trade; collects live evidence on whether 0.50-0.54 events are tradeable."""
    fields = [
        {'name': 'Route score', 'value': f"**{score:.3f}** / {threshold:.3f}  (short {shortfall})", 'inline': True},
        {'name': 'Archetype', 'value': f"{archetype}\n`{route}`", 'inline': True},
        {'name': 'Top drag', 'value': top_drag or '—', 'inline': True},
        {'name': 'Qualified control', 'value': f"{100*(qual_control or 0):.0f}%", 'inline': True},
        {'name': 'Value', 'value': f"{value_state}", 'inline': True},
        {'name': 'Distribution', 'value': f"{(dist_prob or 0):.2f}", 'inline': True},
        {'name': 'Acceptance', 'value': f"{acceptance or '—'}", 'inline': True},
        {'name': 'Info-mass rank', 'value': f"#{info_rank}" if info_rank else '—', 'inline': True},
        {'name': '​', 'value': '​', 'inline': True},
    ]
    _post({
        'title': f"🟡 NEAR-MISS WATCH  {sym} {side} {strike:g}" if strike is not None else f"🟡 NEAR-MISS WATCH  {sym} {side}",
        'description': (f"High-quality event **{score:.3f}/{threshold:.3f}** — below the entry boundary. "
                        f"**RESEARCH ONLY — no order placed.** Watching whether this converts."),
        'color': _AMBER,
        'fields': fields,
        'footer': {'text': f"Jakenew · near-miss research alert (not an entry) · {RESEARCH_FOOTER}"},
        'timestamp': now.astimezone().isoformat(),
    })


def flip_card(*, ticker: str, from_side: str, to_side: str, events, strikes, reason: str,
              now: datetime) -> None:
    """🔄 P5 opposite-side FLIP hand-off — the ReversalCluster ACTIVATED and the incumbent exited; the
    opposite side is now FLIP_PENDING and must re-activate through the normal gates before it opens."""
    fields = [
        {'name': 'Flip', 'value': f"**{from_side} → {to_side}**", 'inline': True},
        {'name': 'Cluster events', 'value': f"{events if events is not None else '—'}", 'inline': True},
        {'name': 'Opp strikes', 'value': (', '.join(f"{s:g}" for s in (strikes or [])) or '—'), 'inline': True},
    ]
    _post({
        'title': f"🔄 FLIP PENDING  {ticker}  {from_side}→{to_side}",
        'description': (f"{reason}\n**Not an order** — the opposite side must recompute its ATM/best-"
                        f"convexity contract and pass the absolute + route + spot gates before it enters."),
        'color': _BLUE,
        'fields': fields,
        'footer': {'text': f"Jakenew · reversal flip hand-off (opposite entry is gated) · {RESEARCH_FOOTER}"},
        'timestamp': now.astimezone().isoformat(),
    })


def scale_card(pos: dict, *, sold: int, remaining: int, price: float, reason: str,
               pnl: float, mode: str, now: datetime) -> None:
    _post({
        'title': f"🟡 SCALE  {pos['symbol']} {pos['side']}  +{100*pnl:.0f}%",
        'description': f"Banked **{sold}** of {sold + remaining} contracts at the structural "
                       f"target; letting **{remaining}** run.",
        'color': _AMBER,
        'fields': [
            {'name': 'Sold', 'value': f"{sold} @ ${price:.2f}", 'inline': True},
            {'name': 'Remaining', 'value': f"{remaining} contract(s)", 'inline': True},
            {'name': 'P&L', 'value': f"+{100*pnl:.0f}%", 'inline': True},
            {'name': 'Held', 'value': _hold(pos.get('opened_at'), now), 'inline': True},
        ],
        'footer': {'text': f"Jakenew Attention Engine · {_mode_tag(mode)}"},
        'timestamp': now.astimezone().isoformat(),
    }, signal_id=f"scale|{pos['symbol']}|{pos['side']}|{pos.get('opened_at')}|{now.isoformat()}")


def exit_card(pos: dict, *, price: float, reason: str, pnl: float, mode: str,
              board: dict, now: datetime) -> None:
    """The reason we're out: objective met, or the thesis died (with where attention went)."""
    win = pnl >= 0
    new_leader = (board or {}).get('leader')
    to_leader = (f" to **{new_leader}**"
                 if (reason == 'ATTENTION_ROTATED_AWAY' and new_leader and new_leader != pos['symbol'])
                 else "")
    reason_text = _REASON_TEXT.get(reason, reason).format(to_leader=to_leader, leader=new_leader)
    entry = pos.get('entry_price')
    dollars = (price - entry) * pos.get('qty', 0) * 100 if entry else 0.0
    dollar_str = f"{'+' if dollars >= 0 else '-'}${abs(dollars):,.0f}"
    fields = [
        {'name': 'P&L',
         'value': f"**{'+' if win else ''}{100*pnl:.0f}%** ({dollar_str})", 'inline': True},
        {'name': 'Exit', 'value': f"${entry:.2f} → ${price:.2f}", 'inline': True},
        {'name': 'Held', 'value': _hold(pos.get('opened_at'), now), 'inline': True},
        {'name': 'Reason', 'value': reason_text, 'inline': False},
    ]
    row = (board.get('by_symbol') or {}).get(pos['symbol']) if board else None
    if row:
        fields.append({'name': 'Attention at exit',
                       'value': f"score {row['attention_score']:.0f} · rank #{row['rank']} · "
                                f"control {row.get('control_side') or '-'}", 'inline': False})
    if board and board.get('ranked'):
        fields.append({'name': 'Board now', 'value': _board_table(board, highlight=new_leader),
                       'inline': False})
    _post({
        'title': f"{'✅' if win else '🔴'} EXIT  {pos['symbol']} {pos['side']}  "
                 f"{'+' if win else ''}{100*pnl:.0f}%",
        'color': _GREEN if win else _RED,
        'fields': fields,
        'footer': {'text': f"Jakenew Attention Engine · {_mode_tag(mode)}"},
        'timestamp': now.astimezone().isoformat(),
    }, signal_id=f"exit|{pos['symbol']}|{pos['side']}|{pos.get('opened_at')}|{now.isoformat()}")
