"""
MAG7 Attention Engine (Layer 1 — cross-symbol allocation).

The old question, asked per ticker, was "did this strike qualify?" (call-vs-put control
WITHIN a name). The market instead asks "where is institutional attention flowing RIGHT
NOW?" — a finite pool of convexity-chasing capital that rotates between names. This module
is that missing layer: treat fresh option premium as one pool and score each MAG7 name by
its SHARE of it, so a name is traded because it owns the day's attention — not merely
because it printed volume in isolation.

Two layers, cleanly separated:
  Layer 1 (here)      : Where is the money?  attention_share_i = fresh_premium_i / Σ fresh_premium
  Layer 2 (premium)   : What is the money doing?  call vs put control within that name

Attention Score (0-100), configurable weights (default per spec):
  40%  Fresh-premium share   (cross-symbol share of the pool, pool-max normalised)
  25%  Premium velocity      (Δ premium vs the prior poll, positive part, pool-max normalised)
  15%  Premium acceleration  (Δ velocity, positive part, pool-max normalised)
  10%  Control dominance     (how one-sided the name is: 2·control_share − 1, intrinsic 0-1)
  10%  Distance-from-low      (nearer the leader contract's low = more room; optional, 0-1)

Pure functions; no I/O. `attention_board` is the entry point. Velocity/acceleration and the
distance-from-low term are optional — when a component's input is absent its weight is
dropped and the rest renormalised, so the score never silently penalises a missing input.
"""
from typing import Optional

DEFAULT_WEIGHTS = {
    'share': 0.40, 'velocity': 0.25, 'acceleration': 0.15,
    'control': 0.10, 'low': 0.10,
}


def _pool_max_norm(values: dict) -> dict:
    """Normalise a {symbol: raw} map by the pool max of its POSITIVE part → leader≈1, laggards→0."""
    mx = max((v for v in values.values() if v and v > 0), default=0.0)
    if mx <= 0:
        return {k: 0.0 for k in values}
    return {k: max(0.0, (v or 0.0)) / mx for k, v in values.items()}


def control_dominance(control_share: Optional[float]) -> float:
    """Within-name one-sidedness: 0.5 (perfectly split) → 0.0, 1.0 (all one side) → 1.0."""
    if control_share is None:
        return 0.0
    return max(0.0, min(1.0, 2.0 * float(control_share) - 1.0))


def attention_board(current: dict, prev: Optional[dict] = None, prev2: Optional[dict] = None,
                    *, weights: Optional[dict] = None, min_total: float = 0.0,
                    score_min: float = 70.0) -> dict:
    """
    Rank the pool by Attention Score for one poll (minute).

    current : {symbol: {'premium': float,           # this poll's fresh $ premium (Σ over the name)
                        'control_share': float|None, # dominant-side share within the name (0.5-1.0)
                        'control_side': str|None,    # 'CALL'/'PUT'
                        'low_score': float|None}}    # 0-1 room-from-low of the leader contract (optional)
    prev/prev2 : {symbol: premium} from the prior / two-prior polls (for velocity / acceleration).

    Returns {'total_premium', 'leader', 'by_symbol', 'ranked': [ {symbol, premium, share, velocity,
    acceleration, control_dominance, control_side, attention_score, above_threshold, rank}... ]}.
    Sorted by attention_score desc. When Σ premium < min_total the board is returned with
    scores but `leader`=None (too little flow in the pool to allocate attention).
    """
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)
    prev = prev or {}
    prev2 = prev2 or {}
    # Velocity needs one prior poll; acceleration needs two. Absent history → DROP those
    # components and renormalise (never score them as a spurious zero — that would deflate
    # every name on the opening polls). Same "no silent penalty" rule as the low-score.
    has_prev = bool(prev)
    has_prev2 = bool(prev) and bool(prev2)

    symbols = list(current.keys())
    prem = {s: float(current[s].get('premium') or 0.0) for s in symbols}
    total = sum(prem.values())

    share = {s: (prem[s] / total if total > 0 else 0.0) for s in symbols}
    velocity = {s: prem[s] - float(prev.get(s, prem[s])) for s in symbols}
    prev_velocity = {s: float(prev.get(s, 0.0)) - float(prev2.get(s, prev.get(s, 0.0))) for s in symbols}
    acceleration = {s: velocity[s] - prev_velocity[s] for s in symbols}

    share_n = _pool_max_norm(share)
    vel_n = _pool_max_norm(velocity)
    acc_n = _pool_max_norm(acceleration)

    ranked = []
    for s in symbols:
        cur = current[s]
        ctrl = control_dominance(cur.get('control_share'))
        low = cur.get('low_score')
        # Component→weight pairs; an unavailable component (no velocity/accel history, or a
        # None low-score) drops its weight and renormalises the rest.
        parts = [(share_n[s], w['share']), (ctrl, w['control'])]
        if has_prev:
            parts.append((vel_n[s], w['velocity']))
        if has_prev2:
            parts.append((acc_n[s], w['acceleration']))
        if low is not None:
            parts.append((max(0.0, min(1.0, float(low))), w['low']))
        wsum = sum(wt for _, wt in parts) or 1.0
        score = 100.0 * sum(val * wt for val, wt in parts) / wsum
        ranked.append({
            'symbol': s,
            'premium': round(prem[s]),
            'share': round(share[s], 4),
            'velocity': round(velocity[s]),
            'acceleration': round(acceleration[s]),
            'control_dominance': round(ctrl, 3),
            'control_side': cur.get('control_side'),
            'attention_score': round(score, 1),
            'above_threshold': score >= score_min,
        })

    ranked.sort(key=lambda r: r['attention_score'], reverse=True)
    for i, r in enumerate(ranked):
        r['rank'] = i + 1

    leader = ranked[0]['symbol'] if (ranked and total >= min_total
                                     and ranked[0]['above_threshold']) else None
    return {'total_premium': round(total), 'leader': leader,
            'by_symbol': {r['symbol']: r for r in ranked}, 'ranked': ranked}


