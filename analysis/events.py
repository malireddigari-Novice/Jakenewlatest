"""
Layer 3 — event quality, the moving convexity front, and contract selection.

Attention (Layer 1) says WHICH ticker; control (Layer 2) says WHICH SIDE. This layer answers
"what FORM is the attention taking, at which strike, and is the entry window still open?"

Three jobs:
  1. Event quality/classification — is this a dominant SINGLE_STRIKE, a coordinated CHAIN, an
     EMERGENT/RAMP event, or just DISTRIBUTED background? (top-strike share, top-3 share,
     active-strike count, compactness around ATM, distributed-background detection.)
  2. The moving convexity front — a strike is most informative while it is BECOMING ATM, not
     after. We track distance-to-strike d=(K−S)/S, its velocity (spot approaching the strike),
     volume acceleration, and ordered strike MIGRATION (K1→K2→K3 in the direction of travel).
  3. Contract selection + entry freshness — pick the best eligible contract among ATM ± one
     adjacent strike by real participation/liquidity/room-from-low (never blindly ATM, no
     far-OTM lottery), and grade how much the premium has already run (EARLY→MISSED).
"""
import config


# ── event quality / classification ───────────────────────────────────────────

def event_metrics(side_strikes: list) -> dict:
    """
    side_strikes: list of per-strike dicts {strike, fresh_prem, fresh_vol} for ONE side.
    Returns concentration metrics used by both the gate and the score.
    """
    active = [s for s in side_strikes if (s.get('fresh_prem') or 0) > 0]
    total = sum(s['fresh_prem'] for s in active)
    if total <= 0:
        return {'top_strike_share': 0.0, 'top3_share': 0.0, 'active_strikes': 0,
                'compactness': 0.0, 'distributed_background': True, 'top_strike': None}
    ranked = sorted(active, key=lambda s: s['fresh_prem'], reverse=True)
    top_share = ranked[0]['fresh_prem'] / total
    top3_share = sum(s['fresh_prem'] for s in ranked[:3]) / total
    # "Meaningfully active" = a strike carrying >= 5% of the side's fresh premium.
    meaningful = [s for s in ranked if s['fresh_prem'] / total >= 0.05]
    n_active = len(meaningful)
    # Compactness: are the meaningful strikes contiguous on the ladder around the leader?
    compactness = _compactness([s['strike'] for s in meaningful])
    # Distributed background = no strike dominates AND breadth is high (flow smeared across
    # many strikes). Grid-contiguity is NOT compactness here: five evenly-spaced strikes at 20%
    # each are background, not a coordinated chain — a chain concentrates in 2-3 adjacent strikes.
    distributed = (top_share < config.GATE_MIN_TOP_STRIKE_SHARE and n_active >= 4)
    return {'top_strike_share': round(top_share, 3), 'top3_share': round(top3_share, 3),
            'active_strikes': n_active, 'compactness': round(compactness, 3),
            'distributed_background': distributed, 'top_strike': ranked[0]['strike']}


def _compactness(strikes: list) -> float:
    """1.0 when the active strikes are perfectly contiguous on the grid, →0 when scattered."""
    if len(strikes) <= 1:
        return 1.0
    xs = sorted(strikes)
    diffs = [round(b - a, 4) for a, b in zip(xs, xs[1:]) if b > a]
    if not diffs:
        return 1.0
    step = min(diffs)                       # inferred grid spacing
    span_steps = (xs[-1] - xs[0]) / step + 1
    return max(0.0, min(1.0, len(xs) / span_steps))


def classify_event(metrics: dict, activation: dict = None) -> str:
    """SINGLE_STRIKE · CHAIN · RAMP · EMERGENT · DISTRIBUTED."""
    if metrics['distributed_background']:
        return 'DISTRIBUTED'
    if activation and activation.get('ramp'):
        return 'RAMP'
    if metrics['top_strike_share'] >= config.EVENT_SINGLE_TOP_SHARE:
        return 'SINGLE_STRIKE'
    if (metrics['active_strikes'] >= config.EVENT_CHAIN_MIN_STRIKES
            and metrics['top3_share'] >= config.EVENT_CHAIN_TOP3_SHARE
            and metrics['compactness'] >= 0.5):
        return 'CHAIN'
    return 'EMERGENT'


def event_quality_score(metrics: dict) -> float:
    """0-1 quality: rewards concentration + compactness, punishes distributed background."""
    if metrics['distributed_background'] or metrics['active_strikes'] == 0:
        return 0.0
    return round(0.6 * metrics['top_strike_share'] + 0.2 * metrics['top3_share']
                 + 0.2 * metrics['compactness'], 3)


# ── moving convexity front ────────────────────────────────────────────────────

def strike_distance(side: str, strike: float, spot: float) -> float:
    """
    Signed distance of a strike from spot, normalised. Positive = still OTM (room to become
    ATM). For a CALL that's (K−S)/S; for a PUT it's (S−K)/S. → 0 as the strike becomes ATM.
    """
    if not spot:
        return 0.0
    return ((strike - spot) if side == 'CALL' else (spot - strike)) / spot


