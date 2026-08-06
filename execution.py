"""
Execution controls — "buy at the current ask" is not sufficient for live options.

Before any order (and even in SHADOW, so the recorded fill is realistic) an entry must clear
liquidity/spread/staleness guards, price with a bounded LIMIT (mid + a small offset, never a
naked market-through-the-ask), respect a max-slippage abort if the quote moved, and be
protected against duplicate submissions. Fill/position reconciliation is delegated to the
broker client (the source of truth).
"""
import logging
from datetime import datetime

import config

logger = logging.getLogger(__name__)


def quote_age_seconds(quote_ts, now) -> float:
    """Age of a quote in seconds from its ISO timestamp; large number if unknown/unparseable."""
    if not quote_ts:
        return 999.0
    try:
        q = datetime.fromisoformat(str(quote_ts).replace('Z', '+00:00'))
        return max(0.0, (now.astimezone(q.tzinfo) - q).total_seconds())
    except Exception:
        return 999.0


def spread_pct(bid, ask, mark) -> float:
    if not bid or not ask or not mark or mark <= 0 or ask <= bid:
        return 1.0
    return (float(ask) - float(bid)) / float(mark)


def check_executable(contract: dict, now) -> tuple:
    """
    (ok, reason) — is this contract's book good enough to send an order into right now?
    Guards: spread, quote size (both sides), and quote staleness.
    """
    bid, ask, mark = contract.get('bid'), contract.get('ask'), contract.get('mark')
    if spread_pct(bid, ask, mark) > config.EXEC_MAX_SPREAD_PCT:
        return False, 'SPREAD_TOO_WIDE'
    if min(contract.get('bid_size') or 0, contract.get('ask_size') or 0) < config.EXEC_MIN_QUOTE_SIZE:
        return False, 'BOOK_TOO_THIN'
    if quote_age_seconds(contract.get('quote_ts'), now) > config.GATE_MAX_QUOTE_STALE_S:
        return False, 'QUOTE_STALE'
    return True, 'OK'


def limit_price(contract: dict) -> float | None:
    """
    Bounded buy limit: mid × (1 + EXEC_LIMIT_OFFSET_PCT), never worse than the ask, never below
    the bid. Gives a realistic fill without chasing straight through the offer.
    """
    bid, ask, mark = contract.get('bid'), contract.get('ask'), contract.get('mark')
    if mark and mark > 0:
        px = float(mark) * (1 + config.EXEC_LIMIT_OFFSET_PCT)
    elif ask:
        px = float(ask)
    else:
        return None
    if ask:
        px = min(px, float(ask))
    if bid:
        px = max(px, float(bid))
    return round(px, 2)


def slippage_ok(intended_mark: float, current_mark: float) -> bool:
    """Abort if the mark moved beyond EXEC_MAX_SLIPPAGE_PCT between decision and submission."""
    if not intended_mark or intended_mark <= 0 or current_mark is None:
        return True
    return abs(current_mark - intended_mark) / intended_mark <= config.EXEC_MAX_SLIPPAGE_PCT


class OrderManager:
    """Thin wrapper adding duplicate-order protection + fill reconciliation over AlpacaClient."""

    def __init__(self, alpaca_exec=None) -> None:
        self.exec = alpaca_exec
        self._pending: set = set()   # OCC symbols with an in-flight buy this session

    def submit_entry(self, occ: str, symbol, expiry, strike, side, qty, limit) -> dict | None:
        if occ in self._pending:
            logger.info("execution: duplicate entry suppressed for %s", occ)
            return None
        if not (self.exec and config.ALPACA_ENABLED):
            return {'shadow': True, 'occ': occ, 'qty': qty, 'limit_price': limit}
        self._pending.add(occ)
        order = self.exec.place_option_order(symbol, expiry, strike, side, qty, limit)
        if order is None:
            self._pending.discard(occ)
        return order

    def clear(self, occ: str) -> None:
        self._pending.discard(occ)

    def reconcile(self, occ: str) -> dict | None:
        """Broker's ground truth for a position (None = not held / unfilled)."""
        if self.exec and config.ALPACA_ENABLED:
            return self.exec.position(occ)
        return None
