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
DISCORD_ENABLED  = _b('CF_DISCORD_ENABLED', False)               # public cards only for PAPER fills
PUBLISH_PROPOSED = _b('CF_PUBLISH_PROPOSED', False)              # proposals stay in the journal (brief item 3)
CARD_SHOW_RETURN = _b('CF_CARD_SHOW_RETURN', False)              # simulated % return on member cards (item 7)
CARD_SHOW_CAMPAIGN_ID = _b('CF_CARD_SHOW_CAMPAIGN_ID', False)    # internal campaign id on member cards
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
MAX_PROPOSALS_PER_TICKER_DAY = _i('CF_MAX_PROPOSALS_PER_TICKER_DAY', 5)   # spec says 2; raised 2026-10-25
DEFAULT_HORIZON  = os.getenv('CF_DEFAULT_HORIZON', 'INTRADAY').upper()   # INTRADAY | OVERNIGHT | SWING
SWING_SESSIONS   = _i('CF_SWING_SESSIONS', 3)                    # SWING planned end = N trading sessions out
SWING_BUFFER_DAYS = _i('CF_SWING_BUFFER_DAYS', 1)
EXPIRY_LIQUIDATION_NY = os.getenv('CF_EXPIRY_LIQUIDATION_NY', '15:30')
PLANNED_END_NY   = os.getenv('CF_PLANNED_END_NY', '15:30')       # time of day a planned end lands on
QUOTE_MAX_AGE_S  = _f('CF_QUOTE_MAX_AGE_S', 30)
# A quote stamped later than the decision time by more than this is FUTURE-DATED (rejected). Decision time is
# the local receipt of the ticker's last response, so a real quote can only lead it by clock misalignment —
# measured 2026-10-19: local clock +0.05 s vs NTP. Not a staleness allowance.
QUOTE_CLOCK_TOL_S = _f('CF_QUOTE_CLOCK_TOL_S', 0.25)
MAX_REL_SPREAD   = _f('CF_MAX_REL_SPREAD', 0.30)
MIN_ASK_SIZE     = _i('CF_MIN_ASK_SIZE', 1)
BUDGET           = _f('CF_BUDGET', 2000.0)                       # reference paper premium budget
MAX_QTY          = _i('CF_MAX_QTY', 2)                           # planned contracts per proposal (cap)
ENTRY_ORDER_TTL_S = _i('CF_ENTRY_ORDER_TTL_S', 90)               # unfilled entry remainder is cancelled after
# Mag 7 brief item 4: at most N call entries and N put entries per session (0 = off). Scope ALL counts across
# the Mag 7 (one call + one put per day in total); TICKER counts per name. Every proposal that reserves or
# reached a fill counts — a stop-out does not reopen the slot, a rotation entry uses it, and a position
# carried overnight counts on the session it was opened. A proposal cancelled unfilled releases its slot.
MAX_ENTRIES_PER_RIGHT_DAY = _i('CF_MAX_ENTRIES_PER_RIGHT_DAY', 1)
ENTRY_CAP_SCOPE  = os.getenv('CF_ENTRY_CAP_SCOPE', 'ALL').upper()     # ALL | TICKER