# ────────────────────────────────────────────────────────────────────────────────────────
# Entry gate + single-trade selection (Layer 3 — "generate ONE trade")
# ────────────────────────────────────────────────────────────────────────────────────────

def gate_signal(board: dict, symbol: str, signal_type: str, *, score_min: float = 70.0,
                require_control_agree: bool = True, max_rank: Optional[int] = None) -> dict:
    """
    Decide whether a fired signal should trade, given this poll's attention board.
      KEEP  — the name owns attention (score ≥ threshold, within rank) AND its within-name
              control side agrees with the trade direction (calls↔BULLISH, puts↔BEARISH).
      DROP  — otherwise, with a reason.
    Returns {decision, reason, attention_score, attention_rank, control_side}.
    """
    row = (board.get('by_symbol') or {}).get(symbol)
    if not row:
        return {'decision': 'DROP', 'reason': 'NO_ATTENTION_DATA',
                'attention_score': None, 'attention_rank': None, 'control_side': None}
    want = 'CALL' if signal_type == 'BULLISH' else 'PUT'
    info = {'attention_score': row['attention_score'], 'attention_rank': row['rank'],
            'control_side': row.get('control_side')}
    if row['attention_score'] < score_min:
        return {'decision': 'DROP', 'reason': 'ATTENTION_BELOW_THRESHOLD', **info}
    if max_rank is not None and row['rank'] > max_rank:
        return {'decision': 'DROP', 'reason': 'ATTENTION_RANK_TOO_LOW', **info}
    if require_control_agree and row.get('control_side') and row['control_side'] != want:
        return {'decision': 'DROP', 'reason': 'CONTROL_SIDE_DISAGREES', **info}
    return {'decision': 'KEEP', 'reason': 'ATTENTION_SUSTAINED', **info}


def select_single_trade(candidates: list, board: dict) -> Optional[dict]:
    """
    The apex of the hierarchy — of the signals that PASSED the gate this poll (each a dict with
    at least 'symbol'), return the one whose name has the highest attention score; None if empty.
    Ties break on premium share. `candidates` are already gate-approved by the caller.
    """
    by = board.get('by_symbol') or {}
    if not candidates:
        return None
    def key(sig):
        r = by.get(sig.get('symbol')) or {}
        return (r.get('attention_score') or 0.0, r.get('share') or 0.0)
    return max(candidates, key=key)


