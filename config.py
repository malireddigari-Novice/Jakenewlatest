"""
Jakenew configuration — the MAG-7 Attention Engine.

Every knob is an environment variable with a sane default, loaded from `.env`.
The whole system is built around ONE question — *where is institutional attention
flowing right now?* — so most of the tunables below shape the Attention Score and
its gate/exit thresholds rather than a grab-bag of independent signal engines.
"""
import os

from dotenv import load_dotenv

load_dotenv()

# ── The universe ─────────────────────────────────────────────────────────────
# Only the Mag-7 compete for the finite pool of institutional attention.
MAG7: list[str] = ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'NVDA', 'TSLA']

# ── Loop / session ───────────────────────────────────────────────────────────
# v2: fast loop. Execution cannot wait for one 60-second serial poll of every contract —
# a 0DTE event that starts at 09:30:05 may be up 30-100% by 09:31. We poll every few
# seconds and score over rolling 30s/60s/180s windows instead.
FAST_POLL_SECONDS     = int(os.getenv('FAST_POLL_SECONDS', '5'))
POLL_INTERVAL_SECONDS = FAST_POLL_SECONDS   # back-compat alias
BARS_TO_FETCH         = int(os.getenv('BARS_TO_FETCH', '40'))
# Rolling flow windows (seconds) used for fresh volume/premium, velocity, acceleration.
WINDOW_FAST = int(os.getenv('WINDOW_FAST', '30'))
WINDOW_MID  = int(os.getenv('WINDOW_MID',  '60'))
WINDOW_SLOW = int(os.getenv('WINDOW_SLOW', '180'))

SESSION_TZ          = os.getenv('SESSION_TZ', 'America/Chicago')
MARKET_OPEN_HOUR    = int(os.getenv('MARKET_OPEN_HOUR', '8'))
MARKET_OPEN_MINUTE  = int(os.getenv('MARKET_OPEN_MINUTE', '30'))
MARKET_CLOSE_HOUR   = int(os.getenv('MARKET_CLOSE_HOUR', '15'))
MARKET_CLOSE_MINUTE = int(os.getenv('MARKET_CLOSE_MINUTE', '0'))
# v2: the opening auction is NOT noise — it is often the clearest institutional commitment
# of the day (AAPL/NVDA/TSLA opening bursts). We SEED contract baselines during the
# pre-open window so fresh deltas are measured from the first seconds after the open, and
# apply STRICTER quality rules during the opening minutes rather than discarding them.
PREOPEN_SEED_MINUTES  = int(os.getenv('PREOPEN_SEED_MINUTES', '10'))   # seed baselines before open
OPENING_STRICT_MINUTES = int(os.getenv('OPENING_STRICT_MINUTES', '5')) # tighter gates just after open
# Legacy no-trade warm-up is OFF by default now (we capture the open instead).
SIGNAL_WARMUP_MINUTES = int(os.getenv('SIGNAL_WARMUP_MINUTES', '0'))
OPENING_RANGE_MINUTES = int(os.getenv('OPENING_RANGE_MINUTES', '5'))
# EOD flatten time (CST). Same-day convexity is always closed before the bell.
EOD_HOUR   = int(os.getenv('EOD_HOUR', '14'))
EOD_MINUTE = int(os.getenv('EOD_MINUTE', '55'))

# ── The Attention Engine (Layer 1 — cross-symbol allocation) ─────────────────
ATTENTION_ENABLED   = os.getenv('ATTENTION_ENABLED', 'true').lower() == 'true'
# A name must score >= this to be considered "in control of attention".
ATTENTION_SCORE_MIN = float(os.getenv('ATTENTION_SCORE_MIN', '70'))
# The pool must carry at least this much fresh $-premium before we allocate attention
# at all (below it, nobody owns the tape — sit out).
ATTENTION_MIN_TOTAL = float(os.getenv('ATTENTION_MIN_TOTAL', '250000'))

# Attention-Score weights (sum ≈ 1.0). Per the design spec.
ATTENTION_W_SHARE        = float(os.getenv('ATTENTION_W_SHARE', '0.40'))
ATTENTION_W_VELOCITY     = float(os.getenv('ATTENTION_W_VELOCITY', '0.25'))
ATTENTION_W_ACCELERATION = float(os.getenv('ATTENTION_W_ACCELERATION', '0.15'))
ATTENTION_W_CONTROL      = float(os.getenv('ATTENTION_W_CONTROL', '0.10'))
ATTENTION_W_LOW          = float(os.getenv('ATTENTION_W_LOW', '0.10'))

# ── Entry gate (Layer 3 — generate ONE trade) ────────────────────────────────
ATTENTION_GATE_ENABLED         = os.getenv('ATTENTION_GATE_ENABLED', 'true').lower() == 'true'
ATTENTION_GATE_MAX_RANK        = int(os.getenv('ATTENTION_GATE_MAX_RANK', '2'))
ATTENTION_GATE_REQUIRE_CONTROL = os.getenv('ATTENTION_GATE_REQUIRE_CONTROL', 'true').lower() == 'true'
# Single-trade discipline: hold at most ONE convexity position — the day's attention
# leader. This is the whole point of the rebuild ("you needed maybe 2 alerts").
ATTENTION_SINGLE_TRADE = os.getenv('ATTENTION_SINGLE_TRADE', 'true').lower() == 'true'
# Cooldown (minutes) after a fill before the same name may be re-entered.
SIGNAL_COOLDOWN_MINUTES = int(os.getenv('SIGNAL_COOLDOWN_MINUTES', '30'))

# ── Attention exit (Layer 4 — leave when the thesis dies) ────────────────────
# Exit an open position when attention ROTATES away or within-name control FLIPS,
# but only after N consecutive polls of deterioration (anti-churn).
ATTENTION_EXIT_ENABLED     = os.getenv('ATTENTION_EXIT_ENABLED', 'true').lower() == 'true'
ATTENTION_EXIT_ROTATE_RANK = int(os.getenv('ATTENTION_EXIT_ROTATE_RANK', '2'))
ATTENTION_EXIT_SUSTAIN     = int(os.getenv('ATTENTION_EXIT_SUSTAIN', '3'))

# ── Structural exit (the OTHER reason to leave — objective achieved) ─────────
# A simple profit-objective ladder standing in for OI-based targets: bank the
# first slice at +TP1, the rest at +TP2, and protect gains with a giveback trail.
TAKE_PROFIT_1_PCT   = float(os.getenv('TAKE_PROFIT_1_PCT', '0.60'))   # +60%  → sell half
TAKE_PROFIT_2_PCT   = float(os.getenv('TAKE_PROFIT_2_PCT', '1.50'))   # +150% → sell rest
TRAIL_GIVEBACK_PCT  = float(os.getenv('TRAIL_GIVEBACK_PCT', '0.35'))  # give back 35% of peak → out
TRAIL_ARM_PCT       = float(os.getenv('TRAIL_ARM_PCT', '0.40'))       # trail only arms past +40%
# Hard stop-loss — a risk backstop that caps the per-trade tail. Fires regardless of min-hold
# or thesis state (risk management overrides everything but a completed fill). 0 disables it.
STOP_LOSS_PCT       = float(os.getenv('STOP_LOSS_PCT', '0.40'))       # close at -40%
# No NEW entries within this many minutes of the EOD flatten — avoids late 0DTE lottery tickets
# and the overnight-hold bug (a fill after the once-daily flatten would never be closed).
ENTRY_CUTOFF_BUFFER_MIN = int(os.getenv('ENTRY_CUTOFF_BUFFER_MIN', '15'))

# ── Fresh-premium measurement ────────────────────────────────────────────────
# Strikes within this % band of spot are considered relevant convexity.
PREMIUM_BAND_PCT     = float(os.getenv('PREMIUM_BAND_PCT', '0.03'))
# Nearest-N strikes per side to sample for each symbol.
PREMIUM_STRIKES_PER_SIDE = int(os.getenv('PREMIUM_STRIKES_PER_SIDE', '3'))

# ── Entry strike selection ───────────────────────────────────────────────────
# Buy the at-the-money strike. If true ATM has no usable quote, step at most this many
# strikes away toward the next-closest (1 = "ATM, or the very next"). Never chase further —
# if the ATM window is unquotable the trade is skipped rather than filled far from the money.
ENTRY_ATM_MAX_STEPS = int(os.getenv('ENTRY_ATM_MAX_STEPS', '1'))

# ── Charles Schwab (OI / structural context; optional) ───────────────────────
# Register a developer app at developer.schwab.com; callback https://127.0.0.1.
SCHWAB_ENABLED      = os.getenv('SCHWAB_ENABLED', 'true').lower() == 'true'
SCHWAB_API_KEY      = os.getenv('SCHWAB_API_KEY', '')
SCHWAB_APP_SECRET   = os.getenv('SCHWAB_APP_SECRET', '')
SCHWAB_CALLBACK_URL = os.getenv('SCHWAB_CALLBACK_URL', 'https://127.0.0.1')
SCHWAB_TOKEN_FILE   = os.getenv('SCHWAB_TOKEN_FILE', 'schwab_token.json')
NEAR_OI_EXPIRY_DAYS = int(os.getenv('NEAR_OI_EXPIRY_DAYS', '7'))
OPT_HIST_LOOKBACK_DAYS = int(os.getenv('OPT_HIST_LOOKBACK_DAYS', '10'))

