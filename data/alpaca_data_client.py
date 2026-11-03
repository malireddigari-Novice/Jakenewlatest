"""
Alpaca market-data client — the intraday feed for the Attention Engine.

Provides the two things the engine needs every poll:
  • the underlying spot (SIP stock feed), and
  • option snapshots near spot (OPRA): mark, CUMULATIVE day volume, day high/low, greeks.

The per-poll *delta* of cumulative volume is what `analysis.premium` turns into fresh
institutional premium — the pool the attention board allocates across the Mag-7.
"""
import email.utils
import logging
import threading
import time
from datetime import date, datetime, timedelta
from typing import Optional

import pytz
import requests

import config
from data.market_utils import CST

logger = logging.getLogger(__name__)

_DATA  = 'https://data.alpaca.markets'
_TRADE = ('https://paper-api.alpaca.markets' if config.ALPACA_PAPER
          else 'https://api.alpaca.markets')
_STOCK_FEED = 'sip'
# OPRA (full), NOT 'indicative' — the indicative snapshot is stale intraday (serves the
# prior session's bars) so cumulative volume never changes and every delta reads 0.
_OPT_FEED = 'opra'


class AlpacaDataClient:

    def __init__(self) -> None:
        self._h = {'APCA-API-KEY-ID': config.ALPACA_API_KEY,
                   'APCA-API-SECRET-KEY': config.ALPACA_SECRET_KEY}
        self._expiry_cache: dict[str, date] = {}
        self._expiry_cache_date: Optional[date] = None
        self._all_exp_cache: dict[str, list] = {}     # symbol -> sorted [date] (>= today), cached per day
        # Timing of the most recent successful response ON THIS THREAD (the engine fetches tickers in
        # parallel): local receipt epoch, and the server's HTTP Date (1 s resolution) — clock skew is visible.
        self._tl = threading.local()

    # ── helpers ────────────────────────────────────────────────────────────────

    def _get(self, base: str, path: str, params: dict) -> Optional[dict]:
        try:
            r = requests.get(f"{base}{path}", headers=self._h, params=params, timeout=20)
            r.raise_for_status()
            out = r.json()
            self._tl.recv_ts = time.time()
            try:
                self._tl.server_ts = email.utils.parsedate_to_datetime(r.headers['Date']).timestamp()
            except Exception:
                self._tl.server_ts = None
            return out
        except Exception as exc:
            logger.warning("Alpaca GET %s failed: %s", path, exc)
            return None

    @property
    def last_recv_ts(self) -> Optional[float]:
        return getattr(self._tl, 'recv_ts', None)

    @property
    def last_server_ts(self) -> Optional[float]:
        return getattr(self._tl, 'server_ts', None)

    @staticmethod
    def _cst(iso_z: str) -> datetime:
        return datetime.fromisoformat(iso_z.replace('Z', '+00:00')).astimezone(CST)

    def login(self) -> None:
        return None

    def verify(self) -> bool:
        j = self._get(_DATA, "/v2/stocks/AAPL/trades/latest", {'feed': _STOCK_FEED})
        ok = bool(j and j.get('trade'))
        logger.info("Alpaca data %s — SIP stock feed + OPRA options",
                    "ready" if ok else "verify FAILED")
        return ok

    # ── spot ────────────────────────────────────────────────────────────────────

    def get_spot(self, symbol: str) -> Optional[float]:
        """Latest trade price (fallback to quote mid), or None."""
        j = self._get(_DATA, f"/v2/stocks/{symbol}/trades/latest", {'feed': _STOCK_FEED})
        if j and j.get('trade') and j['trade'].get('p'):
            return float(j['trade']['p'])
        q = self._get(_DATA, f"/v2/stocks/{symbol}/quotes/latest", {'feed': _STOCK_FEED})
        if q and q.get('quote'):
            bp, ap = q['quote'].get('bp'), q['quote'].get('ap')
            if bp and ap:
                return (float(bp) + float(ap)) / 2
        return None

    # ── expiry discovery ─────────────────────────────────────────────────────────

    def _all_expiries(self, symbol: str) -> list:
        """Sorted list of listed expiries (>= today), cached once per day per symbol."""
        today = date.today()
        if self._expiry_cache_date != today:
            self._expiry_cache.clear(); self._all_exp_cache.clear()
            self._expiry_cache_date = today
        if symbol in self._all_exp_cache:
            return self._all_exp_cache[symbol]
        j = self._get(_TRADE, "/v2/options/contracts",
                      {'underlying_symbols': symbol, 'expiration_date_gte': today.isoformat(),
                       'type': 'call', 'limit': 1000})
        exps = sorted({date.fromisoformat(c['expiration_date'])
                       for c in (j or {}).get('option_contracts', [])})
        self._all_exp_cache[symbol] = exps
        return exps

    def get_nearest_expiry(self, symbol: str) -> Optional[date]:
        if symbol in self._expiry_cache and self._expiry_cache_date == date.today():
            return self._expiry_cache[symbol]
        exps = self._all_expiries(symbol)
        if not exps:
            return None
        self._expiry_cache[symbol] = exps[0]
        logger.debug("Alpaca: %s nearest expiry = %s", symbol, exps[0])
        return exps[0]

    def get_scan_expiries(self, symbol: str, max_expiries: int = 4) -> list:
        """Relevant expiries for multi-expiration scanning (spec §8): the nearest (0DTE if listed),
        the nearest strictly-future expiry, the current-week Friday, and the following weekly."""
        today = date.today()
        exps = self._all_expiries(symbol)
        if not exps:
            return []
        picks = [exps[0]]
        nz = next((e for e in exps if e > today), None)
        if nz:
            picks.append(nz)
        fri = today + timedelta(days=(4 - today.weekday()) % 7)          # this week's Friday
        for target in (fri, fri + timedelta(days=7)):
            match = next((e for e in exps if e == target), None)
            if match:
                picks.append(match)
        picks = sorted(set(picks))
        return picks[:max_expiries] if max_expiries else picks

    # ── option snapshots near spot (the fresh-premium source) ─────────────────────

    def get_option_snapshots(self, symbol: str, expiry: date, spot: float,
                             band_pct: float = None) -> dict:
        """
        Every contract within ±band_pct of spot for `expiry`, keyed by (strike, side):
          {bid, ask, mark, volume (CUMULATIVE day), day_high, day_low, delta, gamma, iv}

        `volume` is the running session total; the caller diffs it against the prior poll
        to recover this minute's FRESH contracts. open_interest is unavailable from Alpaca.
        """
        band = band_pct if band_pct is not None else config.PREMIUM_BAND_PCT
        lo, hi = spot * (1 - band * 1.5), spot * (1 + band * 1.5)
        snaps: dict = {}
        page = None
        while True:
            params = {'feed': _OPT_FEED, 'limit': 1000,
                      'expiration_date': expiry.isoformat(),
                      'strike_price_gte': round(lo, 2), 'strike_price_lte': round(hi, 2)}
            if page:
                params['page_token'] = page
            j = self._get(_DATA, f"/v1beta1/options/snapshots/{symbol}", params)
            if not j:
                break
            snaps.update(j.get('snapshots') or {})
            page = j.get('next_page_token')
            if not page:
                break

        parsed: dict = {}
        for occ, s in snaps.items():
            p = _parse_occ(occ)
            if not p:
                continue
            _sym, strike, ot = p
            q  = s.get('latestQuote') or {}
            db = s.get('dailyBar') or {}
            tr = s.get('latestTrade') or {}
            g  = s.get('greeks') or {}
            bid, ask = q.get('bp'), q.get('ap')
            mark = ((float(bid) + float(ask)) / 2) if (bid and ask) else (
                float(tr['p']) if tr.get('p') else None)
            raw_iv = s.get('impliedVolatility')
            parsed[(strike, ot)] = {
                'bid':          float(bid) if bid else None,
                'ask':          float(ask) if ask else None,
                'mark':         mark,
                'bid_size':     int(q.get('bs', 0) or 0),   # book depth (contracts) — liquidity gate
                'ask_size':     int(q.get('as', 0) or 0),
                'quote_ts':     q.get('t'),                 # ISO ts of the quote — staleness gate
                'volume':       int(db.get('v', 0) or 0),   # cumulative day volume
                'day_high':     float(db['h']) if db.get('h') else None,
                'day_low':      float(db['l']) if db.get('l') else None,
                'delta':        g.get('delta'),
                'gamma':        g.get('gamma'),
                'implied_vol':  float(raw_iv) if raw_iv is not None else None,
                # newest print + prior-session volume (campaign-flow window adapter)
                'trade_px':     float(tr['p']) if tr.get('p') else None,
                'trade_ts':     tr.get('t'),
                'trade_size':   int(tr.get('s') or 0) if tr else None,
                'trade_cond':   tr.get('c'),
                'prev_volume':  int((s.get('prevDailyBar') or {}).get('v') or 0),
            }
        return parsed


# ── module helper ─────────────────────────────────────────────────────────────

def _parse_occ(occ: str) -> Optional[tuple[str, float, str]]:
    """OCC ticker → (underlying, strike, 'CALL'|'PUT'). None if malformed."""
    try:
        strike = int(occ[-8:]) / 1000.0
        cp = occ[-9]
        return occ[:-15], strike, ('CALL' if cp == 'C' else 'PUT')
    except Exception:
        return None
