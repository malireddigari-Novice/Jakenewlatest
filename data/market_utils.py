"""
Market-hours and timezone helpers.
All public functions use America/Chicago (CST/CDT). NYSE open = 08:30 CST, close = 15:00 CST.
"""
from datetime import date, datetime, time, timedelta

import pytz

import config

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


def is_market_open(dt: datetime = None) -> bool:
    dt = dt or now_cst()
    if not is_weekday(dt):
        return False
    t = dt.time().replace(second=0, microsecond=0)
    return _MARKET_OPEN <= t < _MARKET_CLOSE


def is_warmup(dt: datetime = None) -> bool:
    """First SIGNAL_WARMUP_MINUTES after open — build premium baselines, fire nothing."""
    if config.SIGNAL_WARMUP_MINUTES <= 0:
        return False
    dt = dt or now_cst()
    if not is_weekday(dt):
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
    if not is_weekday(dt):
        return False
    t = dt.time().replace(second=0, microsecond=0)
    return _PREOPEN_START <= t < _MARKET_OPEN


def is_opening_strict(dt: datetime = None) -> bool:
    """True during OPENING_STRICT_MINUTES after the open — opening events face tighter gates."""
    if config.OPENING_STRICT_MINUTES <= 0:
        return False
    dt = dt or now_cst()
    if not is_weekday(dt):
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
    if not is_weekday(dt):
        return True
    eod = dt.replace(hour=config.EOD_HOUR, minute=config.EOD_MINUTE, second=0, microsecond=0)
    return dt >= eod - timedelta(minutes=config.ENTRY_CUTOFF_BUFFER_MIN)


def is_eod_window(dt: datetime = None, window_sec: int = 59) -> bool:
    """True within `window_sec` of the EOD flatten time — fires once from a 60s loop."""
    dt = dt or now_cst()
    if not is_weekday(dt):
        return False
    eod_dt = dt.replace(hour=config.EOD_HOUR, minute=config.EOD_MINUTE,
                        second=0, microsecond=0)
    return abs((dt - eod_dt).total_seconds()) <= window_sec