# ── Alpaca (intraday data + execution) ───────────────────────────────────────
ALPACA_API_KEY     = os.getenv('ALPACA_API_KEY', '')
ALPACA_SECRET_KEY  = os.getenv('ALPACA_SECRET_KEY', '')
ALPACA_PAPER       = os.getenv('ALPACA_PAPER',   'true').lower()  == 'true'
ALPACA_ENABLED     = os.getenv('ALPACA_ENABLED', 'false').lower() == 'true'
TRADE_PCT          = float(os.getenv('TRADE_PCT', '0.01'))   # fraction of portfolio value per trade
MAX_OPEN_POSITIONS = int(os.getenv('MAX_OPEN_POSITIONS', '1'))

# ── Notifications (optional) ─────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')

# ═══════════════════════════════════════════════════════════════════════════════
# v2 RESEARCH PARAMETERS
# The four-layer architecture: (1) which ticker owns fresh attention, (2) which side
# controls it, (3) what form the event takes + best contract, (4) position management.
# EVERYTHING below is a research hypothesis, not production truth — stored here so it can
# be tuned and back-tested. Nothing here trades real money until validated in shadow.
# ═══════════════════════════════════════════════════════════════════════════════

# ── Layer 1: blended cross-ticker attention (not premium-share alone) ─────────
# Raw premium dollars favour expensive chains (META $7 > AAPL $0.75) even when AAPL has
# far greater participation/convexity demand. Blend several normalised factors instead.
AW_PREMIUM_SHARE = float(os.getenv('AW_PREMIUM_SHARE', '0.22'))  # $ notional share of the pool
AW_VOLUME_SHARE  = float(os.getenv('AW_VOLUME_SHARE',  '0.18'))  # fresh-contract share of the pool
AW_SHOCK         = float(os.getenv('AW_SHOCK',         '0.25'))  # abnormality vs the ticker's own baseline
AW_VELOCITY      = float(os.getenv('AW_VELOCITY',      '0.15'))  # is fresh flow rising?
AW_ACCELERATION  = float(os.getenv('AW_ACCELERATION',  '0.08'))  # is the rise speeding up?
AW_CONTROL       = float(os.getenv('AW_CONTROL',       '0.06'))  # one-sidedness of control
AW_EVENT_QUALITY = float(os.getenv('AW_EVENT_QUALITY', '0.06'))  # concentration/compactness quality

# Attention Shock = (current fresh activity − expected) / (dispersion + eps), self-normalised
# per ticker. Baseline is a rolling EWMA of that ticker's own per-poll fresh premium (a proxy
# until per-time-of-day historical baselines are stored). AAPL doing $500k when it usually does
# $80k outweighs META doing $700k when META usually does $600k.
SHOCK_BASELINE_ALPHA = float(os.getenv('SHOCK_BASELINE_ALPHA', '0.05'))  # EWMA weight of new sample
SHOCK_EPS            = float(os.getenv('SHOCK_EPS', '1000.0'))           # dispersion floor
SHOCK_CLIP           = float(os.getenv('SHOCK_CLIP', '8.0'))             # clip z to +/- this

# ── Hard eligibility gates (pass/fail BEFORE ranking) ─────────────────────────
# A single 0-100 score must NOT let mediocre factors compensate for a critical failure.
# A name is eligible only if it clears every gate; then eligible names are ranked by score.
GATE_MIN_SYMBOL_PREMIUM = float(os.getenv('GATE_MIN_SYMBOL_PREMIUM', '100000'))   # fresh $ in the name
GATE_MIN_EVENT_NOTIONAL = float(os.getenv('GATE_MIN_EVENT_NOTIONAL', '55000'))   # fresh $ in the chosen contract
GATE_MIN_CONTROL_SHARE  = float(os.getenv('GATE_MIN_CONTROL_SHARE',  '0.60'))    # dominant-side share
GATE_MAX_SPREAD_PCT     = float(os.getenv('GATE_MAX_SPREAD_PCT',     '0.15'))    # (ask-bid)/mid ceiling
GATE_MIN_QUOTE_SIZE     = int(os.getenv('GATE_MIN_QUOTE_SIZE', '5'))             # min bid/ask size (contracts)
GATE_MAX_QUOTE_STALE_S  = float(os.getenv('GATE_MAX_QUOTE_STALE_S', '10.0'))     # quote age ceiling (s)
GATE_MAX_DIST_FROM_LOW  = float(os.getenv('GATE_MAX_DIST_FROM_LOW', '1.50'))     # mark <= 1.5x session low: buy on value, never chase after the pop
GATE_MIN_TOP_STRIKE_SHARE = float(os.getenv('GATE_MIN_TOP_STRIKE_SHARE', '0.35'))# reject distributed background
# During OPENING_STRICT_MINUTES these floors are multiplied up (opening events must be cleaner).
OPENING_STRICT_MULT = float(os.getenv('OPENING_STRICT_MULT', '1.4'))

# ── Price-response validation (ACCUMULATION vs DISTRIBUTION) ──────────────────
# Large option volume is not inherently directional. Only ACCUMULATION is tradeable: fresh
# volume arriving while the option is still cheap and the PREMIUM RESPONDS positively (expands).
# Heavy volume while the premium is COLLAPSING is distribution / liquidation / exit flow — it
# must be management info, never a new entry. A wave records its event price at birth; at entry
# we require the option to have expanded (not bled) since the event.
REQUIRE_ACCUMULATION = os.getenv('REQUIRE_ACCUMULATION', 'true').lower() == 'true'
RESP_EVENT_MIN  = float(os.getenv('RESP_EVENT_MIN',  '-0.02'))  # option must not have fallen >2% since event began
RESP_NEG_REJECT = float(os.getenv('RESP_NEG_REJECT', '-0.05'))  # >5% collapse since event = HEAVY_VOLUME_NEGATIVE_RESPONSE
RESP_RECENT_WINDOW_S = float(os.getenv('RESP_RECENT_WINDOW_S', '120'))  # short-momentum window (lower-lows check)
# Volume-pattern metrics (compact institutional burst detection, per the TSLA 312.5P case).
VP_TRAIL_S           = float(os.getenv('VP_TRAIL_S', '1200'))   # 20-min trailing window
VP_EVENT_MIN         = int(os.getenv('VP_EVENT_MIN', '4'))      # event window = last N minutes
VP_EVENTSHARE20_MIN  = float(os.getenv('VP_EVENTSHARE20_MIN', '0.45'))  # event vol / trailing-20 vol
VP_TOP3SHARE20_MIN   = float(os.getenv('VP_TOP3SHARE20_MIN', '0.55'))   # top-3 minutes / trailing-20 vol
VP_BURST_PERSIST_MIN = int(os.getenv('VP_BURST_PERSIST_MIN', '2'))      # consecutive elevated minutes
VP_MEANINGFUL_MULT   = float(os.getenv('VP_MEANINGFUL_MULT', '2.0'))    # a minute is "meaningful" > this x pre-event mean
VP_VALUE_LOW_MAX     = float(os.getenv('VP_VALUE_LOW_MAX', '1.50'))     # ValueLowDistance ceiling (mature above)

# ── Layer 2: internal control state machine ───────────────────────────────────
# More call premium does not prove bullish call BUYING (could be selling/spreads/rolls).
# Control blends premium share with the OPPOSITE side's awakening (accel) + persistence +
# quote-location, and resolves to one of five states.
CONTROL_STRONG_SHARE   = float(os.getenv('CONTROL_STRONG_SHARE', '0.66'))  # dominant enough to "control"
CONTROL_BALANCED_BAND  = float(os.getenv('CONTROL_BALANCED_BAND', '0.55')) # below this = contested
CONTROL_AWAKEN_ACCEL   = float(os.getenv('CONTROL_AWAKEN_ACCEL', '0.0'))   # opp-side accel > 0 = awakening
CONTROL_PERSIST_POLLS  = int(os.getenv('CONTROL_PERSIST_POLLS', '2'))      # polls of dominance = persistent

# ── Layer 3: event classification + contract selection ────────────────────────
# Distinguish a dominant single-strike event from a coordinated chain, an emergent/ramp event,
# and mere distributed background. Event quality feeds both the gate and the score.
EVENT_SINGLE_TOP_SHARE  = float(os.getenv('EVENT_SINGLE_TOP_SHARE', '0.60'))  # one strike owns the flow
EVENT_CHAIN_TOP3_SHARE  = float(os.getenv('EVENT_CHAIN_TOP3_SHARE', '0.75'))  # ATM+adjacent own it together
EVENT_CHAIN_MIN_STRIKES = int(os.getenv('EVENT_CHAIN_MIN_STRIKES', '2'))      # active strikes for a chain
# Contract selection: best of ATM +/- this many steps (NOT blindly ATM, no far-OTM lottery).
ENTRY_ADJACENT_STEPS = int(os.getenv('ENTRY_ADJACENT_STEPS', '1'))
# Strike-activation: reward a strike moving OTM→ATM with fresh volume accelerating.
ACTIVATION_NEAR_ATM_PCT = float(os.getenv('ACTIVATION_NEAR_ATM_PCT', '0.004'))  # |K-S|/S considered ATM
# FAST_CONVEXITY_ACTIVATION: a faster promotion route inside the current partial window when
# activity is overwhelmingly clear (does not wait for a completed bar).
FAST_ACTIVATION_SHOCK   = float(os.getenv('FAST_ACTIVATION_SHOCK', '3.0'))      # shock z to fast-track
FAST_ACTIVATION_SHARE   = float(os.getenv('FAST_ACTIVATION_SHARE', '0.45'))     # min attention share

