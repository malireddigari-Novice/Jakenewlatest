"""
Campaign HOLD logic (follow-up spec §4-7, §15-16, §20) — pure, I/O-free.

The engine has been *entering* well but *managing* like an attention scanner: it exits a healthy
campaign the moment current attention cools or another ticker out-ranks it (the TSLA +3% ROTATION,
GOOGL 4-min STATISTICAL_EXHAUSTION, AMZN 4-min ROTATION cases). This module separates HOLDING from
ENTERING:

  • CampaignConfidence — a stateful belief that persists across polls. Rotation is a *penalty*, not a
    command (§4/§6); verified deterioration (lost control, distribution, premium/higher-low failure,
    opposite-side campaign) also subtracts; reacceleration / continued premium progress adds. A
    position exits only when confidence erodes below a threshold — never on cooling alone.
  • HoldScore — an instantaneous 0-1 read of campaign health (§5), for logging.
  • Premium-structure metrics — PremiumPersistence / PremiumSmoothness / HigherLowQuality (§15-16)
    that recognise an orderly persistent campaign (AAPL) rather than only a violent shock.

`confidence_step` returns the new confidence + the dominant deterioration cause, which
`exit_reason_from` maps to the §20 exit labels.
"""
import config


def _prices(marks):
    """Normalise a marks series to positive prices. Accepts bare floats OR (ts, price) tuples
    (contract_marks returns [(ts, mark), ...])."""
    out = []
    for x in (marks or []):
        if x is None:
            continue
        v = x[1] if isinstance(x, (tuple, list)) else x
        if v is not None and v > 0:
            out.append(float(v))
    return out


def premium_persistence(series) -> float:
    """0-1: did meaningful activity keep arriving over time (breadth) and not collapse after the
    first burst (sustain)? High for a persistent AAPL-style build, low for a lone TSLA spike."""
    vals = [max(0.0, float(v)) for v in series if v is not None]
    n = len(vals)
    total = sum(vals)
    if n == 0 or total <= 0:
        return 0.0
    mean = total / n
    breadth = sum(1 for v in vals if v >= 0.2 * mean) / n
    half = n // 2 or 1
    early = sum(vals[:half]) or 1e-9
    recent = sum(vals[-half:])
    sustain = min(1.0, recent / early)
    return round(min(1.0, 0.6 * breadth + 0.4 * sustain), 3)


def premium_smoothness(marks) -> float:
    """0-1: orderly progression (mostly non-decreasing, path-efficient) vs whipsaw."""
    m = _prices(marks)
    if len(m) < 3:
        return 0.5
    steps = [m[i + 1] - m[i] for i in range(len(m) - 1)]
    directional = sum(1 for s in steps if s >= 0) / len(steps)
    net = abs(m[-1] - m[0])
    tv = sum(abs(s) for s in steps) or 1e-9
    return round(min(1.0, 0.5 * directional + 0.5 * (net / tv)), 3)


def higher_low_quality(marks) -> float:
    """0-1: are successive pullback lows holding/rising (a resilient trend)?"""
    m = _prices(marks)
    if len(m) < 4:
        return 0.5
    lows = [m[i] for i in range(1, len(m) - 1) if m[i] <= m[i - 1] and m[i] <= m[i + 1]]
    if len(lows) < 2:
        return 1.0 if min(m) >= m[0] * 0.95 else 0.5
    rising = sum(1 for i in range(1, len(lows)) if lows[i] >= lows[i - 1] * 0.98)
    return round(rising / (len(lows) - 1), 3)


def hold_score(f: dict) -> float:
    """Instantaneous 0-1 campaign-health read (§5) — logged, complements the stateful confidence."""
    pos = (config.HS_W_CONF * f.get('confidence', 0.5)
           + config.HS_W_SELFSUST * f.get('self_sust', 0.0)
           + config.HS_W_CONT * f.get('cont', 0.0)
           + config.HS_W_SMOOTH * f.get('smoothness', 0.5)
           + config.HS_W_HL * f.get('higher_low_q', 0.5)
           + config.HS_W_CONTROL * f.get('control', 0.5))
    neg = config.HS_W_DIST * f.get('dist_prob', 0.0) + config.HS_W_OPP * f.get('opp', 0.0)
    return round(max(0.0, min(1.0, pos - neg)), 3)