def strike_activation(side: str, strike: float, spot: float, spot_prev: float,
                      vol_accel: float) -> dict:
    """
    Capture the strike 'coming alive' as it moves OTM→ATM with volume accelerating.
      d = signed distance (see strike_distance); d_vel = d(now) − d(prev)  (< 0 = approaching);
      a high-quality activation looks like  d → 0,  d_vel < 0,  vol_accel > 0.
    Returns {distance, distance_vel, transition, activation, ramp}.
    """
    d = strike_distance(side, strike, spot)
    d_prev = strike_distance(side, strike, spot_prev)
    d_vel = d - d_prev
    near = config.ACTIVATION_NEAR_ATM_PCT

    if abs(d) <= near:
        transition = 'ATM'
    elif d > 0:                                   # still OTM
        transition = 'OTM_TO_ATM' if d_vel < 0 else 'OTM_STATIC'
    else:                                          # gone ITM
        transition = 'ATM_TO_ITM' if d_vel < 0 else 'ITM'

    proximity = max(0.0, 1.0 - abs(d) / (near * 8))        # 1 at ATM, fades over ~8×ATM band
    approaching = max(0.0, min(1.0, (-d_vel) / (near * 4))) if d_vel < 0 else 0.0
    accel = 1.0 if vol_accel > 0 else 0.0
    activation = round(0.5 * proximity + 0.3 * approaching + 0.2 * accel, 3)
    ramp = (transition in ('OTM_TO_ATM', 'ATM_TO_ITM') and vol_accel > 0 and proximity > 0.3)
    return {'distance': round(d, 5), 'distance_vel': round(d_vel, 5), 'transition': transition,
            'activation': activation, 'ramp': ramp}


class MigrationTracker:
    """
    Detect ORDERED strike migration (K1→K2→K3) in the direction of travel — continuation, not
    random chain volume. Bullish: top call strike stepping UP while spot rises; bearish: top put
    strike stepping DOWN while spot falls.
    """

    def __init__(self) -> None:
        self._prev: dict = {}   # (symbol, side) -> (top_strike, spot)

    def new_session(self) -> None:
        self._prev.clear()

    def update(self, symbol: str, side: str, top_strike, spot: float) -> dict:
        key = (symbol, side)
        prev = self._prev.get(key)
        self._prev[key] = (top_strike, spot)
        if not prev or top_strike is None or prev[0] is None:
            return {'migrating': False, 'direction': None}
        pk, ps = prev
        if side == 'CALL':
            migrating = top_strike > pk and spot > ps          # strike + spot both rising
        else:
            migrating = top_strike < pk and spot < ps          # strike + spot both falling
        return {'migrating': bool(migrating), 'direction': ('UP' if top_strike > pk
                                                             else 'DOWN' if top_strike < pk else None)}


# ── contract selection + entry freshness ──────────────────────────────────────

def _room_from_low(mark, low, high):
    if mark is None or low is None or high is None or high <= low:
        return None
    return max(0.0, min(1.0, 1.0 - (float(mark) - float(low)) / (float(high) - float(low))))


def select_contract(side: str, side_strikes: list, spot: float) -> dict | None:
    """
    Best eligible contract among ATM ± ENTRY_ADJACENT_STEPS (never blindly ATM, no far-OTM
    lottery). Scored on real participation (fresh premium), liquidity (quote size), spread,
    and room-from-low. Returns the chosen strike's dict enriched with selection metrics, or
    None if nothing near ATM is quotable.
    """
    quotable = [s for s in side_strikes
                if (s.get('ask') or s.get('mark')) and s.get('mark')]
    if not quotable:
        return None
    quotable.sort(key=lambda s: abs(s['strike'] - spot))
    window = quotable[:config.ENTRY_ADJACENT_STEPS + 1]
    max_prem = max((s['fresh_prem'] for s in window), default=0.0) or 1.0

    def score(s):
        participation = (s.get('fresh_prem') or 0) / max_prem
        bid, ask, mark = s.get('bid'), s.get('ask'), s.get('mark')
        spread_pct = ((ask - bid) / mark) if (bid and ask and mark and mark > 0) else 1.0
        spread_term = max(0.0, 1.0 - spread_pct / config.GATE_MAX_SPREAD_PCT)
        liq = min(1.0, (min(s.get('bid_size') or 0, s.get('ask_size') or 0)) / max(1, config.GATE_MIN_QUOTE_SIZE))
        room = _room_from_low(mark, s.get('day_low'), s.get('day_high'))
        room_term = room if room is not None else 0.5
        relevance = max(0.0, 1.0 - abs(s['strike'] - spot) / (spot * 0.01)) if spot else 0.5
        return (0.45 * participation + 0.20 * spread_term + 0.15 * liq
                + 0.10 * room_term + 0.10 * relevance)

    best = max(window, key=score)
    out = dict(best)
    out['low_score'] = _room_from_low(best.get('mark'), best.get('day_low'), best.get('day_high'))
    out['is_atm'] = (best['strike'] == quotable[0]['strike'])
    return out


def entry_freshness(first_price: float, current_price: float) -> dict:
    """
    Opportunity decay: how far the premium has run since first detection.
      EARLY (<+15%) · ACTIVE (+15..35%) · EXTENDED (+35..50%) · MISSED (>+50%).
    """
    if not first_price or first_price <= 0 or current_price is None:
        return {'label': 'EARLY', 'run_pct': 0.0, 'tradeable': True}
    run = (current_price - first_price) / first_price
    if run <= config.FRESH_EARLY_PCT:
        label = 'EARLY'
    elif run <= config.FRESH_ACTIVE_PCT:
        label = 'ACTIVE'
    elif run <= config.FRESH_EXTENDED_PCT:
        label = 'EXTENDED'
    else:
        label = 'MISSED'
    tradeable = not (label == 'MISSED' and config.FRESH_BLOCK_MISSED)
    return {'label': label, 'run_pct': round(run, 3), 'tradeable': tradeable}