# ── Entry freshness (opportunity decay — don't chase after the pop) ───────────
# A correct signal can already be un-tradeable. Grade by premium change since first detection.
FRESH_EARLY_PCT    = float(os.getenv('FRESH_EARLY_PCT',    '0.15'))  # < +15% over first-qualified price
FRESH_ACTIVE_PCT   = float(os.getenv('FRESH_ACTIVE_PCT',   '0.35'))  # +15..35%
FRESH_EXTENDED_PCT = float(os.getenv('FRESH_EXTENDED_PCT', '0.50'))  # +35..50%  (> this = MISSED, no entry)
FRESH_BLOCK_MISSED = os.getenv('FRESH_BLOCK_MISSED', 'true').lower() == 'true'

# ── Layer 4: position management ──────────────────────────────────────────────
# One primary position by default; an OPTIONAL second only when a second ticker independently
# clears an exceptional threshold. Rank loss ALONE never forces an exit.
MAX_PRIMARY_POSITIONS   = int(os.getenv('MAX_PRIMARY_POSITIONS', '1'))
ALLOW_SECOND_POSITION   = os.getenv('ALLOW_SECOND_POSITION', 'false').lower() == 'true'
SECOND_POSITION_SHOCK   = float(os.getenv('SECOND_POSITION_SHOCK', '4.0'))   # exceptional shock for a 2nd
SECOND_POSITION_SHARE   = float(os.getenv('SECOND_POSITION_SHARE', '0.50'))

# Asymmetric exits — fast when the reversal is overwhelming, confirmed when moderate.
EXIT_IMMEDIATE_OPP_SHARE = float(os.getenv('EXIT_IMMEDIATE_OPP_SHARE', '0.75'))  # opp control overwhelming
EXIT_IMMEDIATE_SHOCK     = float(os.getenv('EXIT_IMMEDIATE_SHOCK', '3.0'))       # + abnormal/accelerating
EXIT_FAST_CONFIRM_POLLS  = int(os.getenv('EXIT_FAST_CONFIRM_POLLS', '2'))        # moderate evidence: 2 fast polls
EXIT_MODERATE_SUSTAIN    = int(os.getenv('EXIT_MODERATE_SUSTAIN', '3'))          # weak evidence: slower
# Rank drop does not exit a still-controlled, profitable position; only a genuine control loss does.
EXIT_REQUIRE_CONTROL_LOSS = os.getenv('EXIT_REQUIRE_CONTROL_LOSS', 'true').lower() == 'true'

# Cooldown: suppress DUPLICATE signals, not legitimate regime changes.
SIGNAL_COOLDOWN_MINUTES = int(os.getenv('SIGNAL_COOLDOWN_MINUTES', '15'))
# Cooldown is BYPASSED on any of: opposite-side control transfer, a materially stronger event
# (shock jump), a substantially improved contract price, or a fresh attention shock.
COOLDOWN_BYPASS_SHOCK      = float(os.getenv('COOLDOWN_BYPASS_SHOCK', '3.5'))
COOLDOWN_BYPASS_PRICE_IMPR = float(os.getenv('COOLDOWN_BYPASS_PRICE_IMPR', '0.20'))  # 20% cheaper than last entry

# ── Execution controls (never "buy at the ask") ───────────────────────────────
EXEC_LIMIT_OFFSET_PCT = float(os.getenv('EXEC_LIMIT_OFFSET_PCT', '0.02'))  # limit = mid × (1+offset)
EXEC_MAX_SLIPPAGE_PCT = float(os.getenv('EXEC_MAX_SLIPPAGE_PCT', '0.05'))  # abort if mid moved past this
EXEC_MAX_SPREAD_PCT   = float(os.getenv('EXEC_MAX_SPREAD_PCT', '0.15'))    # abort fill if spread too wide
EXEC_MIN_QUOTE_SIZE   = int(os.getenv('EXEC_MIN_QUOTE_SIZE', '5'))         # abort if book too thin

# ═══════════════════════════════════════════════════════════════════════════════
# ATTENTION-WAVE STATE MACHINE  (one wave = one entry)
# Detect the birth → growth → peak → decay → death of a single institutional attention
# wave per ticker/side, instead of firing a trade every qualifying minute. Target output:
# 0-3 waves per session, ≤5 primary entries/day. All thresholds are research parameters.
# ═══════════════════════════════════════════════════════════════════════════════
WAVE_ENABLED = os.getenv('WAVE_ENABLED', 'true').lower() == 'true'

# §1 strike-relevance weight  w_k = exp(-alpha · |K-S|/S)  (ATM≈1, 1 adj≈0.8, 2 away≈0.6).
WAVE_RELEVANCE_ALPHA = float(os.getenv('WAVE_RELEVANCE_ALPHA', '22.0'))
WAVE_STRIKES_EACH_SIDE = int(os.getenv('WAVE_STRIKES_EACH_SIDE', '2'))   # ATM ±2 in the high-weight area

# §3 fast/slow EWMA of ticker mass + impulse.
WAVE_LAMBDA_FAST = float(os.getenv('WAVE_LAMBDA_FAST', '0.65'))
WAVE_LAMBDA_SLOW = float(os.getenv('WAVE_LAMBDA_SLOW', '0.20'))
WAVE_EPS = float(os.getenv('WAVE_EPS', '1000.0'))

# §4 adaptive abnormality baseline (EWMA mean/var; frozen while abnormal to stay "non-event").
WAVE_BASELINE_ALPHA   = float(os.getenv('WAVE_BASELINE_ALPHA', '0.05'))
WAVE_BASELINE_FREEZE_Z = float(os.getenv('WAVE_BASELINE_FREEZE_Z', '1.5'))

# §7 strike-distribution classification.
WAVE_SINGLE_TOP_SHARE  = float(os.getenv('WAVE_SINGLE_TOP_SHARE', '0.60'))
WAVE_CHAIN_MIN_SHARE   = float(os.getenv('WAVE_CHAIN_MIN_SHARE', '0.20'))
WAVE_CHAIN_SECOND_FRAC = float(os.getenv('WAVE_CHAIN_SECOND_FRAC', '0.30'))

# ── Chain-led events require SUBSTANTIALLY stronger evidence than single strikes ──────
# A chain is a *synchronized shape*, not three mediocre strikes summed. To be a
# COORDINATED_CHAIN (not SINGLE_STRIKE_DOMINANT), at least two strikes must each own a
# meaningful share of the side's mass AND the top two together must dominate (synchronised).
# Chain entries then face a higher notional floor than single-strike entries.
CHAIN_MIN_SECOND_SHARE = float(os.getenv('CHAIN_MIN_SECOND_SHARE', '0.28'))  # 2nd strike's share of side mass
CHAIN_MIN_TOP2_SHARE   = float(os.getenv('CHAIN_MIN_TOP2_SHARE', '0.70'))    # top-2 combined (coherence)
CHAIN_NOTIONAL_MULT    = float(os.getenv('CHAIN_NOTIONAL_MULT', '1.5'))      # chain event-notional floor multiplier

# ── §14/§15 — unified institutional-campaign assessment ──────────────────────────────
# The engine's entry decision is ONE explicit verdict — "is this a genuine institutional
# campaign starting while convexity is still cheap?" — not a scattered set of threshold checks.
# A campaign is CONFIRMED only when all five entry signals hold (leadership, waking, accumulation,
# control, cheap) AND the combined conviction clears CAMPAIGN_MIN_SCORE. Precision over frequency.
CAMPAIGN_ENABLED     = os.getenv('CAMPAIGN_ENABLED', 'true').lower() == 'true'
CAMPAIGN_MIN_SCORE   = float(os.getenv('CAMPAIGN_MIN_SCORE', '62'))
CAMPAIGN_WAKE_Z      = float(os.getenv('CAMPAIGN_WAKE_Z', '3.0'))    # dormant flow "woke up"
CAMPAIGN_CONTROL_MIN = float(os.getenv('CAMPAIGN_CONTROL_MIN', '0.66'))  # side owns the tape
CW_LEADERSHIP   = float(os.getenv('CW_LEADERSHIP', '0.30'))
CW_WAKING       = float(os.getenv('CW_WAKING', '0.20'))
CW_ACCUMULATION = float(os.getenv('CW_ACCUMULATION', '0.25'))
CW_CONTROL      = float(os.getenv('CW_CONTROL', '0.15'))
CW_CHEAP        = float(os.getenv('CW_CHEAP', '0.10'))