# ────────────────────────────────────────────────────────────────────────────────────────
# Exit logic (Layer 4 — leave on structural target OR attention rotation / control flip)
# ────────────────────────────────────────────────────────────────────────────────────────

class AttentionExitMonitor:
    """
    Per-position exit signal from the attention model: leave when institutional attention has
    ROTATED away from the position's name or within-name CONTROL has flipped against it — but
    only after SUSTAINED deterioration (N consecutive polls), so normal intraday noise in the
    attention board doesn't churn the position. Structural (OI-target) exits are handled
    elsewhere; this is the "the thesis that generated the entry no longer holds" exit.
    """

    def __init__(self) -> None:
        self._streak: dict = {}      # (symbol, side) -> consecutive deteriorated polls

    def reset(self, symbol: str, side: str) -> None:
        self._streak.pop((symbol, side), None)

    def evaluate(self, board: dict, symbol: str, side: str, *, score_min: float = 70.0,
                 rotate_rank: int = 2, sustain_polls: int = 3) -> dict:
        """
        side : the OPEN position's option side ('CALL'/'PUT').
        Deteriorated this poll when EITHER the name fell below the attention threshold / out of
        the top `rotate_rank`, OR within-name control flipped to the opposite side. EXIT only
        once that persists `sustain_polls` polls in a row.
        Returns {exit, reason, streak, attention_rank, attention_score, control_side}.
        """
        key = (symbol, side)
        row = (board.get('by_symbol') or {}).get(symbol) or {}
        rank = row.get('rank')
        score = row.get('attention_score')
        control = row.get('control_side')

        rotated = (score is None or score < score_min or (rank is not None and rank > rotate_rank))
        flipped = bool(control) and control != side
        deteriorated = rotated or flipped

        streak = self._streak.get(key, 0) + 1 if deteriorated else 0
        self._streak[key] = streak

        do_exit = deteriorated and streak >= sustain_polls
        reason = None
        if do_exit:
            reason = 'CONTROL_FLIPPED' if flipped else 'ATTENTION_ROTATED_AWAY'
        return {'exit': do_exit, 'reason': reason, 'streak': streak,
                'attention_rank': rank, 'attention_score': score, 'control_side': control}


# ══════════════════════════════════════════════════════════════════════════════════════════
# v2 — hard eligibility gates → blended multi-factor score → rank eligible names
# ══════════════════════════════════════════════════════════════════════════════════════════
import config as _cfg   # noqa: E402  (module-level import kept local to the v2 block)


def hard_gates(row: dict, *, strict_mult: float = 1.0) -> list:
    """
    Pass/fail gates evaluated BEFORE any scoring, so a 0-100 score can never let several
    mediocre factors compensate for a critical failure. Returns the list of FAILED gate
    reasons ([] = eligible). During the opening window the notional floors are multiplied up.
    """
    fails = []
    bc = row.get('best_contract') or {}
    if (row.get('fresh_prem') or 0) < _cfg.GATE_MIN_SYMBOL_PREMIUM * strict_mult:
        fails.append('SYMBOL_PREMIUM_LOW')
    if (bc.get('fresh_prem') or 0) < _cfg.GATE_MIN_EVENT_NOTIONAL * strict_mult:
        fails.append('EVENT_NOTIONAL_LOW')
    if (row.get('control_share') or 0) < _cfg.GATE_MIN_CONTROL_SHARE:
        fails.append('CONTROL_WEAK')
    if row.get('control_state') == 'BALANCED_CONTEST':
        fails.append('CONTROL_CONTESTED')
    if (row.get('spread_pct') if row.get('spread_pct') is not None else 1.0) > _cfg.GATE_MAX_SPREAD_PCT:
        fails.append('SPREAD_WIDE')
    if (row.get('quote_size') or 0) < _cfg.GATE_MIN_QUOTE_SIZE:
        fails.append('LIQUIDITY_THIN')
    if (row.get('quote_stale_s') if row.get('quote_stale_s') is not None else 999) > _cfg.GATE_MAX_QUOTE_STALE_S:
        fails.append('QUOTE_STALE')
    if (row.get('dist_from_low') or 0) > _cfg.GATE_MAX_DIST_FROM_LOW:
        fails.append('CONTRACT_CHASED')
    if (row.get('top_strike_share') or 0) < _cfg.GATE_MIN_TOP_STRIKE_SHARE:
        fails.append('DISTRIBUTED_BACKGROUND')
    return fails


