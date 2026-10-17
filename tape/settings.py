"""Tape-lane parameters. Every threshold is a PROVISIONAL research rule (flow handoff), env-overridable,
and frozen into `RULE_HASH` so a replay states exactly which rules produced a record."""
import hashlib
import json
import os

import config


def _f(k, d): return float(os.getenv(k, str(d)))
def _i(k, d): return int(os.getenv(k, str(d)))
def _b(k, d): return os.getenv(k, 'true' if d else 'false').lower() == 'true'


# ── storage / process ─────────────────────────────────────────────────────────
DB_PATH          = os.getenv('TAPE_DB', 'jakenew_tape.db')
ARCHIVE_DIR      = os.getenv('TAPE_ARCHIVE_DIR', 'tape_raw')
PARSER_VERSION   = 'alpaca-opra-parser-v1'
QUEUE_MAX        = _i('TAPE_QUEUE_MAX', 50000)        # in-process event buffer; overflow = coverage incident
STALE_S          = _f('TAPE_STALE_S', 15)             # no message this long during the session → reconnect
RECONNECT_MAX_S  = _f('TAPE_RECONNECT_MAX_S', 60)

# ── universe (bounded, explicit denominator) ─────────────────────────────────
UNIVERSE         = [s.strip().upper() for s in os.getenv('TAPE_UNIVERSE', ','.join(config.MAG7)).split(',') if s.strip()]
MAX_DTE          = _i('TAPE_MAX_DTE', 45)
STRIKE_BAND_PCT  = _f('TAPE_STRIKE_BAND_PCT', 0.06)
MAX_CONTRACTS    = _i('TAPE_MAX_CONTRACTS', 400)      # confirm the account's quote-subscription entitlement

# ── quote-side reading (§3) ───────────────────────────────────────────────────
QUOTE_MAX_AGE_MS = _f('TAPE_QUOTE_MAX_AGE_MS', 500)
QUOTE_MAX_WIDTH  = _f('TAPE_QUOTE_MAX_WIDTH', 0.25)   # (ask-bid)/mid
ASK_FRAC         = _f('TAPE_ASK_FRAC', 0.80)
BID_FRAC         = _f('TAPE_BID_FRAC', 0.20)
SPOT_MAX_AGE_MS  = _f('TAPE_SPOT_MAX_AGE_MS', 5000)

# ── execution-mechanics candidates (§3) ───────────────────────────────────────
BLOCK_MIN        = _i('TAPE_BLOCK_MIN', 100)
BLOCK_REL        = _f('TAPE_BLOCK_REL', 5.0)
SWEEP_MIN        = _i('TAPE_SWEEP_MIN', 250)
SWEEP_VENUES     = _i('TAPE_SWEEP_VENUES', 2)
SWEEP_WINDOW_MS  = _f('TAPE_SWEEP_WINDOW_MS', 100)

# ── baselines (§4) ────────────────────────────────────────────────────────────
BASELINE_SESSIONS     = _i('TAPE_BASELINE_SESSIONS', 20)
BASELINE_MIN_SESSIONS = _i('TAPE_BASELINE_MIN_SESSIONS', 10)
BASELINE_MAX_STALE_D  = _i('TAPE_BASELINE_MAX_STALE_DAYS', 7)
PREMIUM_PCTL          = _f('TAPE_PREMIUM_PCTL', 95)
BOOTSTRAP_PAGES      = _i('TAPE_BOOTSTRAP_PAGES', 40)   # REST pages per (name, session) for the premium bootstrap

# ── UOA screens (§4) ──────────────────────────────────────────────────────────
REL_VOL_MULT     = _f('TAPE_REL_VOL_MULT', 5.0)
REL_PREM_MULT    = _f('TAPE_REL_PREM_MULT', 2.0)
OTM_MAX_DTE      = _i('TAPE_OTM_MAX_DTE', 7)
REPEAT_MIN_PRINTS = _i('TAPE_REPEAT_MIN_PRINTS', 3)
REPEAT_MIN_QTY   = _i('TAPE_REPEAT_MIN_QTY', 10)
REPEAT_MED_FRAC  = _f('TAPE_REPEAT_MED_FRAC', 0.20)
QUIET_MIN_TOTAL  = _i('TAPE_QUIET_MIN_TOTAL', 100)
QUIET_SESSIONS   = _i('TAPE_QUIET_SESSIONS', 5)
QUIET_MAX_DAILY  = _i('TAPE_QUIET_MAX_DAILY', 50)