# §8 lead requirement (ticker may be a candidate only when it leads Mag-7 attention).
WAVE_LEAD_SHARE    = float(os.getenv('WAVE_LEAD_SHARE', '0.42'))
WAVE_LEAD_Z_STRONG = float(os.getenv('WAVE_LEAD_Z_STRONG', '3.0'))
WAVE_LEAD_Z_MID    = float(os.getenv('WAVE_LEAD_Z_MID', '2.5'))
WAVE_LEAD_IMPULSE  = float(os.getenv('WAVE_LEAD_IMPULSE', '1.75'))
# The leader must clearly DOMINATE (lead rank-2 by this Attention-Score margin) to enter — in a
# contested pool nobody leads by the margin, so the engine sits out (spec §18: 'occasionally no trades').
WAVE_LEAD_MARGIN   = float(os.getenv('WAVE_LEAD_MARGIN', '10.0'))

# §9 FORMING / ACTIVE transitions.
WAVE_FORMING_Z       = float(os.getenv('WAVE_FORMING_Z', '2.0'))
WAVE_FORMING_CONTROL = float(os.getenv('WAVE_FORMING_CONTROL', '0.55'))
WAVE_ACTIVE_SHARE    = float(os.getenv('WAVE_ACTIVE_SHARE', '0.30'))
WAVE_ACTIVE_CONTROL  = float(os.getenv('WAVE_ACTIVE_CONTROL', '0.60'))
WAVE_ACTIVE_Z        = float(os.getenv('WAVE_ACTIVE_Z', '3.0'))
WAVE_ACTIVE_CONFIRM  = int(os.getenv('WAVE_ACTIVE_CONFIRM', '3'))         # consecutive evals (normal route)
WAVE_IMMEDIATE_Z       = float(os.getenv('WAVE_IMMEDIATE_Z', '4.0'))      # immediate route (fast 0DTE)
WAVE_IMMEDIATE_SHARE   = float(os.getenv('WAVE_IMMEDIATE_SHARE', '0.40'))
WAVE_IMMEDIATE_CONTROL = float(os.getenv('WAVE_IMMEDIATE_CONTROL', '0.70'))

# §12 leadership-transfer hysteresis (do not rotate on a 1-point crossing).
WAVE_ROT_WATCH_MARGIN   = float(os.getenv('WAVE_ROT_WATCH_MARGIN', '8.0'))
WAVE_ROT_CONFIRM_MARGIN = float(os.getenv('WAVE_ROT_CONFIRM_MARGIN', '15.0'))
WAVE_ROT_PERSIST_EVALS  = int(os.getenv('WAVE_ROT_PERSIST_EVALS', '2'))
WAVE_ROT_CONFIRM_Z      = float(os.getenv('WAVE_ROT_CONFIRM_Z', '3.5'))
WAVE_ROT_CONFIRM_SHARE  = float(os.getenv('WAVE_ROT_CONFIRM_SHARE', '0.40'))
WAVE_ROT_CONFIRM_CONTROL = float(os.getenv('WAVE_ROT_CONFIRM_CONTROL', '0.70'))

# Minimum wave commitment — a young wave is protected from thesis-exits (rotation / control
# transfer / exhaustion) for this long UNLESS the reversal is overwhelming. Stops 1-2 minute
# round-trips (§10/§14E: "do not end an event on ordinary one-minute noise"). Time-based so it
# holds identically at the live 5s cadence and the 1-min backtest.
WAVE_MIN_HOLD_SECONDS = float(os.getenv('WAVE_MIN_HOLD_SECONDS', '180'))
# Overwhelming-flip bar that may bypass the min-hold (very high, rare).
WAVE_FLIP_OVERWHELM_CONTROL = float(os.getenv('WAVE_FLIP_OVERWHELM_CONTROL', '0.78'))
WAVE_FLIP_OVERWHELM_Z       = float(os.getenv('WAVE_FLIP_OVERWHELM_Z', '5.0'))

# §13 control-flip inside an active trade (opposite ACTIVATION ≠ opposite CONTROL).
WAVE_FLIP_AWAKEN_Z        = float(os.getenv('WAVE_FLIP_AWAKEN_Z', '2.0'))
WAVE_FLIP_AWAKEN_CONTROL  = float(os.getenv('WAVE_FLIP_AWAKEN_CONTROL', '0.45'))
WAVE_FLIP_IMMEDIATE_CONTROL = float(os.getenv('WAVE_FLIP_IMMEDIATE_CONTROL', '0.60'))
WAVE_FLIP_IMMEDIATE_Z     = float(os.getenv('WAVE_FLIP_IMMEDIATE_Z', '3.0'))
WAVE_FLIP_PERSIST_CONTROL = float(os.getenv('WAVE_FLIP_PERSIST_CONTROL', '0.55'))
WAVE_FLIP_PERSIST_Z       = float(os.getenv('WAVE_FLIP_PERSIST_Z', '2.0'))
WAVE_FLIP_PERSIST_EVALS   = int(os.getenv('WAVE_FLIP_PERSIST_EVALS', '2'))

# §14 statistical-exhaustion end.
WAVE_END_Z     = float(os.getenv('WAVE_END_Z', '1.0'))
WAVE_END_SHARE = float(os.getenv('WAVE_END_SHARE', '0.15'))
WAVE_END_EVALS = int(os.getenv('WAVE_END_EVALS', '3'))

# §15 refractory period + new-wave renewal override.
WAVE_REFRACTORY_MIN     = float(os.getenv('WAVE_REFRACTORY_MIN', '20'))
WAVE_RENEW_Z            = float(os.getenv('WAVE_RENEW_Z', '4.0'))
WAVE_RENEW_FASTMASS_MULT = float(os.getenv('WAVE_RENEW_FASTMASS_MULT', '1.75'))
WAVE_RENEW_MIN_Z        = float(os.getenv('WAVE_RENEW_MIN_Z', '2.5'))

# §16 minimum notional (hard gate; reuse the execution/gate floors already defined above).

# ═══════════════════════════════════════════════════════════════════════════════
# EVENT-SHAPE-THROUGH-TIME  (research direction: model the whole event, not a fixed wait)
# Early-campaign entry with a DTE-sensitive confirmation window, phase-aware response
# EFFICIENCY, a JOINT distribution probability, Bayesian conviction, and expected-value
# timing. Every knob here DEGRADES to the previously-validated behaviour when its extra
# inputs (implied vol, days-to-expiry, aggressor side) are unavailable — so the backtest,
# which carries no IV and a constant delta, still runs and the validated edge is preserved
# until these gates are deliberately tightened via .env.
# ═══════════════════════════════════════════════════════════════════════════════

# ── DTE-sensitive evidence / confirmation windows ─────────────────────────────
# Confirmation cannot be a fixed wait. A 0DTE has ~30-90s before the convexity is gone; a
# 1DTE can develop for minutes; 2DTE+ can demand more persistence.  active_confirm = the
# consecutive normal-route evals to promote FORMING→ACTIVE;  min_hold_s = young-wave
# protection from thesis-exits;  max_forming_s = the MAXIMUM confirmation window before an
# un-promoted FORMING wave is declared FAILED_FORMATION.  Unknown DTE (or the feature off)
# preserves the old fixed constants and never times a forming wave out.
DTE_TIMING_ENABLED = os.getenv('DTE_TIMING_ENABLED', 'true').lower() == 'true'
DTE_TIMING = {
    0: {'active_confirm': 1, 'min_hold_s': 120.0, 'max_forming_s': 120.0},
    1: {'active_confirm': 2, 'min_hold_s': 180.0, 'max_forming_s': 300.0},
    2: {'active_confirm': 3, 'min_hold_s': 240.0, 'max_forming_s': 600.0},
}


def dte_bucket(dte):
    """Map days-to-expiry → {0, 1, 2+} bucket, or None when unknown."""
    if dte is None:
        return None
    try:
        d = int(dte)
    except (TypeError, ValueError):
        return None
    return 0 if d <= 0 else 1 if d == 1 else 2


def dte_timing(dte):
    """Timing profile for a DTE. Unknown DTE (or feature off) → the previously-validated
    fixed constants, with NO forming-window timeout (max_forming_s = None)."""
    b = dte_bucket(dte) if DTE_TIMING_ENABLED else None
    if b is None:
        return {'active_confirm': WAVE_ACTIVE_CONFIRM,
                'min_hold_s': WAVE_MIN_HOLD_SECONDS, 'max_forming_s': None}
    return dict(DTE_TIMING[b])


# ── Implied-volatility confirmation (dIV/dt) ──────────────────────────────────
# IV rising / firm supports accumulation; IV rolling over while premium stalls supports
# distribution. IV is not always available (historical bars carry none), so it is a
# CONTRIBUTING signal — never a hard block unless REQUIRE_IV_CONFIRM is set.
IV_ENABLED         = os.getenv('IV_ENABLED', 'true').lower() == 'true'
REQUIRE_IV_CONFIRM = os.getenv('REQUIRE_IV_CONFIRM', 'false').lower() == 'true'
IV_FIRM_SLOPE      = float(os.getenv('IV_FIRM_SLOPE', '-0.002'))   # dIV over the window >= this = firm/rising
IV_SLOPE_WINDOW_S  = float(os.getenv('IV_SLOPE_WINDOW_S', '120'))

