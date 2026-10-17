"""
NYSE / options-market session calendar — pure, no dependencies.

Holidays and 1:00 pm ET early closes, from the exchange's standing rules (observed-day shifting, Good
Friday via the Gregorian Easter computus, Juneteenth from 2022). Times are produced in New York and
converted to the engine's SESSION_TZ by the caller, so daylight-saving changes are handled by pytz.

Covered rules (NYSE Rule 7.2 practice):
  closed : New Year's Day*, MLK Day, Presidents' Day, Good Friday, Memorial Day, Juneteenth* (2022+),
           Independence Day*, Labor Day, Thanksgiving, Christmas*     (* Sat → Fri, Sun → Mon)
           New Year's Day falling on a Saturday is NOT observed on the prior Friday (year-end close).
  13:00  : July 3 when July 4 is Tue–Fri; the day after Thanksgiving; Dec 24 when it is a weekday and
           not itself a holiday.
One-off closures (national days of mourning, weather) are not rule-based — list them in
`config.EXTRA_MARKET_HOLIDAYS` (ISO dates).
"""
from datetime import date, datetime, time, timedelta
from functools import lru_cache

import pytz

import config

NY = pytz.timezone('America/New_York')
REGULAR_OPEN_NY = time(9, 30)
REGULAR_CLOSE_NY = time(16, 0)
EARLY_CLOSE_NY = time(13, 0)


def _easter(y: int) -> date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(y, month, day)


def _nth_weekday(y, month, weekday, n) -> date:
    d = date(y, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(y, month, weekday) -> date:
    d = date(y, month + 1, 1) - timedelta(days=1) if month < 12 else date(y, 12, 31)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=64)
def holidays(year: int) -> frozenset:
    out = set()
    ny = date(year, 1, 1)
    if ny.weekday() != 5:                       # Saturday New Year's is not moved into the old year
        out.add(_observed(ny))
    out.add(_nth_weekday(year, 1, 0, 3))        # MLK Day
    out.add(_nth_weekday(year, 2, 0, 3))        # Presidents' Day
    out.add(_easter(year) - timedelta(days=2))  # Good Friday
    out.add(_last_weekday(year, 5, 0))          # Memorial Day
    if year >= 2022:
        out.add(_observed(date(year, 6, 19)))   # Juneteenth
    out.add(_observed(date(year, 7, 4)))        # Independence Day
    out.add(_nth_weekday(year, 9, 0, 1))        # Labor Day
    out.add(_nth_weekday(year, 11, 3, 4))       # Thanksgiving
    out.add(_observed(date(year, 12, 25)))      # Christmas
    for s in getattr(config, 'EXTRA_MARKET_HOLIDAYS', ()) or ():
        try:
            d = date.fromisoformat(str(s).strip())
            if d.year == year:
                out.add(d)
        except ValueError:
            pass
    return frozenset(out)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def is_early_close(d: date) -> bool:
    if not is_trading_day(d):
        return False
    if d.month == 7 and d.day == 3 and date(d.year, 7, 4).weekday() in (1, 2, 3, 4):
        return True
    if d == _nth_weekday(d.year, 11, 3, 4) + timedelta(days=1):
        return True
    if d.month == 12 and d.day == 24:
        return True
    return False


def session_bounds(d: date, tz) -> tuple | None:
    """(open, close) as aware datetimes in `tz` for trading day `d`, or None when closed."""
    if not is_trading_day(d):
        return None
    close_ny = EARLY_CLOSE_NY if is_early_close(d) else REGULAR_CLOSE_NY
    o = NY.localize(datetime.combine(d, REGULAR_OPEN_NY)).astimezone(tz)
    c = NY.localize(datetime.combine(d, close_ny)).astimezone(tz)
    return o, c


def ny_date(dt: datetime) -> date:
    """The America/New_York calendar date of an aware datetime (DTE and session are counted in NY)."""
    return dt.astimezone(NY).date()
