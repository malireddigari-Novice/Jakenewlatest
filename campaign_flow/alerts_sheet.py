"""Google Sheet of every Mag 7 Algo alert (campaign-flow card) published to Discord, one row per card.

Separate spreadsheet from the legacy "Trading Log" (config.ALERTS_SPREADSHEET_ID), same service account
(config.GOOGLE_SERVICE_ACCOUNT_FILE; share the sheet with its email as Editor). Only cards actually published
(journal cards.published=1) on or after config.ALERTS_SHEET_FROM are written.

Durable by construction: the journal is the source of truth. Each sync reads the published cards, compares their
card ids with the sheet's "Card ID" column, and appends whatever is missing, oldest first. A Google outage, a
restart or a disabled sheet therefore never loses a row; the next sync (after any published card, and at start-up)
catches up. Syncs run in a daemon thread on their own sqlite connection, so the poll loop is never blocked.

This is an internal operator log, not a member card: it carries the simulated return / P&L and the entry
conviction, which stay off Discord (Mag 7 brief, item 7).

    python -m campaign_flow.alerts_sheet        # one sync now (e.g. after sharing the sheet)
"""
import json
import logging
import random
import sqlite3
import threading
import time
from datetime import date

import config
from campaign_flow import calendar_ny as cal
from campaign_flow import cards
from campaign_flow import settings as S

logger = logging.getLogger(__name__)

HEADERS = ['Date', 'Time (ET)', 'Ticker', 'Alert', 'Contract', 'Side', 'Expiry', 'Horizon',
           'Simulated fill ($)', 'Contracts', 'Still held', 'Avg entry ($)', 'Simulated return',
           'Simulated P&L ($)', 'Reason', 'Entry conviction', 'Conviction score', 'Card text (as posted)',
           'Card ID']
_ID_COL = len(HEADERS)                                   # 1-based column of the card id
_ALERT = {'ENTRY_FILLED': 'Opened', 'EXIT_FILLED': 'Closed', 'ENTRY_PROPOSED': 'Proposed open',
          'EXIT_PROPOSED': 'Proposed close'}
_RETRYABLE = (429, 500, 502, 503, 504)


def _since_ts() -> float:
    return cal.at(date.fromisoformat(config.ALERTS_SHEET_FROM), '00:00')      # New York midnight


def published_cards(journal_path: str) -> list:
    """Published cards on/after ALERTS_SHEET_FROM, oldest first, joined with their campaign."""
    con = sqlite3.connect(f"file:{journal_path}?mode=ro", uri=True, timeout=10)
    try:
        rows = con.execute("SELECT c.card_id, c.label, c.ts, c.body, k.body FROM cards c "
                           "LEFT JOIN campaigns k ON k.campaign_id = c.campaign_id "
                           "WHERE c.published = 1 AND c.ts >= ? ORDER BY c.ts, c.rowid", (_since_ts(),)).fetchall()
    finally:
        con.close()
    return [{'card_id': r[0], 'label': r[1], 'ts': r[2], 'body': json.loads(r[3]),
             'campaign': json.loads(r[4]) if r[4] else {}} for r in rows]


def row(card: dict, n: int) -> list:
    """Sheet row `n` (1-based) for one published card; return and P&L are sheet formulas on that row."""
    c, body = card['campaign'], card['body']
    meta = body.get('sheet') or {}
    k = c.get('contract') or {}
    t = cal.ny_dt(card['ts'])
    entry = card['label'].startswith('ENTRY')
    alert = _ALERT.get(card['label'], card['label'])
    if card['label'] == 'EXIT_FILLED' and meta.get('remaining'):
        alert = 'Reduced'
    ctext, _ = cards.contract_text({**k, 'ticker': c.get('ticker', '')}) if k else ('', '')
    conv = (c.get('entry_conviction') or {}) if entry else {}
    try:
        text = cards.text(body)
    except (KeyError, IndexError, TypeError):
        text = ''
    exit_row = card['label'] == 'EXIT_FILLED'
    return [t.strftime('%Y-%m-%d'), t.strftime('%H:%M:%S'), c.get('ticker', ''), alert, ctext,
            {'C': 'Call', 'P': 'Put'}.get(k.get('right'), ''), str(k.get('expiry', '')),
            (c.get('horizon') or S.DEFAULT_HORIZON).title(),
            meta.get('price', ''), meta.get('qty', ''), meta.get('remaining') or (0 if exit_row else ''),
            meta.get('avg') or '',
            f'=IF(N(L{n})>0,I{n}/L{n}-1,"")' if exit_row else '',
            f'=IF(N(L{n})>0,(I{n}-L{n})*J{n}*100,"")' if exit_row else '',
            '' if entry else cards.reason_text(meta.get('reasons'), c.get('direction', '')),
            conv.get('tier', ''), conv.get('score', ''), text, card['card_id']]