# ── Delta-adjusted notional ── contracts × price × 100 × |delta| — directional exposure,
# not just gross dollars. Computed alongside raw notional; floor default 0 = off (parity with
# the validated notional gate). Raise DELTA_ADJ_NOTIONAL_MIN to require real directional size.
DELTA_ADJ_ENABLED      = os.getenv('DELTA_ADJ_ENABLED', 'true').lower() == 'true'
DELTA_ADJ_NOTIONAL_MIN = float(os.getenv('DELTA_ADJ_NOTIONAL_MIN', '0'))

# ── Response efficiency (premium progress per unit of fresh flow) + decay ─────
# ΔP% normalised by how much fresh notional it took. High in early accumulation, decays
# toward maturity/exhaustion. RESP_EFF_REF_NOTIONAL = the $ of fresh notional that counts as
# "one unit" of flow. Decay = current − campaign-peak efficiency (negative = deteriorating).
RESP_EFF_REF_NOTIONAL = float(os.getenv('RESP_EFF_REF_NOTIONAL', '100000'))
RESP_EFF_DECAY_WATCH  = float(os.getenv('RESP_EFF_DECAY_WATCH', '-0.5'))

# ── Distribution probability (joint, 0-1) ── weighted logistic over the deterioration
# features (extension, efficiency decay, relative premium, IV roll-over, peak giveback,
# opposite-side acceleration, spot fade). Above *_MAX_ENTRY it vetoes a new entry; above
# *_REDUCE it trims a live position; above *_EXIT it corroborates a thesis-death exit.
DIST_PROB_ENABLED   = os.getenv('DIST_PROB_ENABLED', 'true').lower() == 'true'
DIST_PROB_MAX_ENTRY = float(os.getenv('DIST_PROB_MAX_ENTRY', '0.60'))
DIST_PROB_REDUCE    = float(os.getenv('DIST_PROB_REDUCE', '0.60'))
DIST_PROB_EXIT      = float(os.getenv('DIST_PROB_EXIT', '0.78'))
DIST_PROB_BIAS = float(os.getenv('DIST_PROB_BIAS', '-2.2'))   # baseline logit (distribution prior is low)
DW_EXTENSION   = float(os.getenv('DW_EXTENSION',   '1.1'))    # far above the value low
DW_EFF_DECAY   = float(os.getenv('DW_EFF_DECAY',   '1.3'))    # response efficiency decaying
DW_REL_PREMIUM = float(os.getenv('DW_REL_PREMIUM', '0.9'))    # premium high vs campaign start
DW_IV_ROLL     = float(os.getenv('DW_IV_ROLL',     '0.8'))    # IV rolling over
DW_GIVEBACK    = float(os.getenv('DW_GIVEBACK',    '1.2'))    # premium giving back from peak
DW_OPP_ACCEL   = float(os.getenv('DW_OPP_ACCEL',   '1.0'))    # opposite side accelerating
DW_SPOT_FADE   = float(os.getenv('DW_SPOT_FADE',   '0.7'))    # spot not confirming

# ── Conviction posterior (heuristic proxy) + expected-value entry timing ──────
# assess() blends the five-signal linear score with a HEURISTIC POSTERIOR PROXY (prior odds ×
# likelihood ratios per signal). It is Bayesian-INSPIRED, NOT a calibrated probability — until
# analysis.calibration proves reliability (Brier/log-loss/ECE/decile monotonicity, out-of-sample),
# CAMPAIGN_MIN_POSTERIOR is a heuristic knob, not a true 55%. Entry also requires positive expected
# value:  EV = P(continue)·RemainingConvexity − P(false)·ExpectedLoss.  (spec §46-47)
CAMPAIGN_BAYES_ENABLED = os.getenv('CAMPAIGN_BAYES_ENABLED', 'true').lower() == 'true'
CAMPAIGN_MIN_POSTERIOR = float(os.getenv('CAMPAIGN_MIN_POSTERIOR', '0.55'))
# Likelihood ratios (P(signal|campaign) / P(signal|noise)) for present / absent.
LR_LEADERSHIP  = (float(os.getenv('LR_LEADERSHIP_POS',  '3.0')), float(os.getenv('LR_LEADERSHIP_NEG',  '0.40')))
LR_WAKING      = (float(os.getenv('LR_WAKING_POS',      '2.5')), float(os.getenv('LR_WAKING_NEG',      '0.45')))
LR_ACCUMULATION= (float(os.getenv('LR_ACCUMULATION_POS','3.5')), float(os.getenv('LR_ACCUMULATION_NEG','0.25')))
LR_CONTROL     = (float(os.getenv('LR_CONTROL_POS',     '2.0')), float(os.getenv('LR_CONTROL_NEG',     '0.50')))
LR_CHEAP       = (float(os.getenv('LR_CHEAP_POS',       '1.8')), float(os.getenv('LR_CHEAP_NEG',       '0.55')))
LR_SPOT        = (float(os.getenv('LR_SPOT_POS',        '1.6')), float(os.getenv('LR_SPOT_NEG',        '0.65')))
REQUIRE_POSITIVE_EV = os.getenv('REQUIRE_POSITIVE_EV', 'true').lower() == 'true'
EV_MIN              = float(os.getenv('EV_MIN', '0.0'))
EV_EXPECTED_LOSS    = float(os.getenv('EV_EXPECTED_LOSS', '0.40'))   # ≈ the hard stop size

# ── Stricter early-asymmetry test for entering while still FORMING (fast route) ──
# FORMING can be tradeable (capture convexity early) but only under a HIGHER bar than a
# fully-confirmed ACTIVE wave: higher posterior, lower distribution probability, positive
# spot confirmation, and larger expected value.
FORMING_ENTRY_ENABLED        = os.getenv('FORMING_ENTRY_ENABLED', 'true').lower() == 'true'
FORMING_MIN_POSTERIOR        = float(os.getenv('FORMING_MIN_POSTERIOR', '0.66'))
FORMING_MAX_DIST_PROB        = float(os.getenv('FORMING_MAX_DIST_PROB', '0.45'))
FORMING_MIN_EV               = float(os.getenv('FORMING_MIN_EV', '0.05'))
FORMING_REQUIRE_SPOT_CONFIRM = os.getenv('FORMING_REQUIRE_SPOT_CONFIRM', 'true').lower() == 'true'

# ── WATCH / REDUCE — deterioration-driven partial exit (distinct from profit scale-out) ──
# Trim a live position when the distribution probability crosses DIST_PROB_REDUCE and the
# premium has begun giving back from its peak, even though the wave thesis is not yet dead.
REDUCE_ON_DISTRIBUTION = os.getenv('REDUCE_ON_DISTRIBUTION', 'true').lower() == 'true'
REDUCE_MIN_GIVEBACK    = float(os.getenv('REDUCE_MIN_GIVEBACK', '0.15'))   # peak→now giveback fraction

# ═══════════════════════════════════════════════════════════════════════════════
# CAMPAIGN LIFECYCLE  (Morning-session notes: model the birth→maturity→death through time)
# Self-sustainability (premium rises as volume fades), windowed premium response with
# delayed-convexity tolerance (a brief shakeout that recovers is NOT rejected), efficiency
# trend, and a continuation probability feeding expected-value entry timing.
# ═══════════════════════════════════════════════════════════════════════════════
RESP_WINDOW_S = float(os.getenv('RESP_WINDOW_S', '300'))    # trailing premium series window (s)

# Delayed convexity / shakeout tolerance — a compact campaign that briefly consolidated (real
# positive excursion, now recovering back through its event price) still qualifies.
ALLOW_DELAYED_CONVEXITY = os.getenv('ALLOW_DELAYED_CONVEXITY', 'true').lower() == 'true'
RESP_MFE_MIN        = float(os.getenv('RESP_MFE_MIN', '0.05'))       # premium expanded ≥5% at some point
SHAKEOUT_MIN        = float(os.getenv('SHAKEOUT_MIN', '0.25'))       # dip-then-recover score to allow it
SHAKEOUT_RESID_TOL  = float(os.getenv('SHAKEOUT_RESID_TOL', '0.03')) # must be back within 3% of event price
RESP_DELAYED_FLOOR  = float(os.getenv('RESP_DELAYED_FLOOR', '-0.10'))# hard floor: never accept > this far below event

# Premium-efficiency trend (is each unit of flow buying MORE or LESS premium progress over time).
EFF_TREND_WINDOW = int(os.getenv('EFF_TREND_WINDOW', '8'))          # polls of efficiency history to fit
EFF_TREND_EPS    = float(os.getenv('EFF_TREND_EPS', '0.005'))       # |slope| below this = STABLE
EFF_TREND_SCALE  = float(os.getenv('EFF_TREND_SCALE', '50.0'))      # slope→[-1,1] scale for continuation
EFF_HIST_MAX     = int(os.getenv('EFF_HIST_MAX', '40'))             # cap on per-campaign efficiency history