# ── packages (§5) ─────────────────────────────────────────────────────────────
PKG_WINDOW_MS    = _f('TAPE_PKG_WINDOW_MS', 1000)
PKG_MAX_PRINTS   = _i('TAPE_PKG_MAX_PRINTS', 128)
PKG_MIN_SERIES   = _i('TAPE_PKG_MIN_SERIES_QTY', 100)
PKG_TIGHT_MS     = _f('TAPE_PKG_TIGHT_MS', 10)
PKG_LATENESS_MS  = _f('TAPE_PKG_LATENESS_MS', 2000)   # watermark slack before a window is finalised
PKG_MAX_RATIO_PART = _i('TAPE_PKG_MAX_RATIO_PART', 10) # complex orders fill in EXACT small ratios (4:7 ok, 668:667 not)
PKG_POST_MIN_GRADE = os.getenv('TAPE_PKG_POST_MIN_GRADE', 'C')  # D (time/size only) packages are stored, not posted

# ── working hypothesis / leading read (§6) ────────────────────────────────────
LR_MIN_PRINTS    = _i('TAPE_LR_MIN_PRINTS', 3)
LR_MIN_QTY       = _i('TAPE_LR_MIN_QTY', 500)
LR_OI_MULT       = _f('TAPE_LR_OI_MULT', 3.0)
LR_SIDE_SHARE    = _f('TAPE_LR_SIDE_SHARE', 0.60)
LR_MAX_UNKNOWN   = _f('TAPE_LR_MAX_UNKNOWN', 0.25)

# ── OI context (§7) ───────────────────────────────────────────────────────────
BB_SELL_SHARE    = _f('TAPE_BB_SELL_SHARE', 0.65)
BB_BUILD         = _f('TAPE_BB_BUILD', 0.50)
BB_RETAIN        = _f('TAPE_BB_RETAIN', 0.75)
BB_DAYS          = _i('TAPE_BB_DAYS', 14)
ROLL_SIZE_TOL    = _f('TAPE_ROLL_SIZE_TOL', 0.5)

# ── delivery (§9) ─────────────────────────────────────────────────────────────
# OFF until the provider's written redistribution terms are confirmed (§10). Cards are still rendered
# and stored in the tape DB either way.
DISCORD_ENABLED  = _b('TAPE_DISCORD_ENABLED', False)
CAMPAIGN_COOLDOWN_S = _f('TAPE_CAMPAIGN_COOLDOWN_S', 900)
WEBHOOKS = {b: os.getenv(f'DISCORD_WEBHOOK_{b.upper()}', '') for b in
            ('zero_dte', 'weekly', 'short_term', 'swing', 'long_dated')}
PRIVATE_WEBHOOK  = os.getenv('DISCORD_WEBHOOK_PRIVATE', '')

# ── outcomes (§11) ────────────────────────────────────────────────────────────
FEE_PER_CONTRACT = _f('TAPE_FEE_PER_CONTRACT', 0.65)
OUTCOME_HORIZONS_MIN = [int(x) for x in os.getenv('TAPE_OUTCOME_HORIZONS_MIN', '30,120').split(',') if x.strip()]

_FROZEN = {k: v for k, v in globals().items() if k.isupper() and k not in ('WEBHOOKS', 'PRIVATE_WEBHOOK', 'DB_PATH', 'ARCHIVE_DIR')}
RULE_HASH = hashlib.sha256(json.dumps(_FROZEN, sort_keys=True, default=str).encode()).hexdigest()[:12]
RULE_VERSION = f'tape-v1-{RULE_HASH}'