class AlertsSheet:

    def __init__(self, journal_path: str) -> None:
        import gspread
        self._gspread = gspread
        self.journal_path = journal_path
        self._ws = None
        self._kick = threading.Event()
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, name='alerts-sheet', daemon=True).start()
        self._kick.set()                                   # catch up at start-up

    # ── public ────────────────────────────────────────────────────────────────
    def kick(self) -> None:
        """Request a sync (non-blocking)."""
        self._kick.set()

    def sync(self) -> int:
        """Append every published card the sheet does not have yet. Returns rows appended."""
        with self._lock:
            ws = self._worksheet()
            have = set(self._call(ws.col_values, _ID_COL)[1:])
            missing = [c for c in published_cards(self.journal_path) if c['card_id'] not in have]
            if not missing:
                return 0
            n0 = len(self._call(ws.col_values, 1)) + 1     # next empty row (column A is never blank)
            rows = [row(c, n0 + i) for i, c in enumerate(missing)]
            self._call(ws.update, rows, f'A{n0}', value_input_option='USER_ENTERED')
            logger.info("Alerts sheet: appended %d alert row(s)", len(rows))
            return len(rows)

    # ── internals ─────────────────────────────────────────────────────────────
    def _loop(self) -> None:
        delay = 0.0
        while True:
            self._kick.wait(timeout=None if delay == 0 else delay)
            self._kick.clear()
            try:
                self.sync()
                delay = 0.0
            except Exception:
                delay = min(600.0, max(30.0, delay * 2))   # retry on its own; the next card also kicks
                self._ws = None
                logger.warning("Alerts sheet sync failed — retrying in %.0fs", delay, exc_info=True)

    def _worksheet(self):
        if self._ws is None:
            from google.oauth2.service_account import Credentials
            if not config.ALERTS_SPREADSHEET_ID:
                raise RuntimeError("ALERTS_SPREADSHEET_ID is not set")
            creds = Credentials.from_service_account_file(
                config.GOOGLE_SERVICE_ACCOUNT_FILE,
                scopes=['https://www.googleapis.com/auth/spreadsheets'])
            ss = self._gspread.authorize(creds).open_by_key(config.ALERTS_SPREADSHEET_ID)
            try:
                ws = ss.worksheet(config.ALERTS_SHEET_TAB)
            except self._gspread.WorksheetNotFound:
                blank = len(ss.worksheets()) == 1 and not any(any(r) for r in ss.sheet1.get_all_values())
                ws = ss.sheet1 if blank else None
                ws = ws or ss.add_worksheet(title=config.ALERTS_SHEET_TAB, rows=2000, cols=len(HEADERS))
                if ws.title != config.ALERTS_SHEET_TAB:
                    ws.update_title(config.ALERTS_SHEET_TAB)
            if self._call(ws.row_values, 1) != HEADERS:
                self._call(ws.update, [HEADERS], 'A1')
                ws.format('A1:S1', {'textFormat': {'bold': True}})
                ws.freeze(rows=1)
                ws.format('I:I', {'numberFormat': {'type': 'CURRENCY', 'pattern': '$#,##0.00'}})
                ws.format('L:L', {'numberFormat': {'type': 'CURRENCY', 'pattern': '$#,##0.00'}})
                ws.format('M:M', {'numberFormat': {'type': 'PERCENT', 'pattern': '0.0%'}})
                ws.format('N:N', {'numberFormat': {'type': 'CURRENCY', 'pattern': '$#,##0;($#,##0);-'}})
            logger.info("Alerts sheet connected: %s (tab '%s')", ss.title, ws.title)
            self._ws = ws
        return self._ws

    def _call(self, fn, *a, **kw):
        for attempt in range(6):
            try:
                return fn(*a, **kw)
            except self._gspread.exceptions.APIError as exc:
                if getattr(exc.response, 'status_code', None) in _RETRYABLE and attempt < 5:
                    time.sleep(min(30.0, 2 ** attempt + random.random()))
                else:
                    raise


def start(journal_path: str):
    """The sheet syncer when ALERTS_SHEET_ENABLED, else None. Never fatal."""
    if not config.ALERTS_SHEET_ENABLED:
        return None
    try:
        return AlertsSheet(journal_path)
    except Exception:
        logger.warning("Alerts sheet disabled (start failed)", exc_info=True)
        return None


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    s = AlertsSheet.__new__(AlertsSheet)
    import gspread
    s._gspread, s.journal_path, s._ws, s._lock = gspread, S.JOURNAL_DB, None, threading.Lock()
    print('appended', s.sync(), 'row(s)')