# Continuation probability (P(campaign continues)) — feeds EV's P(continue).
CONTINUATION_ENABLED = os.getenv('CONTINUATION_ENABLED', 'true').lower() == 'true'
CONT_BIAS       = float(os.getenv('CONT_BIAS', '-0.40'))
CONT_W_SELFSUST = float(os.getenv('CONT_W_SELFSUST', '1.2'))
CONT_W_EFFTREND = float(os.getenv('CONT_W_EFFTREND', '0.8'))
CONT_W_PERSIST  = float(os.getenv('CONT_W_PERSIST', '0.8'))
CONT_W_CONTROL  = float(os.getenv('CONT_W_CONTROL', '0.7'))
CONT_W_SPOT     = float(os.getenv('CONT_W_SPOT', '0.6'))
CONT_W_SHAKEOUT = float(os.getenv('CONT_W_SHAKEOUT', '0.5'))
# How much the continuation probability blends into EV's P(continue) (rest is the Bayesian posterior).
EV_CONTINUATION_WEIGHT = float(os.getenv('EV_CONTINUATION_WEIGHT', '0.40'))
# Weak self-sustainability on a held position corroborates a WATCH/REDUCE trim.
SELF_SUST_WEAK = float(os.getenv('SELF_SUST_WEAK', '0.12'))

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — CAMPAIGN MEMORY / STABILIZATION  (spec Priority 1: fix premature exits)
# A falling Z-score, cooling attention share or a lost rank is NOT campaign death — it is
# the natural statistical cool-down after a successful accumulation burst. Separate three
# conditions the old engine conflated: ROTATION (a stronger external campaign AND ours is
# weakening), TRUE EXHAUSTION (multi-signal deterioration), and STABILIZATION (flow cools
# but the campaign is structurally intact). A cooling-but-intact wave moves ACTIVE→STABILIZING
# (campaign memory keeps it alive) instead of DECAYING→exhaustion, and a held position is not
# exited on cooling alone. EVERYTHING here is gated by STABILIZE_ENABLED, default OFF, so the
# validated live-paper exit behaviour is unchanged until a backtest proves the new logic.
# ═══════════════════════════════════════════════════════════════════════════════
STABILIZE_ENABLED     = os.getenv('STABILIZE_ENABLED', 'false').lower() == 'true'
# A campaign is "structurally intact" (→ STABILIZING, not exhaustion) while it retains control,
# faces no strong opposite-side campaign, is not distributing, and premium has not failed.
STABILIZE_MIN_CONTROL = float(os.getenv('STABILIZE_MIN_CONTROL', '0.55'))  # side still owns the tape
STABILIZE_OPP_CONTROL = float(os.getenv('STABILIZE_OPP_CONTROL', '0.60'))  # opp this strong (+accel) = real threat
STABILIZE_MIN_RELPREM = float(os.getenv('STABILIZE_MIN_RELPREM', '0.90'))  # premium within 10% of campaign start
STABILIZE_MIN_CONT    = float(os.getenv('STABILIZE_MIN_CONT', '0.50'))     # continuation prob still supportive
# How long a wave may remain STABILIZING (cooling, intact) before a genuine fade-out begins to
# count as deterioration. Time-based so it behaves identically at the live 5s cadence and the
# 1-min backtest. 0 disables the timeout (a stabilizing campaign never times out on its own).
WAVE_STABILIZE_MAX_S  = float(os.getenv('WAVE_STABILIZE_MAX_S', '900'))    # 15 min
# When STABILIZE_ENABLED, a ROTATION exit additionally requires the incumbent's own campaign to
# be materially deteriorating (not merely out-ranked) — a healthy incumbent is never abandoned.
ROTATION_REQUIRE_INCUMBENT_WEAK = os.getenv('ROTATION_REQUIRE_INCUMBENT_WEAK', 'true').lower() == 'true'

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — EARLY DETECTION / LATENCY  (spec Priority 2: reduce detection latency)
# The gap between "nothing" and "ENTER" is too large. Add pre-entry observation stages —
# WATCH (first abnormal activity) and BUILDING (repeated participation + emerging control) —
# BEFORE the FORMING birth threshold, so the engine can measure how early the evidence began
# and score the earliest favorable phase with an EarlyAccumulationScore that is distinct from
# mature campaign confidence. This layer is OBSERVATION-ONLY: it records timestamps, states and
# scores; it does NOT change when the engine enters (that is still FORMING/ACTIVE + the §16/EV
# gates). Gated by EARLY_DETECT_ENABLED (default OFF); EarlyAccumulationScore always computes and
# logs (harmless). Optimisation target: reduce detection latency WITHOUT hurting precision.
# ═══════════════════════════════════════════════════════════════════════════════
EARLY_DETECT_ENABLED = os.getenv('EARLY_DETECT_ENABLED', 'false').lower() == 'true'
EARLY_WATCH_Z     = float(os.getenv('EARLY_WATCH_Z', '1.5'))     # first abnormal activity → WATCH
EARLY_WATCH_CONTROL = float(os.getenv('EARLY_WATCH_CONTROL', '0.50'))  # minimal one-sidedness for WATCH
EARLY_BUILD_EVALS = int(os.getenv('EARLY_BUILD_EVALS', '2'))     # consecutive participation polls → BUILDING
EARLY_CONTROL_MIN = float(os.getenv('EARLY_CONTROL_MIN', '0.55'))# side control marking control-emergence