def confidence_step(prev: float, f: dict, rotation_active: bool):
    """Advance CampaignConfidence one poll. Returns (new_confidence, dominant_cause).
    Penalties accumulate for rotation + each verified-deterioration signal; a recovery/hold bonus
    applies when the campaign is reaccelerating or still progressing without distribution."""
    conf = prev
    causes = []
    if rotation_active:
        conf -= config.CONF_ROTATION_PENALTY; causes.append(('ROTATION', config.CONF_ROTATION_PENALTY))
    if not f.get('control_ok', True):
        conf -= config.CONF_PEN_CONTROL; causes.append(('CONTROL', config.CONF_PEN_CONTROL))
    if f.get('opp_strong'):
        conf -= config.CONF_PEN_OPP; causes.append(('OPP_SIDE', config.CONF_PEN_OPP))
    if f.get('dist_high'):
        conf -= config.CONF_PEN_DIST; causes.append(('DISTRIBUTION', config.CONF_PEN_DIST))
    if not f.get('progressing', True):
        conf -= config.CONF_PEN_PREMIUM; causes.append(('PREMIUM', config.CONF_PEN_PREMIUM))
    if not f.get('higher_low', True):
        conf -= config.CONF_PEN_HL; causes.append(('HIGHER_LOW', config.CONF_PEN_HL))
    if f.get('reaccelerating') or f.get('active'):
        conf += config.CONF_RECOVER_BONUS
    elif f.get('progressing', True) and not f.get('dist_high'):
        conf += config.CONF_HOLD_BONUS          # proven campaign drifts back up while healthy
    # Per-poll DROP CAP — a single noisy poll (a transient control flip, one rotation snapshot)
    # cannot collapse a campaign; deterioration must PERSIST across polls to exit. This is what stops
    # the NVDA/AAPL 1-2 minute exits: a funded campaign now takes several sustained bad polls to erode.
    conf = max(conf, prev - config.CONF_MAX_DROP_PER_POLL)
    conf = max(0.0, min(1.0, conf))
    dominant = max(causes, key=lambda x: x[1])[0] if causes else None
    return round(conf, 3), dominant


def initial_confidence(share, posterior, notional) -> float:
    """Incumbent-strength hysteresis: a heavily-funded, high-conviction campaign STARTS higher, so it
    takes proportionally more opposing evidence to erode below the exit threshold (a strong campaign
    should not be as fragile as a marginal one)."""
    bonus = (min(0.10, max(0.0, (share or 0.0) - 0.30) * 0.5)              # high pool share
             + min(0.05, max(0.0, (posterior or 0.0) - 0.70) * 0.5)       # high posterior
             + min(0.05, (notional or 0.0) / 1e6 * 0.05))                  # large fresh premium
    return round(min(config.CONF_MAX_INIT, config.CONF_INIT + bonus), 3)


_EXIT_BY_CAUSE = {
    'DISTRIBUTION': 'SUSTAINED_DISTRIBUTION',
    'CONTROL': 'PERSISTENT_CONTROL_TRANSFER',
    'OPP_SIDE': 'OPPOSITE_SIDE_CAMPAIGN_SUSTAINED',
    'ROTATION': 'ROTATION_WITH_CURRENT_CAMPAIGN_FAILURE',
    'PREMIUM': 'PREMIUM_STRUCTURE_FAILURE',
    'HIGHER_LOW': 'RESILIENCE_FAILURE',
}


def exit_reason_from(dominant, f: dict) -> str:
    """Map the dominant deterioration cause to a §20 exit label (multi-variable if diffuse)."""
    return _EXIT_BY_CAUSE.get(dominant, 'TRUE_MULTI_VARIABLE_EXHAUSTION')