# ── conviction tiers (Mag 7 brief item 5) ─────────────────────────────────────
# A verified cluster (§5) says WHERE flow concentrated; conviction says whether it looks institutional. Per
# ticker and right, over the last CONV_SPAN_S, across every near-the-money strike and observed expiry:
#   size        side contracts / their prior-session same-time-of-day baseline          >= CONV_MIN_REL_SIZE
#   intraday    side contracts per window / median per-window side volume earlier today  >= CONV_MIN_INTRADAY_REL
#   persistence consecutive latest windows with side volume >= CONV_SLOT_REL_MIN x baseline >= CONV_MIN_PERSIST
#   aggressor   near-ask share of side contracts                                          >= CONV_MIN_NEAR_ASK
#   dominance   side premium $ / (side + opposite premium $)                              >= CONV_MIN_DOMINANCE
#   support     share of side contracts in windows whose option mid rose (no reversal)    >= CONV_MIN_SUPPORT
# Each component scores min(1.5, value/threshold)/1.5; score = 100 x mean (66.7 = every component exactly at
# its threshold). Tier: CONFIRMED = score >= CONV_CONFIRMED_SCORE AND size, persistence and premium-$ floor
# met; BUILDING = score >= CONV_BUILDING_SCORE with size >= CONV_SLOT_REL_MIN; else WEAK. Entries need CONFIRMED (calibration: replays of
# 2026-10-30 TSLA, see HOW_IT_WORKS.md): with near-ask 0.25 the owner's good moments (09:45-09:49 calls,
# 11:05-11:12 puts) score 66-93 and the rejected ones (13:20-13:26 calls) 37-57, so CONFIRMED >= 65.
CONV_ENABLED     = _b('CF_CONV_ENABLED', True)
CONV_SPAN_S      = _i('CF_CONV_SPAN_S', 600)
CONV_MONEYNESS   = _f('CF_CONV_MONEYNESS', 0.03)                 # |strike / spot - 1| <= this is near the money
CONV_SLOT_REL_MIN = _f('CF_CONV_SLOT_REL_MIN', 2.0)
CONV_MIN_PERSIST = _i('CF_CONV_MIN_PERSIST', 3)
CONV_MIN_REL_SIZE = _f('CF_CONV_MIN_REL_SIZE', 3.0)
CONV_MIN_INTRADAY_REL = _f('CF_CONV_MIN_INTRADAY_REL', 2.0)
CONV_MIN_NEAR_ASK = _f('CF_CONV_MIN_NEAR_ASK', 0.25)   # snapshot proxy runs 0.1-0.35 on real flow
CONV_MIN_DOMINANCE = _f('CF_CONV_MIN_DOMINANCE', 0.60)
CONV_MIN_SUPPORT = _f('CF_CONV_MIN_SUPPORT', 0.50)
CONV_MIN_PREMIUM_USD = _f('CF_CONV_MIN_PREMIUM_USD', 250_000)   # side premium $ over the span (hard floor)
CONV_CONFIRMED_SCORE = _f('CF_CONV_CONFIRMED_SCORE', 65)
CONV_BUILDING_SCORE = _f('CF_CONV_BUILDING_SCORE', 45)

# ── §9 daily OI reference ────────────────────────────────────────────────────
OI_CUTOFF_MIN_BEFORE_OPEN = _i('CF_OI_CUTOFF_MIN', 10)
OI_STRIP         = _i('CF_OI_STRIP', 6)
OI_LEVELS        = _i('CF_OI_LEVELS', 3)

# ── §12 exits ────────────────────────────────────────────────────────────────
GAP_MIN_FRACTION = _f('CF_GAP_MIN_FRACTION', 0.0)
FOLLOWTHROUGH_MAX_GAP_S = _i('CF_FOLLOWTHROUGH_MAX_GAP_S', 420)
PREMIUM_LOSS_LIMIT = _of('CF_PREMIUM_LOSS_LIMIT')                # e.g. 0.5 — OFF unless set before entry
UNDERLYING_INVALIDATION_PCT = _of('CF_UNDERLYING_INVALIDATION_PCT')   # e.g. 0.01 below entry spot — OFF unless set
# Mag 7 brief item 6: a winner is not exited on a weak opposite signal. An opposite-cluster rotation exit
# needs the opposite side at CONFIRMED conviction with score >= CONV_CONFIRMED_SCORE x EXIT_CONV_HYSTERESIS
# (more evidence to exit than to enter), and only after the position has been held MIN_HOLD_S. In exchange a
# trailing stop protects the gain: once the bid has been >= ARM above the average entry, a bid that gives back
# GIVEBACK of the peak gain exits (TRAILING_STOP_FROM_PEAK). Calibrated on the 10-30 TSLA 395C path: it
# dipped 4.35 -> 3.15 (-55% of the gain) before running to 8.55, so +100% arm / 60% giveback. Deadline and precommitted risk exits are unchanged.
EXIT_CONV_HYSTERESIS = _f('CF_EXIT_CONV_HYSTERESIS', 1.20)
MIN_HOLD_S       = _i('CF_MIN_HOLD_S', 900)
TRAIL_ARM_GAIN   = _f('CF_TRAIL_ARM_GAIN', 1.00)                 # 0 = trailing stop off
TRAIL_GIVEBACK   = _f('CF_TRAIL_GIVEBACK', 0.60)                 # of the peak gain (peak_bid - avg_entry)

