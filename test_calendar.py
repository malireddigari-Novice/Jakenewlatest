"""Exchange calendar + session-time tests (holidays, 1pm-ET early closes, DST). Run: python test_calendar.py"""
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data import exchange_calendar as xc
from data import market_utils as mu
from analysis import expiry_value

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

def at(y, m, d, hh, mm):
    return mu.CST.localize(datetime(y, m, d, hh, mm))

print("── published NYSE holidays ──")
nyse_2025 = {date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17), date(2025, 4, 18), date(2025, 5, 26),
             date(2025, 6, 19), date(2025, 7, 4), date(2025, 9, 1), date(2025, 11, 27), date(2025, 12, 25)}
ck("2025 holiday set matches NYSE", set(xc.holidays(2025)) == nyse_2025)
nyse_2026 = {date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25),
             date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25)}
ck("2026 holiday set matches NYSE (July 4 Sat → Fri Jul 3 observed)", set(xc.holidays(2026)) == nyse_2026)
nyse_2027 = {date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26), date(2027, 5, 31),
             date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6), date(2027, 11, 25), date(2027, 12, 24)}
ck("2027 holiday set matches NYSE (Juneteenth Sat → Fri, Christmas Sat → Fri)", set(xc.holidays(2027)) == nyse_2027)
ck("2022: Sat New Year's not observed on Fri 2021-12-31", date(2021, 12, 31) not in xc.holidays(2021)
   and date(2021, 12, 31) not in xc.holidays(2022))

print("── early closes ──")
ck("2026-11-27 (day after Thanksgiving) early close", xc.is_early_close(date(2026, 11, 27)))
ck("2026-12-24 early close", xc.is_early_close(date(2026, 12, 24)))
ck("2025-07-03 early close (July 4 Fri)", xc.is_early_close(date(2025, 7, 3)))
ck("2022-07-01 normal (July 4 Mon)", not xc.is_early_close(date(2022, 7, 1)))
ck("2026-07-03 is a holiday, not an early close", not xc.is_early_close(date(2026, 7, 3))
   and not xc.is_trading_day(date(2026, 7, 3)))
ck("2027-12-24 is the observed Christmas holiday", not xc.is_trading_day(date(2027, 12, 24)))

print("── session times (CT) ──")
ck("normal day open 10:00 CT", mu.is_market_open(at(2026, 10, 16, 10, 0)))
ck("holiday (Thanksgiving) never open", not mu.is_market_open(at(2026, 11, 26, 10, 0))
   and not mu.is_preopen_seed(at(2026, 11, 26, 8, 25)))
ck("half day: open 11:59 CT, closed 12:00 CT",
   mu.is_market_open(at(2026, 11, 27, 11, 59)) and not mu.is_market_open(at(2026, 11, 27, 12, 0)))
ck("half day EOD flatten 11:55 CT (5-min lead kept)",
   mu.eod_flatten_time(at(2026, 11, 27, 9, 0)) == at(2026, 11, 27, 11, 55)
   and mu.is_eod_window(at(2026, 11, 27, 11, 55)) and not mu.is_eod_window(at(2026, 11, 27, 14, 55)))
ck("half day entry cutoff from 11:40 CT", mu.is_past_entry_cutoff(at(2026, 11, 27, 11, 40))
   and not mu.is_past_entry_cutoff(at(2026, 11, 27, 11, 39)))
ck("normal day EOD flatten 14:55 CT", mu.eod_flatten_time(at(2026, 10, 16, 9, 0)) == at(2026, 10, 16, 14, 55))
ck("session minutes 390 normal / 210 half", mu.session_minutes(at(2026, 10, 16, 9, 0)) == 390
   and mu.session_minutes(at(2026, 11, 27, 9, 0)) == 210)
ck("DST: half day in winter is still 12:00 CT", mu.session_close(at(2026, 12, 24, 9, 0)) == at(2026, 12, 24, 12, 0))
ck("DST: summer early close 2025-07-03 is 12:00 CT", mu.session_close(at(2025, 7, 3, 9, 0)) == at(2025, 7, 3, 12, 0))

print("── 0DTE theta ramp ends at the actual close ──")
full = expiry_value.late_day_0dte_value(0, 210, strength=1, activation=1, remaining_convexity=1,
                                        session_minutes=210)
ck("half day: theta_risk = 1 at 210 min", full['theta_risk'] == 1.0)

print("── NY date ──")
ck("ny_date of 23:30 CT is the next NY day", xc.ny_date(at(2026, 10, 16, 23, 30)) == date(2026, 10, 17))

config.EXTRA_MARKET_HOLIDAYS = ['2026-10-21']
xc.holidays.cache_clear()
ck("EXTRA_MARKET_HOLIDAYS closes a one-off day", not xc.is_trading_day(date(2026, 10, 21)))
config.EXTRA_MARKET_HOLIDAYS = []
xc.holidays.cache_clear()

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
