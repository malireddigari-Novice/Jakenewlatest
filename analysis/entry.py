"""
Archetype-aware entry routing (follow-up spec §10) — pure, I/O-free.

The base engine's entry decision is a brittle CONJUNCTION:
    rank AND control AND notional AND compactness AND cheapness AND response AND posterior AND EV = ENTRY
Each clause is reasonable alone, but the conjunction eliminates genuine winners — and it is internally
contradictory (it demands early pricing while requiring late confirmation, so by the time every clause
agrees the campaign is already 'chased'). This module replaces that with:

  A. HARD VETOES — the few conditions that should always kill an entry: coherent distribution and an
     objectively-late extension (the engine keeps the microstructure vetoes: stale quote / spread /
     liquidity / execution / duplicate campaign).
  B. ARCHETYPE-SPECIFIC ROUTES — different evidence matters for a shock vs a persistent build vs a
     forward position (FAST_SHOCK / PERSISTENT_BUILD / SHAKEOUT_RECOVERY / FORWARD_POSITIONING /
     STAIR_STEP / CROSS_STRIKE).
  C. TOTAL EXPECTED ASYMMETRY — rank, notional, control, response, abnormality, persistence and
     cheapness each CONTRIBUTE evidence; strong evidence in one dimension can compensate a weak
     reading in another. Entry passes when the (no-veto) weighted asymmetry clears the route threshold.

Gated by ENTRY_ROUTES_ENABLED in the engine; default OFF, so the validated conjunctive path is
unchanged until this is turned on and validated.
"""
import config

# Per-archetype evidence weights (must sum ≈ 1.0): rank, notional, control, response, abn, persist, cheap.
_ROUTES = {
    'SHOCK_ACCUMULATION':       ('FAST_SHOCK',           dict(rank=.15, notional=.15, control=.15, response=.10, abn=.30, persist=.05, cheap=.10)),
    'IMPULSE_REPRICING':        ('FAST_SHOCK',           dict(rank=.10, notional=.15, control=.10, response=.25, abn=.20, persist=.10, cheap=.10)),
    'PERSISTENT_ACCUMULATION':  ('PERSISTENT_BUILD',     dict(rank=.05, notional=.15, control=.15, response=.10, abn=.10, persist=.35, cheap=.10)),
    'SELF_SUSTAINING_EXPANSION':('PERSISTENT_BUILD',     dict(rank=.05, notional=.10, control=.15, response=.25, abn=.05, persist=.30, cheap=.10)),
    'STAIR_STEP_ACCUMULATION':  ('STAIR_STEP',           dict(rank=.10, notional=.15, control=.15, response=.10, abn=.10, persist=.30, cheap=.10)),
    'SHAKEOUT_AND_RECOVERY':    ('SHAKEOUT_RECOVERY',    dict(rank=.10, notional=.15, control=.15, response=.20, abn=.10, persist=.20, cheap=.10)),
    'FORWARD_POSITIONING':      ('FORWARD_POSITIONING',  dict(rank=.05, notional=.20, control=.15, response=.05, abn=.10, persist=.25, cheap=.20)),
    'CROSS_EXPIRY_ACCUMULATION':('CROSS_STRIKE',         dict(rank=.05, notional=.20, control=.15, response=.05, abn=.10, persist=.25, cheap=.20)),
}
_DEFAULT = ('PERSISTENT_BUILD', dict(rank=.15, notional=.20, control=.15, response=.10, abn=.15, persist=.15, cheap=.10))


def _clamp(x):
    return max(0.0, min(1.0, x))


# Non-tradeable event shapes — a route must NEVER enter a campaign that is being unwound, has a
# collapsing premium, or is a lone/late chase. Route mode bypasses the soft accumulation/shape gates,
# so these have to be hard vetoes here. Expanded 2026-08-06 after route mode entered a GOOGL 362.5C
# HEAVY_VOLUME_NEGATIVE_RESPONSE (premium being destroyed) and an AMZN ISOLATED_PRINT late-chase.
_EXIT_SHAPES = {'MATURE_SCALING_ACTIVITY', 'DISTRIBUTION_AT_PREMIUM_HIGH',
                'EXHAUSTION_OR_EXIT_FLOW', 'STALE_OPENING_VOLUME',
                'HEAVY_VOLUME_NEGATIVE_RESPONSE', 'ISOLATED_PRINT'}


