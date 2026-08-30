"""
Google Sheets trade log for Jakenew — ported from Jakevolume/output/sheets_logger.py.

Why this exists
---------------
Jakenew had no Sheets integration, so the shared "Trading Log" spreadsheet never updated with
Jakenew's trades — only Jakevolume fed it. This module reuses the SAME service-account credentials
and the SAME spreadsheet, but writes to a Jakenew-specific worksheet (config.SHEET_NAMES['trades'],
default 'Jakenew_Trades'), so both engines can share one workbook without colliding.

Auth
----
Google Cloud service-account JSON key at config.GOOGLE_SERVICE_ACCOUNT_FILE. The target
spreadsheet (config.GOOGLE_SPREADSHEET_ID) must be shared with the service-account email (editor).

Concurrency / rate limiting (unchanged from Jakevolume)
-------------------------------------------------------
Every public log_* method is non-blocking: it enqueues a (sheet_key, row) task and returns. A single
background daemon thread serialises the actual API calls, throttled to stay under the Sheets write
quota, with exponential back-off on HTTP 429 — so the ~5s trading loop is never stalled by Sheets I/O.
"""
import logging
import queue
import random
import threading
import time
from datetime import datetime

import config
from data.market_utils import CST

logger = logging.getLogger(__name__)

_SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]

# One row per trade EVENT (ENTRY / SCALE / EXIT), newest inserted at the top (row 2).
_HDR_TRADES = [
    'Date', 'Time_CST', 'Event', 'Mode',
    'Symbol', 'Side', 'OCC_Symbol', 'Strike', 'Expiry', 'Qty',
    'Entry_Price', 'Exit_Price', 'PnL_%', 'Reason', 'Exit_Category',
    'Wave_ID', 'Archetype', 'Campaign_Score', 'Posterior', 'Dist_Prob', 'EV',
    'Hold_s', 'MFE_%', 'MAE_%', 'Order_ID',
]

_HEADERS = {config.SHEET_NAMES['trades']: _HDR_TRADES}


