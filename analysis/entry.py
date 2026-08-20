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


def hard_vetoes(c: dict) -> list:
    """§10-A data-derived hard vetoes — returns ALL that apply (not just the first), each as a named
    veto family, so the ledger can attribute the kill precisely (audit item 1/8). (Microstructure
    vetoes — stale/spread/liquidity/execution — stay in the engine.)"""
    v = []
    if (c.get('dist_prob', 0.0) or 0.0) >= config.ENTRY_HARD_DIST:
        v.append('DISTRIBUTION')                              # coherent distribution
    if (c.get('archetype') or {}).get('archetype') == 'DISTRIBUTION':
        v.append('DISTRIBUTION_ARCHETYPE')                    # never route-enter a distribution campaign
    if c.get('shape') in _EXIT_SHAPES:
        v.append('EXIT_SHAPE')                                # mature / exit / stale event shape
    if config.ACCEPTANCE_ENABLED and (c.get('acceptance') or {}).get('label') == 'REJECTION':
        v.append('PREMIUM_REJECTION')                         # heavy volume but premium making lower lows
    if (c.get('dist_low', 1.0) or 1.0) > config.ENTRY_HARD_EXTENSION:
        v.append('OBJECTIVELY_LATE')                          # objectively-late extension
    return v


# map veto family → the §19 reject label the engine returns
_VETO_LABEL = {'DISTRIBUTION': 'ECONOMICALLY_VALID_REJECTION',
               'DISTRIBUTION_ARCHETYPE': 'ECONOMICALLY_VALID_REJECTION',
               'EXIT_SHAPE': 'ECONOMICALLY_VALID_REJECTION',
               'PREMIUM_REJECTION': 'ECONOMICALLY_VALID_REJECTION',
               'OBJECTIVELY_LATE': 'MISSED_DUE_TO_PRICE_EXTENSION'}


def hard_veto(c: dict):
    """Back-compat single-label helper (first applicable veto, or None)."""
    v = hard_vetoes(c)
    return _VETO_LABEL[v[0]] if v else None


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
    """Return the full route decision. Audit item 1: a HARD VETO no longer collapses to score=0.00 —
    the raw route score is ALWAYS computed (so we know what it WOULD have scored), reported as
    `raw_score`, while `score` is null under a veto and `score_status` distinguishes the two states:
        SCORED    → score is a genuine continuous asymmetry
        HARD_VETO → score=None; raw_score is what it would have scored; hard_vetoes[] names why."""
    arch = (c.get('archetype') or {}).get('archetype') or 'UNCLASSIFIED'
    route, w = _ROUTES.get(arch, _DEFAULT)
    ev = evidence(c, m)
    contrib = {k: round(w[k] * ev.get(k, 0.0), 3) for k in w}    # weighted contribution per dimension
    raw = round(sum(contrib.values()), 3)
    # gap decomposition (audit): the components most responsible for the shortfall to the threshold.
    gap = {k: round(w[k] * (1.0 - ev.get(k, 0.0)), 3) for k in w}
    top_drag = sorted(gap.items(), key=lambda kv: -kv[1])[:3]
    vetoes = hard_vetoes(c)
    base = {'route': route, 'archetype': arch, 'evidence': ev, 'weights': w,
            'contributions': contrib, 'top_drag': top_drag, 'raw_score': raw}
    if vetoes:
        return {**base, 'pass': False, 'score': None, 'score_status': 'HARD_VETO',
                'hard_vetoes': vetoes, 'primary_veto': vetoes[0], 'shortfall': None,
                'reason': _VETO_LABEL[vetoes[0]]}
    ok = raw >= config.ENTRY_ROUTE_MIN_SCORE
    return {**base, 'pass': ok, 'score': raw, 'score_status': 'SCORED', 'hard_vetoes': [],
            'primary_veto': None, 'shortfall': round(max(0.0, config.ENTRY_ROUTE_MIN_SCORE - raw), 3),
            'reason': None if ok else 'MISSED_DUE_TO_LOW_ASYMMETRY'}
