"""
Jakenew — MAG-7 Attention Engine.  Entry point.

A single process on a POLL_INTERVAL_SECONDS loop. Each tick asks one question — who owns
institutional attention right now? — and acts on the answer: at most one convexity trade,
held until its objective is met or attention rotates away.

Run:  python main.py
Execution is OFF until ALPACA_ENABLED=true in .env — until then it logs a full SHADOW
narrative so you can watch the decisions before committing capital.
"""
import logging
import sys
import time

import config
from data.alpaca_client import AlpacaClient
from data.alpaca_data_client import AlpacaDataClient
from data.market_utils import is_market_open, is_preopen_seed, is_weekday, now_cst
from engine import AttentionEngine

try:
    from data.schwab_client import SchwabClient
except Exception:                       # schwab-py not installed → run Alpaca-only
    SchwabClient = None


def _keep_awake() -> None:
    """Block system sleep while Jakenew runs (i.e. during market hours). Scoped to the process:
    Windows releases it automatically when the process exits at EOD, so no global power-setting
    change or restore is needed. Combined with the task's WakeToRun, the machine wakes at 08:10 and
    stays awake through the session. No-op off Windows / on failure."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        logging.getLogger('main').info("Sleep blocked for the session (SetThreadExecutionState).")
    except Exception:
        logging.getLogger('main').warning("Could not block sleep (continuing).", exc_info=True)


def _release_awake() -> None:
    """Clear the keep-awake request so normal power management resumes after the session."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)  # ES_CONTINUOUS only
    except Exception:
        pass


def _setup_logging() -> None:
    # Windows consoles default to cp1252 and crash on non-ASCII log glyphs; force UTF-8
    # (same fix JakeVolume applied via PYTHONUTF8=1).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    handlers = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(config.LOG_FILE, encoding='utf-8'))
    except Exception:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)-7s %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=handlers,
    )


_BEHAVIOR_FLAGS = [
    'ALPACA_ENABLED', 'ALPACA_PAPER', 'CAMPAIGN_CONFIDENCE_ENABLED', 'STABILIZE_ENABLED',
    'DAILY_ENTRY_LOCK_ENABLED', 'ENTRY_ROUTES_ENABLED', 'ENTRY_ROUTE_MIN_SCORE',
    'ACCEPTANCE_ENABLED', 'OPENING_QUALITY_ENABLED', 'ARCHETYPE_GATE_ENABLED', 'SURFACE_GATE_ENABLED',
    'RUNNER_ENABLED', 'REINFORCE_LOG_ENABLED', 'RESEARCH_ARCHIVE_ENABLED', 'MULTI_EXPIRY_ENABLED',
    'ROTATION_REQUIRE_INCUMBENT_WEAK', 'REQUIRE_POSITIVE_EV', 'CAMPAIGN_MIN_POSTERIOR',
    'DIST_PROB_MAX_ENTRY', 'REDUCE_ON_DISTRIBUTION', 'HOLD_EXIT_THRESHOLD', 'SHEETS_ENABLED',
]


def _log_config() -> None:
    """Print the ACTUAL resolved runtime config every launch — never rely on documented defaults.
    The 'decision owner' is whichever exit path is authoritative given these flags."""
    log = logging.getLogger('main')
    vals = "  ".join(f"{f}={getattr(config, f)}" for f in _BEHAVIOR_FLAGS)
    log.info("RUNTIME CONFIG | %s", vals)
    owner = ("CAMPAIGN_CONFIDENCE (hold engine)" if config.CAMPAIGN_CONFIDENCE_ENABLED
             else "STABILIZE" if config.STABILIZE_ENABLED else "LEGACY wave exits")
    log.info("EXIT DECISION OWNER = %s | entry path = %s | daily one-per-side lock = %s", owner,
             "ARCHETYPE ROUTES" if config.ENTRY_ROUTES_ENABLED else "conjunctive gate stack",
             "ON" if config.DAILY_ENTRY_LOCK_ENABLED else "OFF")


def _build_engine() -> AttentionEngine:
    log = logging.getLogger('main')

    data = AlpacaDataClient()
    data.login()
    if not data.verify():
        log.error("Alpaca data feed unavailable — cannot run without it. Check ALPACA_* in .env.")
        sys.exit(1)

    execu = None
    if config.ALPACA_ENABLED:
        execu = AlpacaClient()
        if not execu.verify():
            log.warning("Alpaca execution verify failed — running in SHADOW (no orders).")
            execu = None
    else:
        # Still build the exec client for sizing/portfolio reads if creds are valid; orders
        # are gated on ALPACA_ENABLED inside the engine, so nothing trades.
        execu = AlpacaClient()

    schwab = None
    if config.SCHWAB_ENABLED and SchwabClient is not None:
        schwab = SchwabClient()
        if not schwab.login():
            schwab = None       # degrade gracefully — engine runs on Alpaca alone

    mode = "LIVE execution" if config.ALPACA_ENABLED else "SHADOW (no orders)"
    log.info("Jakenew ready — %s | Schwab OI=%s | Mag7=%s",
             mode, "on" if schwab else "off", ",".join(config.MAG7))
    return AttentionEngine(data, execu, schwab)


def main() -> None:
    _setup_logging()
    _keep_awake()                         # block sleep for the duration of the session
    _log_config()                         # print the actual resolved runtime config + decision owner
    log = logging.getLogger('main')
    engine = _build_engine()

    log.info("Entering %ds fast loop (windows %d/%d/%ds). Market %02d:%02d-%02d:%02d %s; "
             "pre-open seed from %02d:%02d.",
             config.FAST_POLL_SECONDS, config.WINDOW_FAST, config.WINDOW_MID, config.WINDOW_SLOW,
             config.MARKET_OPEN_HOUR, config.MARKET_OPEN_MINUTE, config.MARKET_CLOSE_HOUR,
             config.MARKET_CLOSE_MINUTE, config.SESSION_TZ,
             config.MARKET_OPEN_HOUR, config.MARKET_OPEN_MINUTE - config.PREOPEN_SEED_MINUTES)

    while True:
        try:
            now = now_cst()
            active = is_market_open(now) or is_preopen_seed(now)
            if active:
                engine.poll()                 # poll() handles pre-open seeding + phase internally
                engine.maybe_eod_flatten(now)
            # Exit once the day is done (EOD flatten complete, or a weekday launch already past
            # the close) so the NEXT 08:10 scheduled launch always starts fresh with the on-disk
            # code. A long-lived process would otherwise keep running stale code day after day.
            close_dt = now.replace(hour=config.MARKET_CLOSE_HOUR,
                                   minute=config.MARKET_CLOSE_MINUTE, second=0, microsecond=0)
            if (engine.state.get('eod_done') == now.date().isoformat()
                    or (is_weekday(now) and now >= close_dt)):
                log.info("Session complete for %s — exiting so the next launch runs fresh code.",
                         now.date())
                break
        except KeyboardInterrupt:
            log.info("Interrupted - exiting.")
            break
        except Exception:
            log.exception("poll loop error (continuing)")
        # Fast cadence while the session (or pre-open seeding) is active; idle slowly otherwise.
        time.sleep(config.FAST_POLL_SECONDS if (is_market_open() or is_preopen_seed()) else 30)

    _release_awake()                      # resume normal power management after the session
    log.info("Jakenew stopped.")


if __name__ == '__main__':
    main()