class SheetsLogger:

    def __init__(self) -> None:
        # gspread is imported here so a missing dependency degrades to a clear error at
        # construction time (the engine catches it) rather than at module import.
        import gspread                                     # noqa: F401
        self._gspread = gspread
        self._gc = None
        self._ss = None
        self._ws_cache: dict = {}
        self._write_queue: queue.Queue = queue.Queue()
        self._last_write_ts = 0.0
        self._worker = threading.Thread(target=self._drain_queue, name='sheets-writer', daemon=True)
        self._worker.start()

    # ── connection ──────────────────────────────────────────────────────────────
    def connect(self, max_retries: int = 4) -> None:
        from google.oauth2.service_account import Credentials
        if not config.GOOGLE_SPREADSHEET_ID:
            raise RuntimeError("GOOGLE_SPREADSHEET_ID is not set")
        for attempt in range(max_retries):
            try:
                creds = Credentials.from_service_account_file(
                    config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=_SCOPES)
                self._gc = self._gspread.authorize(creds)
                self._ss = self._gc.open_by_key(config.GOOGLE_SPREADSHEET_ID)
                for sheet_key in config.SHEET_NAMES:                 # ensure the tab + header exist
                    ws = self._ws(sheet_key)
                    headers = _HEADERS.get(config.SHEET_NAMES[sheet_key], [])
                    if headers:
                        ws.update([headers], 'A1')
                logger.info("Google Sheets connected: %s (tab '%s')",
                            self._ss.title, config.SHEET_NAMES['trades'])
                return
            except Exception as exc:
                if attempt < max_retries - 1:
                    wait = (2 ** attempt) + random.random()
                    logger.warning("Sheets connect failed (attempt %d/%d), retrying in %.1fs: %s",
                                   attempt + 1, max_retries, wait, exc)
                    time.sleep(wait)
                else:
                    raise

    # ── public logging (all non-blocking) ─────────────────────────────────────────
    def log_trade_entry(self, pos: dict, *, mode: str) -> None:
        """Enqueue an ENTRY row from a Jakenew held-position dict."""
        self._enqueue('trades', self._row('ENTRY', mode, pos, entry_price=pos.get('entry_price')))
        logger.info("Sheets: queued ENTRY %s %s x%s @ %s", pos.get('symbol'), pos.get('side'),
                    pos.get('qty'), pos.get('entry_price'))

    def log_trade_scale(self, pos: dict, *, sold, price, reason, pnl, mode: str) -> None:
        """Enqueue a SCALE (partial exit) row."""
        self._enqueue('trades', self._row('SCALE', mode, pos, exit_price=price, reason=reason,
                                          pnl=pnl, qty=sold))
        logger.info("Sheets: queued SCALE %s %s sold=%s @ %s", pos.get('symbol'), pos.get('side'),
                    sold, price)

    def log_trade_exit(self, pos: dict, *, price, reason, pnl, mode: str,
                       category='', hold_s=None, mfe=None, mae=None) -> None:
        """Enqueue an EXIT (full close) row."""
        self._enqueue('trades', self._row('EXIT', mode, pos, exit_price=price, reason=reason,
                                          pnl=pnl, category=category, hold_s=hold_s, mfe=mfe, mae=mae))
        logger.info("Sheets: queued EXIT %s %s @ %s (%s %+.0f%%)", pos.get('symbol'),
                    pos.get('side'), price, reason, 100 * (pnl or 0.0))

    # ── row construction ──────────────────────────────────────────────────────────
    def _row(self, event, mode, pos, *, entry_price=None, exit_price=None, reason='',
             category='', pnl=None, qty=None, hold_s=None, mfe=None, mae=None) -> list:
        now = datetime.now(CST)
        d = {
            'Date': now.strftime('%Y-%m-%d'), 'Time_CST': now.strftime('%H:%M:%S'),
            'Event': event, 'Mode': mode,
            'Symbol': pos.get('symbol', ''), 'Side': pos.get('side', ''),
            'OCC_Symbol': pos.get('occ', ''), 'Strike': pos.get('strike', ''),
            'Expiry': pos.get('expiry', ''), 'Qty': qty if qty is not None else pos.get('qty', ''),
            'Entry_Price': entry_price if entry_price is not None else pos.get('entry_price', ''),
            'Exit_Price': exit_price if exit_price is not None else '',
            'PnL_%': round(pnl * 100, 1) if pnl is not None else '',
            'Reason': reason, 'Exit_Category': category,
            'Wave_ID': pos.get('wave_id', ''), 'Archetype': pos.get('archetype') or '',
            'Campaign_Score': pos.get('campaign_score', ''), 'Posterior': pos.get('posterior', ''),
            'Dist_Prob': pos.get('dist_prob', ''), 'EV': pos.get('ev', ''),
            'Hold_s': hold_s if hold_s is not None else '',
            'MFE_%': round(mfe * 100, 1) if mfe is not None else '',
            'MAE_%': round(mae * 100, 1) if mae is not None else '',
            'Order_ID': str(pos.get('order_id', ''))[:8],
        }
        return [d.get(col, '') for col in _HDR_TRADES]

    # ── internal queue / write ─────────────────────────────────────────────────────
    def _enqueue(self, sheet_key, row) -> None:
        self._write_queue.put((sheet_key, row))

    def _drain_queue(self) -> None:
        while True:
            sheet_key, row = self._write_queue.get()
            wait = config.SHEETS_MIN_WRITE_INTERVAL - (time.monotonic() - self._last_write_ts)
            if wait > 0:
                time.sleep(wait)
            try:
                self._insert_row(sheet_key, row)
            except Exception:
                logger.exception("Sheets background write failed for '%s'", sheet_key)
            finally:
                self._last_write_ts = time.monotonic()
                self._write_queue.task_done()

    # Google Sheets returns 429 (rate limit) and transient 5xx (500/502/503/504 — "service
    # unavailable") that succeed on a retry. A 503 was silently dropping a trade row because only 429
    # was retried; retry both so a momentary Google outage never loses an ENTRY/SCALE/EXIT row.
    _RETRYABLE = (429, 500, 502, 503, 504)

    def _insert_row(self, sheet_key, row, max_retries: int = 6) -> None:
        ws = self._ws(sheet_key)
        for attempt in range(max_retries):
            try:
                ws.insert_row(row, index=2, value_input_option='USER_ENTERED')
                return
            except self._gspread.exceptions.APIError as exc:
                status = getattr(exc.response, 'status_code', None)
                if status in self._RETRYABLE and attempt < max_retries - 1:
                    wait = min(30.0, (2 ** attempt) + random.random())
                    logger.warning("Sheets write %s (attempt %d/%d) — retrying in %.1fs",
                                   status, attempt + 1, max_retries, wait)
                    time.sleep(wait)
                else:
                    raise

    def _ws(self, sheet_key):
        name = config.SHEET_NAMES[sheet_key]
        if name not in self._ws_cache:
            self._ws_cache[name] = self._get_or_create(name)
        return self._ws_cache[name]

    def _get_or_create(self, name):
        try:
            return self._ss.worksheet(name)
        except self._gspread.WorksheetNotFound:
            ws = self._ss.add_worksheet(title=name, rows=10000, cols=30)
            headers = _HEADERS.get(name, [])
            if headers:
                ws.append_row(headers, value_input_option='USER_ENTERED')
            logger.info("Sheets: created worksheet '%s'", name)
            return ws
