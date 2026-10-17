"""Alpaca REST access for the tape lane: contract master + dated OI, daily option bars, historical option
trades (backfill / bootstrap), SIP stock trades (spot backfill) and the condition-code definitions.
Historical option QUOTES do not exist on Alpaca (verified 2026-10-17: 404) — quotes are live-only."""
import logging
import time

import requests

import config

logger = logging.getLogger(__name__)

DATA = 'https://data.alpaca.markets'
TRADE = 'https://paper-api.alpaca.markets' if config.ALPACA_PAPER else 'https://api.alpaca.markets'


class Rest:

    def __init__(self) -> None:
        self._h = {'APCA-API-KEY-ID': config.ALPACA_API_KEY, 'APCA-API-SECRET-KEY': config.ALPACA_SECRET_KEY}
        self.pages = 0

    def _get(self, base, path, params, tries=4):
        for i in range(tries):
            try:
                r = requests.get(base + path, headers=self._h, params=params, timeout=30)
                self.pages += 1
                if r.status_code == 429:
                    time.sleep(float(r.headers.get('Retry-After') or 2 ** i))
                    continue
                if r.status_code >= 500:
                    time.sleep(2 ** i)
                    continue
                r.raise_for_status()
                return r.json()
            except requests.RequestException as exc:
                if i == tries - 1:
                    raise
                logger.debug("rest retry %s: %s", path, exc)
                time.sleep(2 ** i)
        raise RuntimeError(f"REST {path} failed after {tries} tries")

    def _pages(self, base, path, params, key):
        token = None
        while True:
            p = dict(params, **({'page_token': token} if token else {}))
            j = self._get(base, path, p)
            yield j.get(key) or ({} if isinstance(j.get(key), dict) else [])
            token = j.get('next_page_token')
            if not token:
                return

    def conditions(self) -> dict:
        return self._get(DATA, '/v1beta1/options/meta/conditions/trade', {})

    def contracts(self, underlying, exp_gte, exp_lte, strike_lo, strike_hi) -> list:
        out = []
        for page in self._pages(TRADE, '/v2/options/contracts', {
                'underlying_symbols': underlying, 'expiration_date_gte': exp_gte, 'expiration_date_lte': exp_lte,
                'strike_price_gte': strike_lo, 'strike_price_lte': strike_hi, 'status': 'active', 'limit': 1000},
                'option_contracts'):
            out.extend(page)
        return out

    def daily_bars(self, symbols, start, end) -> dict:
        out = {}
        for i in range(0, len(symbols), 100):
            for page in self._pages(DATA, '/v1beta1/options/bars', {
                    'symbols': ','.join(symbols[i:i + 100]), 'timeframe': '1Day', 'start': start, 'end': end,
                    'limit': 10000}, 'bars'):
                for k, v in page.items():
                    out.setdefault(k, []).extend(v)
        return out

    def option_trades(self, symbols, start_iso, end_iso, max_pages=None):
        """Yields (occ, row) for every historical trade; stops early when max_pages is reached and
        reports completeness via the returned generator's StopIteration value (see `complete`)."""
        self.complete = True
        n = 0
        for i in range(0, len(symbols), 100):
            for page in self._pages(DATA, '/v1beta1/options/trades', {
                    'symbols': ','.join(symbols[i:i + 100]), 'start': start_iso, 'end': end_iso,
                    'limit': 10000, 'sort': 'asc'}, 'trades'):
                n += 1
                for occ, rows in page.items():
                    for r in rows:
                        yield occ, r
                if max_pages and n >= max_pages:
                    self.complete = False
                    return

    def stock_trades(self, symbol, start_iso, end_iso) -> list:
        out = []
        for page in self._pages(DATA, f'/v2/stocks/{symbol}/trades', {
                'start': start_iso, 'end': end_iso, 'feed': 'sip', 'limit': 10000}, 'trades'):
            out.extend(page)
        return out

    def last_stock_trade(self, symbol):
        return (self._get(DATA, f'/v2/stocks/{symbol}/trades/latest', {'feed': 'sip'}) or {}).get('trade')
