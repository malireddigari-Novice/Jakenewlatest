"""
Alpaca brokerage client — executes the single convexity trade the Attention Engine picks.

Paper vs live via ALPACA_PAPER (default paper). Execution is OFF until ALPACA_ENABLED=true.
On a KEEP from the attention gate:
  BULLISH (call control) → buy the ATM CALL   |   BEARISH (put control) → buy the ATM PUT
Qty = floor(TRADE_PCT * portfolio_value / (limit_price * 100)).
"""
import logging
from datetime import date
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)

_PAPER_URL = 'https://paper-api.alpaca.markets'
_LIVE_URL  = 'https://api.alpaca.markets'


class AlpacaClient:

    def __init__(self) -> None:
        self._base = _PAPER_URL if config.ALPACA_PAPER else _LIVE_URL
        self._headers = {
            'APCA-API-KEY-ID':     config.ALPACA_API_KEY,
            'APCA-API-SECRET-KEY': config.ALPACA_SECRET_KEY,
            'Content-Type':        'application/json',
        }

    # ── account ────────────────────────────────────────────────────────────────

    def verify(self) -> bool:
        try:
            r = requests.get(f"{self._base}/v2/account", headers=self._headers, timeout=10)
            r.raise_for_status()
            acct = r.json()
            logger.info("Alpaca %s — buying_power=$%.2f  portfolio_value=$%.2f",
                        "PAPER" if config.ALPACA_PAPER else "LIVE",
                        float(acct.get('buying_power', 0)), float(acct.get('portfolio_value', 0)))
            return True
        except Exception as exc:
            logger.error("Alpaca: verify failed: %s", exc)
            return False

    def portfolio_value(self) -> float:
        try:
            r = requests.get(f"{self._base}/v2/account", headers=self._headers, timeout=10)
            r.raise_for_status()
            return float(r.json().get('portfolio_value', 0))
        except Exception as exc:
            logger.warning("Alpaca: could not fetch portfolio value: %s", exc)
            return 0.0

    def open_position_count(self) -> int:
        try:
            r = requests.get(f"{self._base}/v2/positions", headers=self._headers, timeout=10)
            r.raise_for_status()
            return len(r.json())
        except Exception as exc:
            logger.warning("Alpaca: could not fetch positions: %s", exc)
            return 0

    def position(self, occ: str) -> Optional[dict]:
        """Open position for an OCC symbol, or None (404 = not held / unfilled)."""
        try:
            r = requests.get(f"{self._base}/v2/positions/{occ}", headers=self._headers, timeout=10)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            p = r.json()
            return {
                'occ':             p.get('symbol'),
                'qty':             int(float(p.get('qty', 0) or 0)),
                'avg_entry_price': float(p.get('avg_entry_price', 0) or 0),
                'current_price':   float(p.get('current_price', 0) or 0),
                'unrealized_pl':   float(p.get('unrealized_pl', 0) or 0),
                'unrealized_plpc': float(p.get('unrealized_plpc', 0) or 0),
            }
        except Exception as exc:
            logger.warning("Alpaca: could not fetch position for %s: %s", occ, exc)
            return None

    # ── sizing ─────────────────────────────────────────────────────────────────

    def calculate_qty(self, limit_price: float) -> tuple[int, float]:
        """(contracts, dollars) using TRADE_PCT of portfolio value. One contract = 100 shares."""
        pv = self.portfolio_value()
        if pv <= 0 or limit_price <= 0:
            return 0, 0.0
        budget = pv * config.TRADE_PCT
        qty    = int(budget / (limit_price * 100))
        spend  = qty * limit_price * 100
        logger.info("Alpaca: sizing pv=$%.2f budget=%.1f%%=$%.2f limit=$%.2f → qty=%d spend=$%.2f",
                    pv, config.TRADE_PCT * 100, budget, limit_price, qty, spend)
        return qty, spend

    # ── orders ─────────────────────────────────────────────────────────────────

    def place_option_order(self, symbol: str, expiry: date, strike: float,
                           option_type: str, qty: int, limit_price: float) -> Optional[dict]:
        """Buy-to-open limit day order. Returns the Alpaca order dict, or None on failure."""
        occ = occ_symbol(symbol, expiry, strike, option_type)
        payload = {'symbol': occ, 'qty': str(qty), 'side': 'buy', 'type': 'limit',
                   'time_in_force': 'day', 'limit_price': f"{limit_price:.2f}",
                   'order_class': 'simple'}
        return self._post_order(payload, f"BUY {occ} x{qty} @${limit_price:.2f}")

    def close_position_qty(self, occ: str, qty: int) -> Optional[dict]:
        """Market-sell `qty` contracts (partial or full exit)."""
        payload = {'symbol': occ, 'qty': str(qty), 'side': 'sell',
                   'type': 'market', 'time_in_force': 'day'}
        return self._post_order(payload, f"SELL {occ} x{qty}")

    def close_all_positions(self) -> int:
        try:
            r = requests.delete(f"{self._base}/v2/positions", headers=self._headers,
                                params={'cancel_orders': 'true'}, timeout=15)
            if r.status_code in (200, 204, 207):
                count = len(r.json()) if r.status_code == 207 else 0
                logger.info("Alpaca: EOD liquidation — closed %d position(s)", count)
                return count
            r.raise_for_status()
            return 0
        except Exception as exc:
            logger.error("Alpaca: EOD liquidation failed: %s", exc)
            return 0

    # ── campaign-flow order primitives (idempotent client_order_id) ─────────────

    def submit_limit(self, occ: str, side: str, qty: int, limit_price: float,
                     client_order_id: str) -> Optional[dict]:
        """Day LIMIT order with a caller-chosen client_order_id (Alpaca rejects a reused id, so a retry
        after a crash cannot create a second order)."""
        payload = {'symbol': occ, 'qty': str(qty), 'side': side, 'type': 'limit', 'time_in_force': 'day',
                   'limit_price': f"{limit_price:.2f}", 'client_order_id': client_order_id}
        return self._post_order(payload, f"{side.upper()} {occ} x{qty} @${limit_price:.2f} [{client_order_id}]")

    def get_order_by_client_id(self, client_order_id: str) -> Optional[dict]:
        try:
            r = requests.get(f"{self._base}/v2/orders:by_client_order_id", headers=self._headers,
                             params={'client_order_id': client_order_id}, timeout=10)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            logger.warning("Alpaca: order lookup failed for %s: %s", client_order_id, exc)
            return None

    def cancel_order(self, order_id: str) -> bool:
        try:
            r = requests.delete(f"{self._base}/v2/orders/{order_id}", headers=self._headers, timeout=10)
            return r.status_code in (200, 204, 422)        # 422 = already filled/cancelled
        except Exception as exc:
            logger.warning("Alpaca: cancel failed for %s: %s", order_id, exc)
            return False

    def _post_order(self, payload: dict, label: str) -> Optional[dict]:
        try:
            r = requests.post(f"{self._base}/v2/orders", json=payload,
                              headers=self._headers, timeout=10)
            r.raise_for_status()
            order = r.json()
            logger.info("Alpaca: ORDER %s  id=%s", label, order.get('id', '?')[:8])
            return order
        except Exception as exc:
            body = getattr(getattr(exc, 'response', None), 'text', '') or ''
            logger.error("Alpaca: order FAILED (%s): %s  %s", label, exc, body[:300])
            return None


# ── OCC helpers ────────────────────────────────────────────────────────────────

def occ_symbol(symbol: str, expiry: date, strike: float, option_type: str) -> str:
    """{SYMBOL}{YYMMDD}{C|P}{strike*1000:08d}. AAPL 2026-05-27 305C → AAPL260527C00305000"""
    date_s = expiry.strftime('%y%m%d')
    cp     = 'C' if option_type == 'CALL' else 'P'
    return f"{symbol}{date_s}{cp}{int(round(strike * 1000)):08d}"


def parse_occ_symbol(occ: str) -> tuple:
    """Inverse: OCC ticker → (underlying, expiry_date, 'CALL'|'PUT', strike)."""
    strike = int(occ[-8:]) / 1000.0
    cp     = occ[-9]
    yy, mm, dd = int(occ[-15:-13]), int(occ[-13:-11]), int(occ[-11:-9])
    return occ[:-15], date(2000 + yy, mm, dd), ('CALL' if cp == 'C' else 'PUT'), strike
