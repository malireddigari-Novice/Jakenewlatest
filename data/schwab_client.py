"""
Charles Schwab option-chain client — OI / structural context (optional).

Alpaca drives the intraday attention loop; Schwab is the only source of live OPEN
INTEREST, which backs the *structural* exit objective (Layer 4-A: "did we reach the
OI-derived target?"). The engine runs fine on Alpaca alone — if the Schwab token has
expired, `login()` logs a warning and every method degrades to empty/None.

Setup (one-time)
----------------
1. Register a developer app at developer.schwab.com; callback URL https://127.0.0.1.
2. Client ID → SCHWAB_API_KEY, Secret → SCHWAB_APP_SECRET in .env.
3. python schwab_reauth.py   (opens a browser; token saved to SCHWAB_TOKEN_FILE).
The refresh token expires ~weekly → re-run schwab_reauth.py when quotes stop working.
"""
import logging
import random
import time
from datetime import date, timedelta
from typing import Optional

import schwab
import schwab.client

import config

logger = logging.getLogger(__name__)


class SchwabClient:

    def __init__(self) -> None:
        self._client: Optional[schwab.client.Client] = None

    # ── auth ────────────────────────────────────────────────────────────────────

    def login(self) -> bool:
        """Load (and auto-refresh) the saved token. Returns True if usable."""
        if not config.SCHWAB_API_KEY or not config.SCHWAB_APP_SECRET:
            logger.warning("Schwab: credentials missing — OI/structural context disabled.")
            return False
        try:
            self._client = schwab.auth.client_from_token_file(
                config.SCHWAB_TOKEN_FILE, config.SCHWAB_API_KEY, config.SCHWAB_APP_SECRET)
            logger.info("Schwab: token loaded from %s", config.SCHWAB_TOKEN_FILE)
            return True
        except Exception as exc:
            logger.warning("Schwab: token load failed (%s) — run schwab_reauth.py. "
                           "Continuing without OI.", exc)
            self._client = None
            return False

    def login_manual(self) -> None:
        """Interactive browser OAuth (used by schwab_reauth.py)."""
        self._client = schwab.auth.client_from_manual_flow(
            api_key=config.SCHWAB_API_KEY, app_secret=config.SCHWAB_APP_SECRET,
            callback_url=config.SCHWAB_CALLBACK_URL, token_path=config.SCHWAB_TOKEN_FILE)
        logger.info("Schwab: token saved to %s", config.SCHWAB_TOKEN_FILE)

    @property
    def ready(self) -> bool:
        return self._client is not None

    # ── public API ──────────────────────────────────────────────────────────────

    def get_quote(self, symbol: str) -> Optional[float]:
        if not self._client:
            return None
        try:
            resp = self._client.get_quote(symbol)
            resp.raise_for_status()
            q = resp.json()[symbol]['quote']
            price = q.get('lastPrice') or q.get('closePrice')
            return float(price) if price is not None else None
        except Exception as exc:
            logger.warning("Schwab: get_quote failed for %s: %s", symbol, exc)
            return None

    def get_option_chain_full(self, symbol: str, expiry: date = None) -> dict:
        """
        Parsed chain keyed by (strike, 'CALL'|'PUT') → {bid, ask, mark, volume,
        open_interest, delta, gamma, implied_vol}. Empty dict on any error.
        """
        raw = self._get_option_chain(symbol, expiry)
        return _parse_chain(raw) if raw else {}

    def get_oi_by_side(self, symbol: str, expiry: date = None) -> dict:
        """
        {(strike, side): open_interest} for one expiry — the OI map the structural
        exit uses to locate a take-profit magnet (the near strike with the largest OI).
        """
        chain = self.get_option_chain_full(symbol, expiry)
        return {k: v.get('open_interest', 0) for k, v in chain.items()}

    # ── internal ────────────────────────────────────────────────────────────────

    def _get_option_chain(self, symbol: str, expiry: Optional[date] = None,
                          max_retries: int = 4, days: int = 7) -> Optional[dict]:
        if not self._client:
            return None
        for attempt in range(max_retries):
            try:
                if expiry:
                    from_date = to_date = expiry
                else:
                    from_date = date.today()
                    to_date = from_date + timedelta(days=days)
                resp = self._client.get_option_chain(
                    symbol, contract_type=schwab.client.Client.Options.ContractType.ALL,
                    from_date=from_date, to_date=to_date)
                resp.raise_for_status()
                data = resp.json()
                if data.get('status') != 'SUCCESS':
                    logger.warning("Schwab: chain status=%s for %s", data.get('status'), symbol)
                    return None
                return data
            except Exception as exc:
                msg = str(exc).lower()
                if ('429' in msg or 'rate limit' in msg) and attempt < max_retries - 1:
                    wait = (2 ** attempt) + random.random()
                    logger.warning("Schwab rate limit for %s, retry in %.1fs", symbol, wait)
                    time.sleep(wait)
                else:
                    logger.warning("Schwab: chain fetch failed for %s: %s", symbol, exc)
                    return None
        return None


def _parse_chain(data: dict) -> dict:
    """Flatten Schwab call/put ExpDateMaps → {(strike, side): {...}} (nearest expiry inclusive)."""
    result: dict = {}
    for opt_type, exp_map in (('CALL', data.get('callExpDateMap', {})),
                              ('PUT',  data.get('putExpDateMap',  {}))):
        for _date_dte, strikes_map in exp_map.items():
            for strike_str, contracts in strikes_map.items():
                if not contracts:
                    continue
                c = contracts[0]
                raw_iv = c.get('volatility')
                result[(float(strike_str), opt_type)] = {
                    'bid':           c.get('bid'),
                    'ask':           c.get('ask'),
                    'mark':          c.get('mark'),
                    'volume':        int(c.get('totalVolume', 0) or 0),
                    'open_interest': int(c.get('openInterest', 0) or 0),
                    'delta':         c.get('delta'),
                    'gamma':         c.get('gamma'),
                    'implied_vol':   (float(raw_iv) / 100.0) if raw_iv is not None else None,
                }
    return result
