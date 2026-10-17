"""New York trading-day boundaries, opens, early closes and deadlines (actual exchange calendar).

Epoch seconds in, epoch seconds out; every conversion goes through America/New_York.
"""
from datetime import date, datetime, time, timedelta

import pytz

from campaign_flow import settings as S
from data import exchange_calendar as xcal

NY = pytz.timezone(S.NY_TZ)


def ny_dt(ts: float) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=pytz.utc).astimezone(NY)


def ny_day(ts: float) -> date:
    return ny_dt(ts).date()


def at(d: date, hhmm: str) -> float:
    h, m = (int(x) for x in hhmm.split(':'))
    return NY.localize(datetime.combine(d, time(h, m))).timestamp()


def bounds(d: date):
    """(open_ts, close_ts) of the regular session, or None on a non-trading day."""
    b = xcal.session_bounds(d, NY)
    return (b[0].timestamp(), b[1].timestamp()) if b else None


def is_trading_day(d: date) -> bool:
    return xcal.is_trading_day(d)


def next_trading_day(d: date) -> date:
    n = d + timedelta(days=1)
    while not xcal.is_trading_day(n):
        n += timedelta(days=1)
    return n


def prev_trading_day(d: date) -> date:
    n = d - timedelta(days=1)
    while not xcal.is_trading_day(n):
        n -= timedelta(days=1)
    return n


def oi_cutoff(d: date):
    """Actual regular open minus OI_CUTOFF_MIN_BEFORE_OPEN (09:20 for a normal 09:30 open)."""
    b = bounds(d)
    return None if not b else b[0] - S.OI_CUTOFF_MIN_BEFORE_OPEN * 60


def expiry_deadline(expiry: str) -> float:
    """Reference expiration liquidation cutoff (15:30 NY), never later than the actual close minus 30 min
    on an early-close day. A non-trading expiration date rolls back to the prior trading session."""
    d = date.fromisoformat(str(expiry))
    while not xcal.is_trading_day(d):
        d -= timedelta(days=1)
    cut = at(d, S.EXPIRY_LIQUIDATION_NY)
    _, close = bounds(d)
    return min(cut, close - 30 * 60)


def planned_end(horizon: str, decision_ts: float) -> float:
    """Planned end chosen BEFORE entry (the router does not infer a horizon from raw flow)."""
    d = ny_day(decision_ts)
    if horizon == 'OVERNIGHT':
        d = next_trading_day(d)
    elif horizon == 'SWING':
        for _ in range(max(1, S.SWING_SESSIONS)):
            d = next_trading_day(d)
    end = at(d, S.PLANNED_END_NY)
    _, close = bounds(d)
    return min(end, close - 30 * 60)
