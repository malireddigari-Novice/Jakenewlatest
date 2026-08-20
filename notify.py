"""
Discord notifications for the Attention Engine — rich embed "cards", not plain lines.

Every trade the engine takes is the output of the whole attention hierarchy, so the card
shows the *evidence*, not just the fill: the cross-symbol attention board (why THIS name won
the tape), the within-name control, the contract, and the exit plan. Exit cards close the
loop — P&L, hold time, and a plain-English reason (including where attention rotated to).

No-op when DISCORD_WEBHOOK_URL is unset, so the engine runs fine without it.
"""
import logging
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


# ── low-level ─────────────────────────────────────────────────────────────────

def _post(embed: dict) -> None:
    if not config.DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(config.DISCORD_WEBHOOK_URL, json={'embeds': [embed]}, timeout=10)
    except Exception as exc:
        logger.debug("notify: discord post failed: %s", exc)


def send(text: str) -> None:
    """Plain-content fallback (kept for ad-hoc messages)."""
    if not config.DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(config.DISCORD_WEBHOOK_URL, json={'content': text}, timeout=10)
    except Exception as exc:
        logger.debug("notify: discord post failed: %s", exc)


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
    })


def near_miss_card(*, sym: str, side: str, strike, route: str, score: float, threshold: float,
                   shortfall, value_state, qual_control, dist_prob, archetype, info_rank,
                   acceptance, top_drag: str, now: datetime) -> None:
    """🟡 RESEARCH-ONLY near-miss WATCH — a genuinely-scored candidate just under the execution
    boundary. Explicitly NOT a trade; collects live evidence on whether 0.50-0.54 events are tradeable."""
    fields = [
        {'name': 'Route score', 'value': f"**{score:.2f}** / {threshold:.2f}  (short {shortfall})", 'inline': True},
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
        'description': (f"High-quality event **{score:.2f}/{threshold:.2f}** — below the entry boundary. "
                        f"**RESEARCH ONLY — no order placed.** Watching whether this converts."),
        'color': _AMBER,
        'fields': fields,
        'footer': {'text': "Jakenew · near-miss research alert (not an entry)"},
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
    })


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
    })
