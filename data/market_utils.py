"""
Market-hours and timezone helpers.
All public functions use America/Chicago (CST/CDT). NYSE open = 08:30 CST, close = 15:00 CST.
Holidays and 1:00 pm ET early closes come from `data/exchange_calendar.py`: a holiday is never "open",
and on an early-close day the close, the EOD flatten and the entry cutoff all move earlier by the same
amount (the flatten keeps its normal lead on the close).
"""
from datetime import date, datetime, time, timedelta

import pytz

import config
from data import exchange_calendar as xcal

CST = pytz.timezone(config.SESSION_TZ)

_MARKET_OPEN  = time(config.MARKET_OPEN_HOUR,  config.MARKET_OPEN_MINUTE)
_MARKET_CLOSE = time(config.MARKET_CLOSE_HOUR, config.MARKET_CLOSE_MINUTE)
_WARMUP_END = (datetime.combine(date.min, _MARKET_OPEN)
               + timedelta(minutes=config.SIGNAL_WARMUP_MINUTES)).time()
_PREOPEN_START = (datetime.combine(date.min, _MARKET_OPEN)
                  - timedelta(minutes=config.PREOPEN_SEED_MINUTES)).time()
_OPENING_STRICT_END = (datetime.combine(date.min, _MARKET_OPEN)
                       + timedelta(minutes=config.OPENING_STRICT_MINUTES)).time()


def now_cst() -> datetime:
    return datetime.now(CST)


def today_cst() -> date:
    return now_cst().date()


def is_weekday(dt: datetime = None) -> bool:
    dt = dt or now_cst()
    return dt.weekday() < 5


def is_trading_day(dt: datetime = None) -> bool:
    """Weekday AND not an exchange holiday."""
    dt = dt or now_cst()
    return xcal.is_trading_day(dt.date())


def session_close(dt: datetime = None) -> datetime:
    """Today's close in SESSION_TZ (12:00 CT on an early-close day), or the regular close time on a
    non-trading day (callers check is_trading_day first)."""
    dt = dt or now_cst()
    regular = dt.replace(hour=config.MARKET_CLOSE_HOUR, minute=config.MARKET_CLOSE_MINUTE,
                         second=0, microsecond=0)
    if xcal.is_early_close(dt.date()):
        _, close = xcal.session_bounds(dt.date(), CST)
        return close if dt.tzinfo is not None else close.replace(tzinfo=None)
    return regular


def session_minutes(dt: datetime = None) -> float:
    """Length of today's regular session in minutes (390 normally, 210 on an early-close day)."""
    dt = dt or now_cst()
    open_dt = dt.replace(hour=config.MARKET_OPEN_HOUR, minute=config.MARKET_OPEN_MINUTE,
                         second=0, microsecond=0)
    return (session_close(dt) - open_dt).total_seconds() / 60.0


def eod_flatten_time(dt: datetime = None) -> datetime:
    """The EOD flatten keeps its configured lead on the close (14:55 normally, 11:55 on a half day)."""
    dt = dt or now_cst()
    regular_close = dt.replace(hour=config.MARKET_CLOSE_HOUR, minute=config.MARKET_CLOSE_MINUTE,
                               second=0, microsecond=0)
    regular_eod = dt.replace(hour=config.EOD_HOUR, minute=config.EOD_MINUTE, second=0, microsecond=0)
    return session_close(dt) - (regular_close - regular_eod)


def is_market_open(dt: datetime = None) -> bool:
    dt = dt or now_cst()
    if not is_trading_day(dt):
        return False
    t = dt.time().replace(second=0, microsecond=0)
    return _MARKET_OPEN <= t < session_close(dt).time()


def is_warmup(dt: datetime = None) -> bool:
    """First SIGNAL_WARMUP_MINUTES after open — build premium baselines, fire nothing."""
    if config.SIGNAL_WARMUP_MINUTES <= 0:
        return False
    dt = dt or now_cst()
    if not is_trading_day(dt):
        return False
    t = dt.time().replace(second=0, microsecond=0)
    return _MARKET_OPEN <= t < _WARMUP_END


def is_preopen_seed(dt: datetime = None) -> bool:
    """
    True in the PREOPEN_SEED_MINUTES window just before the open. Here the engine reads
    contract snapshots and SEEDS volume baselines (no trading) so that fresh deltas after
    the open capture the opening auction instead of discarding it as noise.
    """
    if config.PREOPEN_SEED_MINUTES <= 0:
        return False
    dt = dt or now_cst()
    if not is_trading_day(dt):
        return False
    t = dt.time().replace(second=0, microsecond=0)
    return _PREOPEN_START <= t < _MARKET_OPEN


def is_opening_strict(dt: datetime = None) -> bool:
    """True during OPENING_STRICT_MINUTES after the open — opening events face tighter gates."""
    if config.OPENING_STRICT_MINUTES <= 0:
        return False
    dt = dt or now_cst()
    if not is_trading_day(dt):
        return False
    t = dt.time().replace(second=0, microsecond=0)
    return _MARKET_OPEN <= t < _OPENING_STRICT_END


def is_past_entry_cutoff(dt: datetime = None) -> bool:
    """
    True once we are within ENTRY_CUTOFF_BUFFER_MIN of the EOD flatten — no NEW positions after
    this. Stops opening a 0DTE with too little time to work, and prevents a fill landing after
    the once-daily flatten (which would otherwise be carried overnight).
    """
    dt = dt or now_cst()
    if not is_trading_day(dt):
        return True
    return dt >= eod_flatten_time(dt) - timedelta(minutes=config.ENTRY_CUTOFF_BUFFER_MIN)


def is_eod_window(dt: datetime = None, window_sec: int = 59) -> bool:
    """True within `window_sec` of the EOD flatten time — fires once from a 60s loop."""
    dt = dt or now_cst()
    if not is_trading_day(dt):
        return False
    return abs((dt - eod_flatten_time(dt)).total_seconds()) <= window_sec
