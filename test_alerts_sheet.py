"""Mag 7 Algo alerts sheet (campaign_flow/alerts_sheet.py) on SYNTHETIC cards and a fake worksheet: only published
cards on/after ALERTS_SHEET_FROM become rows, each once, with the posted text, fill fields and exit formulas.

Run: python test_alerts_sheet.py
"""
import os
import tempfile
import threading
from datetime import date

os.environ['CF_MODE'] = 'SHADOW'
import config                                            # noqa: E402
from campaign_flow import alerts_sheet                  # noqa: E402
from campaign_flow import calendar_ny as cal            # noqa: E402
from campaign_flow import settings as S                 # noqa: E402
from campaign_flow.executor import SimBroker            # noqa: E402
from campaign_flow.journal import Journal               # noqa: E402
from campaign_flow.pipeline import Pipeline             # noqa: E402

fails = 0


def check(ok, name):
    global fails
    print(('PASS ' if ok else 'FAIL ') + name)
    fails += 0 if ok else 1


class FakeWS:
    def __init__(self):
        self.cells = {}                                  # (row, col) -> value

    def col_values(self, col):
        n = max([r for r, c in self.cells if c == col] or [0])
        return [self.cells.get((r, col), '') for r in range(1, n + 1)]

    def update(self, rows, a1, value_input_option=None):
        r0 = int(a1[1:])
        for i, row in enumerate(rows):
            for j, v in enumerate(row):
                self.cells[(r0 + i, j + 1)] = v

    def row(self, r):
        return [self.cells.get((r, c + 1), '') for c in range(len(alerts_sheet.HEADERS))]


def sheet_for(path, ws):
    s = alerts_sheet.AlertsSheet.__new__(alerts_sheet.AlertsSheet)
    s.journal_path, s._ws, s._lock = path, ws, threading.Lock()
    s._call = lambda fn, *a, **kw: fn(*a, **kw)
    return s


path = os.path.join(tempfile.mkdtemp(), 'j.db')
j = Journal(path)
d = date(2026, 11, 3)
o = cal.bounds(d)[0]
camp = {'campaign_id': 'c-tsla-1', 'ticker': 'TSLA', 'direction': 'BULLISH', 'session': '2026-11-03', 'state': 'CLOSED', 'horizon': 'INTRADAY',
        'contract': {'ticker': 'TSLA', 'expiry': '2026-11-04', 'right': 'C', 'strike': 395.0},
        'first_entry_ts': o + 1200, 'entry_conviction': {'tier': 'CONFIRMED', 'score': 81.4}}
j.put_campaign(camp)
S.MODE, S.DISCORD_ENABLED = 'PAPER', True
sent = []
p = Pipeline(j, SimBroker(), publish=lambda payload, cid: sent.append((cid, payload)))
p._card('ENTRY_PROPOSED', 'c-tsla-1', o + 1100, price=2.05, qty=2, card_id='e1:EP')
p._card('ENTRY_FILLED', 'c-tsla-1', o + 1200, price=2.11, qty=2, card_id='e1:EF')
p._card('EXIT_FILLED', 'c-tsla-1', o + 3000, price=4.20, qty=1, avg=2.11, remaining=1,
        reasons=['TRAILING_STOP_FROM_PEAK'], card_id='x1:XF')
p._card('EXIT_FILLED', 'c-tsla-1', o + 4000, price=3.00, qty=1, avg=2.11,
        reasons=['CONFIRMED_OPPOSITE_CLUSTER_ROTATION'], card_id='x2:XF')
j.put_card('old:EF', 'c-tsla-1', 'ENTRY_FILLED', cal.at(date(2026, 11, 2), '10:00'),
           {'embeds': [{'title': 't', 'description': 'd', 'footer': {'text': 'f'}}]}, published=True)

check(all('sheet' not in pl for _, pl in sent), 'the sheet metadata is journal-only, never sent to Discord')
check([c for c, _ in sent] == ['e1:EF', 'x1:XF', 'x2:XF'], 'only filled cards are published')

config.ALERTS_SHEET_FROM = '2026-11-03'
ws = FakeWS()
ws.update([alerts_sheet.HEADERS], 'A1')
s = sheet_for(path, ws)
check(s.sync() == 3, 'three published cards since Nov 3 are appended (proposal and Nov 2 card are not)')
check(s.sync() == 0, 'a second sync appends nothing (card id dedupe)')
r2, r3, r4 = ws.row(2), ws.row(3), ws.row(4)
check(r2[:8] == ['2026-11-03', '09:50:00', 'TSLA', 'Opened', 'TSLA 395C', 'Call', '2026-11-04', 'Intraday'],
      'entry row: date/time ET, ticker, alert, contract, side, expiry, horizon')
check(r2[8:12] == [2.11, 2, '', ''] and r2[12] == '' and r2[15:17] == ['CONFIRMED', 81.4],
      'entry row: fill, contracts, entry conviction; no return')
check('Model opened a simulated position' in r2[17] and r2[18] == 'e1:EF', 'entry row carries the posted card text and id')
check(r3[3] == 'Reduced' and r3[10] == 1 and r3[11] == 2.11 and r3[14] == 'Trailing stop from peak',
      'partial exit row: Reduced, still held, avg entry, reason')
check(r3[12] == '=IF(N(L3)>0,I3/L3-1,"")' and r3[13] == '=IF(N(L3)>0,(I3-L3)*J3*100,"")',
      'exit return / P&L are formulas on their own row')
check(r4[3] == 'Closed' and r4[10] == 0 and r4[14] == 'Confirmed opposite put flow' and r4[15] == '',
      'final exit row: Closed, nothing held, reason text')

p._card('EXIT_FILLED', 'c-tsla-1', o + 5000, price=3.10, qty=1, avg=2.11, card_id='x3:XF')
check(s.sync() == 1 and ws.row(5)[18] == 'x3:XF' and ws.row(5)[12] == '=IF(N(L5)>0,I5/L5-1,"")',
      'a later card is appended to the next row')

print('\nALL PASS' if not fails else f'\n{fails} FAILED')
raise SystemExit(1 if fails else 0)
