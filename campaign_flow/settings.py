"""Campaign-flow policy parameters (Logic for Jake.txt, Oct 15 2026 revision).

Every number here is a configurable PAPER DEFAULT that still needs forward calibration; none is a validated
edge. All are env-overridable (CF_*) and folded into RULE_VERSION, so every journal row states exactly which
rules produced it.
"""
import hashlib
import json
import os


def _f(k, d): return float(os.getenv(k, str(d)))
def _i(k, d): return int(os.getenv(k, str(d)))
def _b(k, d): return os.getenv(k, 'true' if d else 'false').lower() == 'true'
def _of(k):   # optional float: unset/blank → None (a risk control that is OFF unless precommitted)
    v = os.getenv(k, '').strip()
    return float(v) if v else None


# ── mode / storage ────────────────────────────────────────────────────────────
# OFF: not run. SHADOW: decide + journal on the engine's own polls; fills come from the simulated broker
# (tagged SIM, never published as fills). PAPER: this policy owns the Alpaca PAPER orders and the legacy
# engine stops ordering (it keeps computing, so both policies still see identical observations).
MODE             = os.getenv('CF_MODE', 'SHADOW').upper()
JOURNAL_DB       = os.getenv('CF_JOURNAL_DB', 'jakenew_campaign_flow.db')
OBS_DIR          = os.getenv('CF_OBS_DIR', 'cf_obs')            # recorded observations, for exact replay
RECORD_OBS       = _b('CF_RECORD_OBS', True)
DISCORD_ENABLED  = _b('CF_DISCORD_ENABLED', False)               # public cards only for PAPER fills/proposals
UNIVERSE         = ('AAPL', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA', 'TSLA')
NY_TZ            = 'America/New_York'

# ── §3 exact-contract premium value gate ─────────────────────────────────────
VALUE_MIN_REFS   = _i('CF_VALUE_MIN_REFS', 20)
VALUE_LOW_MAX    = _f('CF_VALUE_LOW_MAX', 0.25)                  # pct <= this: low band
VALUE_HIGH_MIN   = _f('CF_VALUE_HIGH_MIN', 0.75)                 # pct >= this: high band
VALUE_REF_SESSIONS = _i('CF_VALUE_REF_SESSIONS', 3)              # prior sessions of 1-min bars per series

# ── §4 concentrated shock ────────────────────────────────────────────────────
WINDOW_S         = _i('CF_WINDOW_S', 60)                         # adapter's completed-window length
SHOCK_MAX_WINDOW_S = _i('CF_SHOCK_MAX_WINDOW_S', 300)
SHOCK_MIN_CONTRACTS = _i('CF_SHOCK_MIN_CONTRACTS', 50)
SHOCK_MIN_PRINTS = _i('CF_SHOCK_MIN_PRINTS', 3)
SHOCK_MIN_SURPRISE = _f('CF_SHOCK_MIN_SURPRISE', 2.0)            # window volume / comparable baseline
SHOCK_MIN_NEAR_ASK = _f('CF_SHOCK_MIN_NEAR_ASK', 0.60)
SHAPE_TOP_BIN    = _f('CF_SHAPE_TOP_BIN', 0.45)
SHAPE_TOP2       = _f('CF_SHAPE_TOP2', 0.70)
SHAPE_TOP_PRINT  = _f('CF_SHAPE_TOP_PRINT', 0.35)
FLOW_LOOKBACK_S  = _i('CF_FLOW_LOOKBACK_S', 1200)

# ── §5 clusters ──────────────────────────────────────────────────────────────
PAIR_MAX_GAP_FRAC = _f('CF_PAIR_MAX_GAP_FRAC', 0.025)            # neighbouring-strike gap / event spot
CLUSTER_MAX_END_GAP_S = _i('CF_CLUSTER_MAX_END_GAP_S', 420)
CLUSTER_MAX_AGE_S = _i('CF_CLUSTER_MAX_AGE_S', 300)
SNAPSHOT_MAX_AGE_S = _i('CF_SNAPSHOT_MAX_AGE_S', 60)
ADJACENCY_RULE   = 'NEIGHBOURING_QUALIFYING_STRIKES_GAP_LE_PCT_OF_SPOT'   # reference interpretation (§21)

# ── §6 board ─────────────────────────────────────────────────────────────────
RECENCY_S        = _i('CF_RECENCY_S', 1200)
YEAR_S           = 31_557_600

# ── §7 turnover ──────────────────────────────────────────────────────────────
PRIOR_TURNOVER_LABEL_MIN = _f('CF_PRIOR_TURNOVER_LABEL_MIN', 0.75)

# ── §8 entry ─────────────────────────────────────────────────────────────────
OLD_ROUTE_BOUNDARY = _f('CF_OLD_ROUTE_BOUNDARY', 0.550)          # logged comparison only, never a veto
MAX_PROPOSALS_PER_TICKER_DAY = _i('CF_MAX_PROPOSALS_PER_TICKER_DAY', 2)
DEFAULT_HORIZON  = os.getenv('CF_DEFAULT_HORIZON', 'INTRADAY').upper()   # INTRADAY | OVERNIGHT | SWING
SWING_SESSIONS   = _i('CF_SWING_SESSIONS', 3)                    # SWING planned end = N trading sessions out
SWING_BUFFER_DAYS = _i('CF_SWING_BUFFER_DAYS', 1)
EXPIRY_LIQUIDATION_NY = os.getenv('CF_EXPIRY_LIQUIDATION_NY', '15:30')
PLANNED_END_NY   = os.getenv('CF_PLANNED_END_NY', '15:30')       # time of day a planned end lands on
QUOTE_MAX_AGE_S  = _f('CF_QUOTE_MAX_AGE_S', 30)
MAX_REL_SPREAD   = _f('CF_MAX_REL_SPREAD', 0.30)
MIN_ASK_SIZE     = _i('CF_MIN_ASK_SIZE', 1)
BUDGET           = _f('CF_BUDGET', 2000.0)                       # reference paper premium budget
MAX_QTY          = _i('CF_MAX_QTY', 2)                           # planned contracts per proposal (cap)
ENTRY_ORDER_TTL_S = _i('CF_ENTRY_ORDER_TTL_S', 90)               # unfilled entry remainder is cancelled after

# ── §9 daily OI reference ────────────────────────────────────────────────────
OI_CUTOFF_MIN_BEFORE_OPEN = _i('CF_OI_CUTOFF_MIN', 10)
OI_STRIP         = _i('CF_OI_STRIP', 6)
OI_LEVELS        = _i('CF_OI_LEVELS', 3)

# ── §12 exits ────────────────────────────────────────────────────────────────
GAP_MIN_FRACTION = _f('CF_GAP_MIN_FRACTION', 0.0)
FOLLOWTHROUGH_MAX_GAP_S = _i('CF_FOLLOWTHROUGH_MAX_GAP_S', 420)
PREMIUM_LOSS_LIMIT = _of('CF_PREMIUM_LOSS_LIMIT')                # e.g. 0.5 — OFF unless set before entry
UNDERLYING_INVALIDATION_PCT = _of('CF_UNDERLYING_INVALIDATION_PCT')   # e.g. 0.01 below entry spot — OFF unless set

# ── §13 exit quotes ──────────────────────────────────────────────────────────
EXIT_QUOTE_MAX_AGE_S = _f('CF_EXIT_QUOTE_MAX_AGE_S', 30)

# ── adapter (snapshot) definitions — §21 says these must be documented, not inferred ────────────
NEAR_ASK_LOCATION = _f('CF_NEAR_ASK_LOCATION', 0.80)             # trade price location in [bid,ask] >= this
SYNC_MIN_FRESH_FRAC = _f('CF_SYNC_MIN_FRESH_FRAC', 0.90)         # share of quotes <= QUOTE_MAX_AGE_S old
BASELINE_FLOOR   = _f('CF_BASELINE_FLOOR', 5.0)                  # contracts per window (avoids a 0 baseline)
UNDERLYING_WINDOW_S = _i('CF_UNDERLYING_WINDOW_S', 30)           # engine's WINDOW_FAST dS/dt rule

RULE_VERSION = 'cf-v1-' + hashlib.sha256(json.dumps(
    {k: v for k, v in sorted(globals().items()) if k.isupper() and k not in ('JOURNAL_DB', 'OBS_DIR', 'MODE', 'DISCORD_ENABLED', 'RECORD_OBS')},
    default=str).encode()).hexdigest()[:10]
