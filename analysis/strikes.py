"""
Strike-surface aggregation (spec §23-25) — pure, I/O-free.

The base engine asks a contract-selection question ("which single strike dominates?") and can
therefore MISS a real ticker-level campaign that is spread across a ladder of strikes — the AMZN
case, where call volume was distributed across ~237.5…257.5 with no single strike passing a
dominant-strike test. Broad participation is not weak participation.

This module answers the TICKER-LEVEL question first — "is capital concentrating in this side across
the strike surface?" — and only then names a representative contract. It takes one side's per-strike
mass (from `mass.compute_masses`'s `call_strikes` / `put_strikes`) and returns surface measures plus
a classification: SINGLE_STRIKE_DOMINANT, TWO_STRIKE_COORDINATED, ADJACENT_STRIKE_LADDER,
BROAD_SURFACE_ACCUMULATION, DISTRIBUTED_BACKGROUND, THIN.

Phase 5 is SHADOW: computed + logged. Letting a broad-surface campaign qualify for entry without a
single dominant strike is reserved behind `SURFACE_GATE_ENABLED` (default OFF) and not wired in yet.
"""
import config


def surface_profile(strike_mass: dict, spot: float, prev_center=None) -> dict:
    """strike_mass: {strike: mass} for ONE side. Returns surface measures + classification +
    a representative strike (nearest the mass-weighted center)."""
    active = {float(k): float(m) for k, m in strike_mass.items() if m and m > 0}
    total = sum(active.values())
    if total <= 0:
        return {'ladder_mass': 0.0, 'breadth': 0, 'n_active': 0, 'concentration': 0.0,
                'dispersion': 0.0, 'weighted_center': None, 'top_strike': None, 'top_share': 0.0,
                'second_share': 0.0, 'top2_share': 0.0, 'contiguous': False, 'momentum': None,
                'breadth_adjusted_strength': 0.0, 'representative_strike': None,
                'classification': 'THIN'}

    shares = {k: m / total for k, m in active.items()}
    hhi = sum(s * s for s in shares.values())                      # StrikeConcentration
    ranked = sorted(shares.items(), key=lambda x: -x[1])
    top_k, top_s = ranked[0]
    second_s = ranked[1][1] if len(ranked) > 1 else 0.0
    top2_s = top_s + second_s
    meaningful = sorted(k for k, s in shares.items() if s >= config.SURFACE_STRIKE_MIN_SHARE)
    breadth = len(meaningful)                                       # LadderParticipationBreadth
    center = sum(k * m for k, m in active.items()) / total          # WeightedStrikeCenter
    var = sum(m * (k - center) ** 2 for k, m in active.items()) / total
    dispersion = round((var ** 0.5) / spot, 4) if spot else 0.0     # StrikeDispersion (÷ spot)

    contiguous = False                                             # adjacent, evenly-spaced band?
    if breadth >= 2:
        gaps = [meaningful[i + 1] - meaningful[i] for i in range(breadth - 1)]
        step = min(gaps) if gaps else 0.0
        contiguous = step > 0 and all(g <= step * 1.5 for g in gaps)

    # BreadthAdjustedCampaignStrength — REWARD broad participation instead of penalising it: a
    # normalised total that grows with how many strikes each carry meaningful weight (spec §24).
    breadth_adjusted = round(total * (1.0 + config.SURFACE_BREADTH_BONUS * max(0, breadth - 1)), 1)
    momentum = round((center - prev_center) / spot, 4) if (prev_center and spot) else None

    rep = min(active, key=lambda k: abs(k - center))               # representative contract
    n_active = len(active)

    return {'ladder_mass': round(total), 'breadth': breadth, 'n_active': n_active,
            'concentration': round(hhi, 3), 'dispersion': dispersion,
            'weighted_center': round(center, 2), 'top_strike': top_k, 'top_share': round(top_s, 3),
            'second_share': round(second_s, 3), 'top2_share': round(top2_s, 3),
            'contiguous': contiguous, 'momentum': momentum,
            'breadth_adjusted_strength': breadth_adjusted, 'representative_strike': rep,
            'classification': _classify(top_s, second_s, top2_s, breadth, n_active, contiguous)}


def _classify(top_s, second_s, top2_s, breadth, n_active, contiguous) -> str:
    if top_s >= config.SURFACE_SINGLE:
        return 'SINGLE_STRIKE_DOMINANT'
    if top2_s >= config.SURFACE_TWO_TOP2 and second_s >= config.SURFACE_TWO_SECOND and breadth <= 3:
        return 'TWO_STRIKE_COORDINATED'
    if breadth >= config.SURFACE_BROAD_BREADTH:
        # many strikes each carry meaningful weight — a real ticker-level campaign (the AMZN case),
        # NOT weak background. Distinguish a tight ladder from a genuinely broad surface.
        return 'ADJACENT_STRIKE_LADDER' if contiguous else 'BROAD_SURFACE_ACCUMULATION'
    if breadth >= config.SURFACE_LADDER_BREADTH and contiguous:
        return 'ADJACENT_STRIKE_LADDER'
    if breadth <= 1 and n_active >= 4:
        return 'DISTRIBUTED_BACKGROUND'         # smeared across many strikes, none meaningful
    return 'THIN'


def is_tradeable_surface(cls: str) -> bool:
    """Surface classes that represent a genuine ticker-level campaign (spec §23: broad participation
    can be a meaningful campaign). Used only when SURFACE_GATE_ENABLED is turned on."""
    return cls in ('SINGLE_STRIKE_DOMINANT', 'TWO_STRIKE_COORDINATED',
                   'ADJACENT_STRIKE_LADDER', 'BROAD_SURFACE_ACCUMULATION')