def _posnorm(values: dict) -> dict:
    mx = max((v for v in values.values() if v and v > 0), default=0.0)
    return {k: (max(0.0, v or 0.0) / mx if mx > 0 else 0.0) for k, v in values.items()}


def build_board(rows: dict, *, opening_strict: bool = False, score_min: float = None,
                min_total: float = None) -> dict:
    """
    v2 cross-ticker board. `rows` = {symbol: enriched row} (fresh_prem/vol, shock, velocity,
    acceleration, control_*, event_quality, best_contract, and the gate raw inputs).

    Steps:  (1) hard_gates each name → eligible set;  (2) blended score from pool-normalised
    factors (premium share, volume share, self-normalised shock, velocity, acceleration,
    control strength, event quality) with configurable AW_* weights;  (3) rank the ELIGIBLE
    names; leader = top eligible clearing score_min with the pool over min_total.
    """
    score_min = _cfg.ATTENTION_SCORE_MIN if score_min is None else score_min
    min_total = _cfg.ATTENTION_MIN_TOTAL if min_total is None else min_total
    strict_mult = _cfg.OPENING_STRICT_MULT if opening_strict else 1.0
    syms = list(rows)

    prem = {s: (rows[s].get('fresh_prem') or 0.0) for s in syms}
    vol = {s: (rows[s].get('fresh_vol') or 0.0) for s in syms}
    total_prem = sum(prem.values())
    total_vol = sum(vol.values()) or 1.0

    prem_share = {s: (prem[s] / total_prem if total_prem > 0 else 0.0) for s in syms}
    vol_share = {s: vol[s] / total_vol for s in syms}
    shock_n = _posnorm({s: rows[s].get('shock') or 0.0 for s in syms})
    vel_n = _posnorm({s: rows[s].get('velocity') or 0.0 for s in syms})
    acc_n = _posnorm({s: rows[s].get('acceleration') or 0.0 for s in syms})

    w = {'prem': _cfg.AW_PREMIUM_SHARE, 'vol': _cfg.AW_VOLUME_SHARE, 'shock': _cfg.AW_SHOCK,
         'vel': _cfg.AW_VELOCITY, 'acc': _cfg.AW_ACCELERATION, 'ctrl': _cfg.AW_CONTROL,
         'evq': _cfg.AW_EVENT_QUALITY}
    wsum = sum(w.values()) or 1.0

    ranked = []
    for s in syms:
        r = rows[s]
        fails = hard_gates(r, strict_mult=strict_mult)
        factors = {
            'prem': _posnorm(prem_share)[s], 'vol': vol_share[s], 'shock': shock_n[s],
            'vel': vel_n[s], 'acc': acc_n[s], 'ctrl': r.get('control_strength') or 0.0,
            'evq': r.get('event_quality') or 0.0,
        }
        score = 100.0 * sum(factors[k] * w[k] for k in w) / wsum
        ranked.append({
            'symbol': s, 'fresh_prem': round(prem[s]), 'fresh_vol': round(vol[s]),
            'premium_share': round(prem_share[s], 4), 'volume_share': round(vol_share[s], 4),
            'share': round(prem_share[s], 4),                              # notify/board-table alias
            'control_dominance': round(r.get('control_strength') or 0.0, 3),  # notify alias
            'premium': round(prem[s]),                                     # notify alias
            'shock': round(r.get('shock') or 0.0, 2), 'velocity': round(r.get('velocity') or 0.0),
            'acceleration': round(r.get('acceleration') or 0.0),
            'control_side': r.get('control_side'), 'control_state': r.get('control_state'),
            'control_share': r.get('control_share'), 'control_strength': r.get('control_strength'),
            'event_class': r.get('event_class'), 'event_quality': r.get('event_quality'),
            'best_contract': r.get('best_contract'),
            'attention_score': round(score, 1), 'eligible': not fails, 'gate_fails': fails,
            'above_threshold': (not fails) and score >= score_min,
        })

    # Rank: eligible names first (by score), ineligible after (context only).
    ranked.sort(key=lambda r: (r['eligible'], r['attention_score']), reverse=True)
    for i, r in enumerate(ranked):
        r['rank'] = i + 1

    leader = next((r['symbol'] for r in ranked
                   if r['eligible'] and r['above_threshold']), None) if total_prem >= min_total else None
    return {'total_premium': round(total_prem), 'total_volume': round(sum(vol.values())),
            'leader': leader, 'by_symbol': {r['symbol']: r for r in ranked}, 'ranked': ranked}