# EarlyAccumulationScore (0-100) — a separate early-phase score, NOT mature CampaignConfidence.
# Optimised for the earliest favorable phase: fresh-premium velocity + participation proof + value
# proximity (low extension) + emerging control + firming/recovering response + absence of
# distribution + remaining convexity. Always computed and logged; never gates on its own.
EAS_W_FRESHVEL      = float(os.getenv('EAS_W_FRESHVEL', '0.22'))   # fresh flow rising
EAS_W_PARTICIPATION = float(os.getenv('EAS_W_PARTICIPATION', '0.18'))  # meaningful abnormal participation (z)
EAS_W_VALUE         = float(os.getenv('EAS_W_VALUE', '0.20'))      # still near local value (low extension)
EAS_W_CONTROL       = float(os.getenv('EAS_W_CONTROL', '0.15'))    # emerging one-sided control
EAS_W_RESPONSE      = float(os.getenv('EAS_W_RESPONSE', '0.15'))   # premium firming/recovering (resp + shakeout)
EAS_W_NODIST        = float(os.getenv('EAS_W_NODIST', '0.10'))     # low distribution probability

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — MULTI-EXPIRATION SCANNING  (spec Priority 3 / §8-9, §24-25, §28)
# The base engine centres on the NEAREST listed expiry. Institutions express a thesis across
# expirations (0DTE urgency, current-week Friday forward positioning, or both). This layer scans
# several relevant expiries, derives per-expiry share/control and the near→forward migration of
# capital, and classifies the structure. It is SHADOW: gated by MULTI_EXPIRY_ENABLED (default OFF)
# and THROTTLED (the extra option-snapshot calls run at most every MULTI_EXPIRY_POLL_S). It only
# LOGS — the trading path still uses the nearest expiry until a later, separately-gated step wires
# multi-expiry structure into entries. The shadow scan uses cumulative (not fresh) volume as a
# coarse mass proxy, which is sufficient for share / control / migration direction.
# ═══════════════════════════════════════════════════════════════════════════════
MULTI_EXPIRY_ENABLED    = os.getenv('MULTI_EXPIRY_ENABLED', 'false').lower() == 'true'
MULTI_EXPIRY_MAX        = int(os.getenv('MULTI_EXPIRY_MAX', '4'))       # 0DTE + nearest-nonzero + Fri + next-Fri
MULTI_EXPIRY_POLL_S     = float(os.getenv('MULTI_EXPIRY_POLL_S', '60')) # throttle the extra API load
EXPIRY_MEANINGFUL_SHARE = float(os.getenv('EXPIRY_MEANINGFUL_SHARE', '0.20'))  # an expiry "matters" above this
EXPIRY_MIGRATION_SLOPE  = float(os.getenv('EXPIRY_MIGRATION_SLOPE', '0.08'))   # Δ forward-share = migration

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 4 — CAMPAIGN ARCHETYPES  (spec Priority 4 / §10)
# Not every valid campaign is a compact 0DTE shock. Classify the developing shape (shock,
# persistent, self-sustaining, shakeout-recovery, stair-step, impulse-repricing, forward/cross-
# expiry, distribution) so archetype-specific expectations can be applied. ARCHETYPE_ENABLED just
# computes + logs the label (harmless, like EarlyAccumulationScore). ARCHETYPE_GATE_ENABLED (default
# OFF) applies the archetype-specific ENTRY expectation in engine._open_wave: only a recognized
# accumulation archetype may enter (DISTRIBUTION / UNCLASSIFIED are rejected).
# ═══════════════════════════════════════════════════════════════════════════════
ARCHETYPE_ENABLED      = os.getenv('ARCHETYPE_ENABLED', 'true').lower() == 'true'
ARCHETYPE_GATE_ENABLED = os.getenv('ARCHETYPE_GATE_ENABLED', 'false').lower() == 'true'
ARCH_SELF_SUST_MIN = float(os.getenv('ARCH_SELF_SUST_MIN', '0.25'))  # self-sustaining premium threshold
ARCH_VOLUME_FADE   = float(os.getenv('ARCH_VOLUME_FADE', '0.50'))    # decay_rate above = volume fading
ARCH_SHOCK_DOMINANT = float(os.getenv('ARCH_SHOCK_DOMINANT', '0.60'))# single-bar dominance for a shock
ARCH_SHOCK_Z        = float(os.getenv('ARCH_SHOCK_Z', '3.5'))        # abnormality for a shock
ARCH_IMPULSE_RESP   = float(os.getenv('ARCH_IMPULSE_RESP', '0.10'))  # premium repricing strength

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 5 — DISTRIBUTED STRIKE-SURFACE AGGREGATION  (spec Priority 5 / §23-25)
# The base engine can reject a real ticker-level campaign spread across a strike ladder because no
# single strike passes a dominant-strike test (the AMZN 237.5–257.5 case). This layer answers the
# ticker-level "is capital concentrating across the surface?" question first, then names a
# representative contract. SURFACE_ENABLED just computes + logs the surface profile (harmless).
# SURFACE_GATE_ENABLED (default OFF) lets a tradeable broad/ladder surface clear the single-strike
# notional floor on its breadth-adjusted ladder mass in engine._open_wave (the AMZN fix).
# ═══════════════════════════════════════════════════════════════════════════════
SURFACE_ENABLED       = os.getenv('SURFACE_ENABLED', 'true').lower() == 'true'
SURFACE_GATE_ENABLED  = os.getenv('SURFACE_GATE_ENABLED', 'false').lower() == 'true'
SURFACE_STRIKE_MIN_SHARE = float(os.getenv('SURFACE_STRIKE_MIN_SHARE', '0.10'))  # a strike "participates" above this
SURFACE_SINGLE        = float(os.getenv('SURFACE_SINGLE', '0.60'))   # one strike owns the surface
SURFACE_TWO_TOP2      = float(os.getenv('SURFACE_TWO_TOP2', '0.70')) # two-strike coordination (top-2 share)
SURFACE_TWO_SECOND    = float(os.getenv('SURFACE_TWO_SECOND', '0.25'))# …with a real second participant
SURFACE_LADDER_BREADTH = int(os.getenv('SURFACE_LADDER_BREADTH', '3'))# adjacent ladder needs ≥ this many strikes
SURFACE_BROAD_BREADTH  = int(os.getenv('SURFACE_BROAD_BREADTH', '4')) # broad-surface campaign breadth
SURFACE_BREADTH_BONUS  = float(os.getenv('SURFACE_BREADTH_BONUS', '0.15'))  # reward per extra participating strike

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 6 — CAMPAIGN REPLAY / CANDIDATE ARCHIVE  (spec Priority 6 / §41-45)
# Archive a structured, poll-by-poll record for every candidate (incl. rejected ones) so campaigns
# can be reconstructed and missed winners turned into reproducible diagnostics. Gated by
# RESEARCH_ARCHIVE_ENABLED (default OFF): when off, no record is built and nothing is written —
# zero effect on the trading loop and no disk I/O. Throttled to limit disk volume.
# ═══════════════════════════════════════════════════════════════════════════════
RESEARCH_ARCHIVE_ENABLED = os.getenv('RESEARCH_ARCHIVE_ENABLED', 'false').lower() == 'true'
RESEARCH_ARCHIVE_FILE    = os.getenv('RESEARCH_ARCHIVE_FILE', 'jakenew_candidates.jsonl')
RESEARCH_ARCHIVE_EVERY_S = float(os.getenv('RESEARCH_ARCHIVE_EVERY_S', '30'))  # snapshot cadence
RESEARCH_ARCHIVE_TOPK    = int(os.getenv('RESEARCH_ARCHIVE_TOPK', '5'))        # top-N ranked per snapshot

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 7 — PROFIT-TAKING REVALIDATION / RUNNER  (spec Priority 7 / §37-40)
# The +60/+150 ladder mechanically forfeits the +300/+500/+1000% campaigns the engine exists to
# catch. With RUNNER_ENABLED, after banking half at +TP1 the rest becomes a RUNNER held while the
# campaign is intact — exited only on coherent distribution, a wider (expiry-aware) trail, control
# transfer, or EOD — instead of a hard +150% close. The −40% hard stop remains a pure backstop.
# Default OFF → the validated +60/+150 ladder is unchanged. Exits are also tagged into a taxonomy
# (objective / thesis-death / distribution / control-transfer / risk-stop / liquidity / EOD).
# ═══════════════════════════════════════════════════════════════════════════════
RUNNER_ENABLED            = os.getenv('RUNNER_ENABLED', 'false').lower() == 'true'
RUNNER_TRAIL_ARM_PCT      = float(os.getenv('RUNNER_TRAIL_ARM_PCT', '1.00'))     # runner trail arms past +100%
RUNNER_TRAIL_GIVEBACK_PCT = float(os.getenv('RUNNER_TRAIL_GIVEBACK_PCT', '0.50'))# give back 50% of peak (wide → let it run)
RUNNER_MAX_PCT            = float(os.getenv('RUNNER_MAX_PCT', '0'))              # optional hard ceiling (0 = none)

# ═══════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEETS TRADE LOG  (ported from Jakevolume/output/sheets_logger.py)
# Jakenew had NO Sheets integration — which is why the shared spreadsheet never updated with
# Jakenew's trades (only Jakevolume fed it). This logs every Jakenew entry/scale/exit to a
# dedicated worksheet in the SAME spreadsheet, reusing the SAME service-account credentials, so the
# two engines can share one workbook without colliding (Jakenew writes only its own tab). Writes are
# async + throttled + retried in a daemon thread, so the trading loop is never blocked. Gated by
# SHEETS_ENABLED; if the credentials/spreadsheet are missing, the engine logs a warning and runs on
# without Sheets (never crashes the loop).
# ═══════════════════════════════════════════════════════════════════════════════
SHEETS_ENABLED = os.getenv('SHEETS_ENABLED', 'false').lower() == 'true'
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'service_account.json')
GOOGLE_SPREADSHEET_ID       = os.getenv('GOOGLE_SPREADSHEET_ID', '')
SHEETS_MIN_WRITE_INTERVAL   = float(os.getenv('SHEETS_MIN_WRITE_INTERVAL', '1.1'))  # ≥ this many s between writes
SHEET_NAMES = {
    'trades': os.getenv('SHEET_NAME_TRADES', 'Jakenew_Trades'),
}

# ═══════════════════════════════════════════════════════════════════════════════
# FOLLOW-UP P1 — CAMPAIGN CONFIDENCE / HOLD SCORE  (follow-up spec §4-7, §15-16, §20)
# Separate HOLDING from ENTERING. A stateful CampaignConfidence persists across polls: rotation is a
# PENALTY (not an immediate exit — §4/§6), verified deterioration subtracts, reacceleration/continued
# progress adds; a position exits only when confidence erodes below HOLD_EXIT_THRESHOLD. This
# supersedes the STABILIZE exit path when enabled. Gated by CAMPAIGN_CONFIDENCE_ENABLED (default OFF)
# so the current live behaviour is unchanged until a backtest validates it.
# ═══════════════════════════════════════════════════════════════════════════════
CAMPAIGN_CONFIDENCE_ENABLED = os.getenv('CAMPAIGN_CONFIDENCE_ENABLED', 'false').lower() == 'true'
CONF_INIT             = float(os.getenv('CONF_INIT', '0.75'))     # base confidence at entry
CONF_MAX_INIT         = float(os.getenv('CONF_MAX_INIT', '0.95'))  # strongest campaigns start here (hysteresis)
CONF_MAX_DROP_PER_POLL = float(os.getenv('CONF_MAX_DROP_PER_POLL', '0.12'))  # max confidence loss/poll (persistence)
HOLD_EXIT_THRESHOLD   = float(os.getenv('HOLD_EXIT_THRESHOLD', '0.40'))  # exit when confidence drops below
CONF_ROTATION_PENALTY = float(os.getenv('CONF_ROTATION_PENALTY', '0.10'))  # rotation = penalty, not command
CONF_PEN_CONTROL      = float(os.getenv('CONF_PEN_CONTROL', '0.15'))   # side lost control
CONF_PEN_OPP          = float(os.getenv('CONF_PEN_OPP', '0.15'))       # opposite side strengthening
CONF_PEN_DIST         = float(os.getenv('CONF_PEN_DIST', '0.20'))      # distribution evidence
CONF_PEN_PREMIUM      = float(os.getenv('CONF_PEN_PREMIUM', '0.12'))   # premium not progressing
CONF_PEN_HL           = float(os.getenv('CONF_PEN_HL', '0.08'))        # higher-low structure failing
CONF_RECOVER_BONUS    = float(os.getenv('CONF_RECOVER_BONUS', '0.12')) # reaccelerating / active again
CONF_HOLD_BONUS       = float(os.getenv('CONF_HOLD_BONUS', '0.03'))    # healthy drift-up while holding
# HoldScore snapshot weights (positive block sums ≈1; distribution/opp subtract).
HS_W_CONF     = float(os.getenv('HS_W_CONF', '0.30'))
HS_W_SELFSUST = float(os.getenv('HS_W_SELFSUST', '0.15'))
HS_W_CONT     = float(os.getenv('HS_W_CONT', '0.15'))
HS_W_SMOOTH   = float(os.getenv('HS_W_SMOOTH', '0.15'))
HS_W_HL       = float(os.getenv('HS_W_HL', '0.10'))
HS_W_CONTROL  = float(os.getenv('HS_W_CONTROL', '0.15'))
HS_W_DIST     = float(os.getenv('HS_W_DIST', '0.30'))
HS_W_OPP      = float(os.getenv('HS_W_OPP', '0.15'))