# ── overnight carry (Mag 7 brief item 1) ──────────────────────────────────────
# With the nearest expiration expiring today (Mon/Wed/Fri for the Mag 7), the runner also observes the next
# expiration, so flow positioned beyond today is visible. A verified cluster in a LATER expiration becomes an
# OVERNIGHT proposal (carried past the close, reviewed at the next open) when: it is CONFIRMED, the time is
# >= OVERNIGHT_FROM_NY, the day is consolidated (session high-low <= OVERNIGHT_MAX_RANGE_PCT of the open) and
# the premium already carried overnight plus this one stays <= OVERNIGHT_MAX_PREMIUM. Otherwise later-expiry
# flow is journaled, not traded. Held overnight: an open gap against the position by >= OVERNIGHT_MAX_ADVERSE_GAP
# exits at the open; at open + OVERNIGHT_REVIEW_S a carried position that is not in profit and whose own side is
# not at least BUILDING exits (the same conviction logic as entries). Planned end / expiry deadline still apply,
# so a carried contract is always sold before its 15:30 expiry-day cutoff — never held into expiration.
OVERNIGHT_ENABLED = _b('CF_OVERNIGHT_ENABLED', True)
OVERNIGHT_FROM_NY = os.getenv('CF_OVERNIGHT_FROM_NY', '12:00')
OVERNIGHT_MAX_RANGE_PCT = _f('CF_OVERNIGHT_MAX_RANGE_PCT', 0.02)
OVERNIGHT_MAX_PREMIUM = _f('CF_OVERNIGHT_MAX_PREMIUM', 600.0)    # $ premium carried overnight, all positions
OVERNIGHT_MAX_ADVERSE_GAP = _f('CF_OVERNIGHT_MAX_ADVERSE_GAP', 0.01)
OVERNIGHT_REVIEW_S = _i('CF_OVERNIGHT_REVIEW_S', 900)

# ── §13 exit quotes ──────────────────────────────────────────────────────────
EXIT_QUOTE_MAX_AGE_S = _f('CF_EXIT_QUOTE_MAX_AGE_S', 30)

# ── adapter (snapshot) definitions — §21 says these must be documented, not inferred ────────────
NEAR_ASK_LOCATION = _f('CF_NEAR_ASK_LOCATION', 0.80)             # trade price location in [bid,ask] >= this
SYNC_MIN_FRESH_FRAC = _f('CF_SYNC_MIN_FRESH_FRAC', 0.90)         # share of quotes <= QUOTE_MAX_AGE_S old
BASELINE_FLOOR   = _f('CF_BASELINE_FLOOR', 5.0)                  # contracts per window (avoids a 0 baseline)
UNDERLYING_WINDOW_S = _i('CF_UNDERLYING_WINDOW_S', 30)           # engine's WINDOW_FAST dS/dt rule

RULE_VERSION = 'cf-v1-' + hashlib.sha256(json.dumps(
    {k: v for k, v in sorted(globals().items()) if k.isupper() and k not in ('JOURNAL_DB', 'OBS_DIR', 'MODE', 'DISCORD_ENABLED', 'RECORD_OBS', 'PUBLISH_PROPOSED',
                                                           'CARD_SHOW_RETURN', 'CARD_SHOW_CAMPAIGN_ID')},
    default=str).encode()).hexdigest()[:10]