class PositionExitMonitor:
    """
    v2 asymmetric exit — fast when the reversal is overwhelming, confirmed when moderate, and
    NEVER on rank loss alone while the position still controls its side and is profitable.

      • IMMEDIATE  — opposite side controls with overwhelming share AND abnormal shock AND
                     accelerating (velocity>0).
      • FAST       — genuine control loss (opposite side dominant) → confirm over 2 fast polls.
      • MODERATE   — thesis deteriorated (attention rotated) AND our side no longer controls →
                     confirm over the slower sustain count.
    Structural (profit-target / trailing) exits are handled by the engine, not here.
    """

    def __init__(self) -> None:
        self._fast: dict = {}
        self._mod: dict = {}

    def reset(self, symbol, side) -> None:
        self._fast.pop((symbol, side), None)
        self._mod.pop((symbol, side), None)

    def evaluate(self, board: dict, symbol: str, side: str, *, pnl: float,
                 score_min: float = None, rotate_rank: int = None) -> dict:
        score_min = _cfg.ATTENTION_SCORE_MIN if score_min is None else score_min
        rotate_rank = _cfg.ATTENTION_EXIT_ROTATE_RANK if rotate_rank is None else rotate_rank
        key = (symbol, side)
        row = (board.get('by_symbol') or {}).get(symbol) or {}
        ctrl_side = row.get('control_side')
        ctrl_share = row.get('control_share') or 0.0
        shock = row.get('shock') or 0.0
        velocity = row.get('velocity') or 0.0
        rank = row.get('rank')
        score = row.get('attention_score')

        opp_controls = bool(ctrl_side) and ctrl_side != side
        still_controls = (ctrl_side == side and (row.get('control_strength') or 0) > 0.3)

        # IMMEDIATE — overwhelming, abnormal, accelerating reversal.
        if opp_controls and ctrl_share >= _cfg.EXIT_IMMEDIATE_OPP_SHARE \
                and shock >= _cfg.EXIT_IMMEDIATE_SHOCK and velocity > 0:
            self.reset(symbol, side)
            return {'exit': True, 'reason': 'CONTROL_FLIP_OVERWHELMING', 'mode': 'IMMEDIATE',
                    'fast_streak': 0, 'mod_streak': 0}

        # FAST — genuine control loss, confirm over a couple of fast polls.
        if opp_controls:
            fs = self._fast.get(key, 0) + 1
            self._fast[key] = fs
            if fs >= _cfg.EXIT_FAST_CONFIRM_POLLS:
                self.reset(symbol, side)
                return {'exit': True, 'reason': 'CONTROL_FLIPPED', 'mode': 'FAST',
                        'fast_streak': fs, 'mod_streak': 0}
        else:
            self._fast[key] = 0

        # MODERATE — attention rotated away AND we no longer control (rank loss alone is NOT
        # enough if we still control and are profitable).
        rotated = (score is None or score < score_min or (rank is not None and rank > rotate_rank))
        thesis_lost = rotated and not (still_controls and pnl >= 0) if _cfg.EXIT_REQUIRE_CONTROL_LOSS \
            else rotated
        if thesis_lost:
            ms = self._mod.get(key, 0) + 1
            self._mod[key] = ms
            if ms >= _cfg.EXIT_MODERATE_SUSTAIN:
                self.reset(symbol, side)
                return {'exit': True, 'reason': 'ATTENTION_ROTATED_AWAY', 'mode': 'MODERATE',
                        'fast_streak': self._fast.get(key, 0), 'mod_streak': ms}
        else:
            self._mod[key] = 0

        return {'exit': False, 'reason': None, 'mode': None,
                'fast_streak': self._fast.get(key, 0), 'mod_streak': self._mod.get(key, 0)}