# ═══════════════════════════════════════════════════════════════════════════════
# FOLLOW-UP §10 — ARCHETYPE ENTRY ROUTES (hard vetoes + total expected asymmetry)
# Replace the conjunctive gate stack with hard vetoes + an archetype-weighted asymmetry score, so
# strong evidence in one dimension can compensate a weak reading in another (the AAPL/persistent and
# AMZN/ladder misses). When ENTRY_ROUTES_ENABLED, a candidate that clears the hard vetoes AND scores
# >= ENTRY_ROUTE_MIN_SCORE on its archetype route enters — the soft conjunctive gates are bypassed.
# Default OFF → the validated conjunctive path is unchanged.
# ═══════════════════════════════════════════════════════════════════════════════
ENTRY_ROUTES_ENABLED  = os.getenv('ENTRY_ROUTES_ENABLED', 'false').lower() == 'true'
ENTRY_ROUTE_MIN_SCORE = float(os.getenv('ENTRY_ROUTE_MIN_SCORE', '0.55'))  # total-asymmetry pass bar
# Rank relaxation (MSFT 495C false-negative): under routes, absolute campaign quality can qualify a
# non-leader — the wave engine proposes candidates up to this attention rank and lets the route's
# asymmetry score + hard vetoes decide, instead of requiring strict Mag-7 rank #1 + lead margin.
ROUTE_MAX_RANK        = int(os.getenv('ROUTE_MAX_RANK', '3'))
ENTRY_HARD_DIST       = float(os.getenv('ENTRY_HARD_DIST', '0.80'))        # dist-prob above = hard distribution veto
ENTRY_HARD_EXTENSION  = float(os.getenv('ENTRY_HARD_EXTENSION', '2.5'))    # dist-from-low above = objectively-late veto

# ═══════════════════════════════════════════════════════════════════════════════
# FOLLOW-UP §11-12 — LOCAL-VALUE CHEAPNESS + DETECTION-LATENCY / AGGREGATION DIAGNOSIS
# CHASED means two different things — a campaign discovered early but executed late (detection
# latency, fixable) vs one recognised only after it extended (a valid reject). Distinguish them by
# how far premium drifted since the campaign was first captured. Notional shortfalls likewise
# distinguish a thin single strike from a cluster the aggregation would have covered.
# ═══════════════════════════════════════════════════════════════════════════════
CHASED_LATENCY_DRIFT      = float(os.getenv('CHASED_LATENCY_DRIFT', '1.30'))   # premium up ≥30% since capture = latency
CHEAP_LOCAL_VALUE_ENABLED = os.getenv('CHEAP_LOCAL_VALUE_ENABLED', 'false').lower() == 'true'  # (reserved) local value vs session low
# §13 — waive the blanket opening 1.4× penalty for a clean opening campaign (persists beyond the
# auction / positive short response / adjacent-strike confirmation). Default OFF.
OPENING_QUALITY_ENABLED   = os.getenv('OPENING_QUALITY_ENABLED', 'false').lower() == 'true'

# ═══════════════════════════════════════════════════════════════════════════════
# NEW-SPEC — DAILY ONE-ENTER-PER-SIDE LOCK + PREMIUM ACCEPTANCE + REINFORCEMENT
# "The scanner gets unlimited observations; the trader gets extremely few decisions." A fired entry
# CONSUMES that (ticker, side) slot for the whole session — no re-entry that side/ticker today even
# after an exit/invalidation (kills the ENTER→EXIT→ENTER churn). Everything after entry is campaign
# management (STRENGTHENING/HOLD/INVALIDATED), not a new alert. Flag-gated, default OFF.
# ═══════════════════════════════════════════════════════════════════════════════
DAILY_ENTRY_LOCK_ENABLED = os.getenv('DAILY_ENTRY_LOCK_ENABLED', 'false').lower() == 'true'
# Premium Acceptance (GOOGL §): heavy volume + premium HOLDING = absorption (tradeable, even flat);
# heavy volume + premium lower-lows = rejection (WATCH only, not ENTER). Never requires appreciation.
ACCEPTANCE_ENABLED     = os.getenv('ACCEPTANCE_ENABLED', 'true').lower() == 'true'  # compute+log
ACCEPTANCE_HEAVY_MULT  = float(os.getenv('ACCEPTANCE_HEAVY_MULT', '2.0'))  # recent vol ≥ this × mean = heavy
ACCEPTANCE_REJECT_DROP = float(os.getenv('ACCEPTANCE_REJECT_DROP', '0.05'))# recent low ≥5% below prior lows = rejection
# Reinforcement: same-side resurgence on a held position logs STRENGTHENING (not a new ENTER).
REINFORCE_LOG_ENABLED     = os.getenv('REINFORCE_LOG_ENABLED', 'true').lower() == 'true'
REINFORCE_MIN_INTERVAL_S  = float(os.getenv('REINFORCE_MIN_INTERVAL_S', '300'))  # throttle strengthening notices
REINFORCE_MIN_CONF        = float(os.getenv('REINFORCE_MIN_CONF', '0.55'))  # don't post STRENGTHENING on a fading campaign
# T+1 OI campaign confirmation (research): needs Schwab OI (currently off) to fetch next-day OI.
OI_CONFIRM_ENABLED        = os.getenv('OI_CONFIRM_ENABLED', 'false').lower() == 'true'
OI_CONFIRM_FILE           = os.getenv('OI_CONFIRM_FILE', 'jakenew_campaigns.jsonl')

# ═══════════════════════════════════════════════════════════════════════════════
# NEW-SPEC P1 — CROSS-SESSION CAMPAIGN MEMORY
# A campaign whose option expiration is still alive is serialized in the state file (saved every
# poll → survives a mid-day RESTART too, not just overnight) and restored at startup, instead of the
# engine waking up thinking every ticker is fresh (the AMZN Thursday→Friday reset). An inherited
# campaign is under management, does NOT consume the new day's slot, and raises the bar for an
# opposite-side entry that session (hysteresis). Flag-gated, default OFF.
# ═══════════════════════════════════════════════════════════════════════════════
CROSS_SESSION_MEMORY_ENABLED = os.getenv('CROSS_SESSION_MEMORY_ENABLED', 'false').lower() == 'true'
# Extra route-asymmetry an opposite-side entry must clear when a surviving campaign holds the other
# side (Friday's first AMZN put must overcome Thursday's funded call campaign).
CROSS_SESSION_OPP_BUMP = float(os.getenv('CROSS_SESSION_OPP_BUMP', '0.15'))

# ═══════════════════════════════════════════════════════════════════════════════
# NEW-SPEC P3 — STATEFUL OPPOSITE-SIDE REVERSAL (ReversalCluster + EXIT != REVERSE)
# Opposite-side flow builds evidence through a stateful cluster (OPPOSITE_FLOW_DETECTED → WATCH →
# CONFIRMED → ACTIVATED) rather than flipping a position on one print. At ACTIVATED the incumbent
# exits — EXIT_REVERSE if the opposite side independently qualifies as a fresh entry, else EXIT_FLAT.
# When enabled, the reversal cluster OWNS opposite-side exits (CampaignConfidence then only exits on
# own-side deterioration). Flag-gated, default OFF.
# ═══════════════════════════════════════════════════════════════════════════════
REVERSAL_ENABLED     = os.getenv('REVERSAL_ENABLED', 'false').lower() == 'true'
REV_OPP_CONTROL_MIN  = float(os.getenv('REV_OPP_CONTROL_MIN', '0.55'))  # opp must own this to count as an event
REV_OPP_Z            = float(os.getenv('REV_OPP_Z', '2.5'))            # opp abnormality to count as an event
REV_WATCH_EVENTS     = int(os.getenv('REV_WATCH_EVENTS', '2'))          # opp events: DETECTED → WATCH
REV_CONFIRM_EVENTS   = int(os.getenv('REV_CONFIRM_EVENTS', '3'))        # persistence alt for confirmation
REV_CONFIRM_EVALS    = int(os.getenv('REV_CONFIRM_EVALS', '2'))         # sustained confirm polls → CONFIRMED
REV_ACTIVATE_CONTROL = float(os.getenv('REV_ACTIVATE_CONTROL', '0.66')) # opp control to activate (with confirmed)

# ── Runtime state ────────────────────────────────────────────────────────────
STATE_FILE = os.getenv('STATE_FILE', 'jakenew_state.json')
LOG_FILE   = os.getenv('LOG_FILE', 'jakenew.log')