def hard_veto(c: dict):
    """§10-A data-derived hard vetoes. Returns a §19 reject label or None. (Microstructure vetoes —
    stale/spread/liquidity/execution — stay in the engine.)"""
    if (c.get('dist_prob', 0.0) or 0.0) >= config.ENTRY_HARD_DIST:
        return 'ECONOMICALLY_VALID_REJECTION'                 # coherent distribution
    if (c.get('archetype') or {}).get('archetype') == 'DISTRIBUTION':
        return 'ECONOMICALLY_VALID_REJECTION'                 # never route-enter a distribution campaign
    if c.get('shape') in _EXIT_SHAPES:
        return 'ECONOMICALLY_VALID_REJECTION'                 # mature / exit / stale event shape
    if config.ACCEPTANCE_ENABLED and (c.get('acceptance') or {}).get('label') == 'REJECTION':
        return 'ECONOMICALLY_VALID_REJECTION'                 # heavy volume but premium making lower lows
    if (c.get('dist_low', 1.0) or 1.0) > config.ENTRY_HARD_EXTENSION:
        return 'MISSED_DUE_TO_PRICE_EXTENSION'                # objectively-late extension
    return None


def evidence(c: dict, m: dict) -> dict:
    """0-1 evidence per dimension. Notional uses the max of the selected contract and the breadth-
    adjusted surface (so an AMZN-style ladder contributes its cluster mass, not one strike)."""
    side = c.get('side')
    rank = m.get('rank', 9) or 9
    share = m.get('attention_share', 0.0) or 0.0
    z = m.get('mass_z', 0.0) or 0.0
    ctrl = (m.get('call_control', 0.0) if side == 'CALL' else m.get('put_control', 0.0)) or 0.0
    surf = c.get('surface') or {}
    eff_notional = max(c.get('notional', 0.0) or 0.0, surf.get('breadth_adjusted_strength', 0.0) or 0.0)
    dist = c.get('dist_low', 1.0) or 1.0
    cheap = (_clamp(1.0 - (dist - 1.0) / max(config.GATE_MAX_DIST_FROM_LOW - 1.0, 1e-9)) if dist >= 1 else 1.0)
    persist = max(c.get('self_sust', 0.0) or 0.0, c.get('cont_prob', 0.0) or 0.0)
    rank_ev = (1.0 if rank == 1 else 0.6 if rank == 2 else 0.3 if rank == 3 else 0.1) * _clamp(share / 0.5)
    # Response evidence: premium appreciation OR absorption (heavy volume + premium holding) — we do
    # NOT require appreciation (that would make us late; the AMZN lesson).
    resp_ev = _clamp(0.5 + (c.get('resp_event', 0.0) or 0.0) * 2.0)
    acc = (c.get('acceptance') or {})
    if acc.get('absorbing'):
        resp_ev = max(resp_ev, acc.get('score', 0.0))
    return {'rank': _clamp(rank_ev),
            'notional': _clamp(eff_notional / (config.GATE_MIN_EVENT_NOTIONAL * 2.0)),
            'control': _clamp((ctrl - 0.5) * 2.0),
            'response': resp_ev,
            'abn': _clamp(z / 6.0),
            'persist': _clamp(persist),
            'cheap': cheap}


def decide(c: dict, m: dict) -> dict:
    """Return {pass, score, route, archetype, evidence, reason}. A hard veto short-circuits to fail."""
    veto = hard_veto(c)
    if veto:
        return {'pass': False, 'score': 0.0, 'route': None,
                'archetype': (c.get('archetype') or {}).get('archetype'), 'evidence': {}, 'reason': veto}
    arch = (c.get('archetype') or {}).get('archetype') or 'UNCLASSIFIED'
    route, w = _ROUTES.get(arch, _DEFAULT)
    ev = evidence(c, m)
    contrib = {k: round(w[k] * ev.get(k, 0.0), 3) for k in w}    # weighted contribution per dimension
    score = sum(contrib.values())
    ok = score >= config.ENTRY_ROUTE_MIN_SCORE
    # gap decomposition (audit): how far each dimension is from its own max possible contribution —
    # the components most responsible for the shortfall to ENTRY_ROUTE_MIN_SCORE, largest first.
    gap = {k: round(w[k] * (1.0 - ev.get(k, 0.0)), 3) for k in w}
    top_drag = sorted(gap.items(), key=lambda kv: -kv[1])[:3]
    return {'pass': ok, 'score': round(score, 3), 'route': route, 'archetype': arch,
            'evidence': ev, 'weights': w, 'contributions': contrib, 'top_drag': top_drag,
            'shortfall': round(max(0.0, config.ENTRY_ROUTE_MIN_SCORE - score), 3),
            'reason': None if ok else 'MISSED_DUE_TO_LOW_ASYMMETRY'}
