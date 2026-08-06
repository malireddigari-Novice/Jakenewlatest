"""
Campaign archetype classification (spec §10) — pure, I/O-free.

The base engine over-rewards one shape: the compact 0DTE shock (TSLA-style). But institutional
commitment appears in several forms, and each has different expectations for how premium should
respond and when the campaign is "healthy". This module classifies the developing campaign into an
archetype from the already-computed features (volume geometry, abnormality, response, self-
sustainability, distribution probability, and — when available — the expiry structure). It does NOT
force every winner to look like a shock.

Phase 4 is SHADOW: the archetype is computed and logged for research. Applying archetype-specific
entry expectations (e.g. tolerating a delayed response for PERSISTENT_ACCUMULATION) is reserved
behind `ARCHETYPE_GATE_ENABLED` and not wired into the entry decision yet.

Archetypes: SHOCK_ACCUMULATION, PERSISTENT_ACCUMULATION, FORWARD_POSITIONING,
SELF_SUSTAINING_EXPANSION, SHAKEOUT_AND_RECOVERY, STAIR_STEP_ACCUMULATION, IMPULSE_REPRICING,
CROSS_EXPIRY_ACCUMULATION, DISTRIBUTION, UNCLASSIFIED.
"""
import config


def classify(f: dict) -> dict:
    """f: features from the engine's candidate build — vp (volume_pattern dict), mass_z, impulse,
    velocity, resp_event, self_sust, eff_trend (label), rel_premium, dist_prob, shakeout, mfe, and
    optional expiry_class / strike_class. Returns {archetype, confidence, reason}."""
    vp = f.get('vp') or {}
    z = f.get('mass_z', 0.0) or 0.0
    resp = f.get('resp_event', 0.0) or 0.0
    self_sust = f.get('self_sust', 0.0) or 0.0
    eff_trend = f.get('eff_trend')
    rel_prem = f.get('rel_premium', 1.0) or 1.0
    dist_prob = f.get('dist_prob', 0.0) or 0.0
    shakeout = f.get('shakeout', 0.0) or 0.0
    mfe = f.get('mfe', 0.0) or 0.0
    expiry_class = f.get('expiry_class')
    dominant = vp.get('dominant', 0.0)
    burst = vp.get('burst', 0)
    decay = vp.get('decay_rate', 0.0)
    reaccel = vp.get('reaccel', 0.0)
    compact = vp.get('compact', False)

    def out(a, conf, reason):
        return {'archetype': a, 'confidence': round(max(0.0, min(1.0, conf)), 2), 'reason': reason}

    # 1) DISTRIBUTION first — heavy activity resembling unwinding / exit flow overrides the rest.
    if dist_prob >= config.DIST_PROB_EXIT or resp <= config.RESP_NEG_REJECT:
        return out('DISTRIBUTION', max(dist_prob, 0.6), 'distribution/exit evidence dominant')

    # 2) SHAKEOUT_AND_RECOVERY — a real prior excursion, a dip, and a recovery back through value.
    if (shakeout >= config.SHAKEOUT_MIN and mfe >= config.RESP_MFE_MIN
            and resp >= config.RESP_DELAYED_FLOOR):
        return out('SHAKEOUT_AND_RECOVERY', 0.5 + shakeout / 2.0, 'dip-then-recover with prior MFE')

    # 3) SELF_SUSTAINING_EXPANSION — premium keeps progressing as volume fades (the AAPL case).
    if (self_sust >= config.ARCH_SELF_SUST_MIN and rel_prem > 1.0
            and eff_trend != 'DECAYING' and decay >= config.ARCH_VOLUME_FADE):
        return out('SELF_SUSTAINING_EXPANSION', self_sust, 'premium rising while volume fades')

    # 4) Multi-expiry structure (when the P3 scan provides it).
    if expiry_class == 'SAME_SIDE_MULTI_EXPIRY_CONTROL':
        return out('CROSS_EXPIRY_ACCUMULATION', 0.6, 'same side building across expiries')
    if expiry_class == 'FORWARD_POSITIONING':
        return out('FORWARD_POSITIONING', 0.55, 'concentration in a forward expiry')

    # 5) STAIR_STEP_ACCUMULATION — faded then fired again (multiple clusters).
    if reaccel > 0.0 and burst >= config.VP_BURST_PERSIST_MIN:
        return out('STAIR_STEP_ACCUMULATION', 0.5 + reaccel / 2.0, 'reacceleration after a pause')

    # 6) SHOCK_ACCUMULATION — one compact, dominant, highly abnormal burst (specific → before impulse).
    if compact and dominant >= config.ARCH_SHOCK_DOMINANT and z >= config.ARCH_SHOCK_Z:
        return out('SHOCK_ACCUMULATION', min(1.0, z / 6.0), 'compact dominant abnormal burst')

    # 7) IMPULSE_REPRICING — premium repricing strongly while volume has not arrived late.
    if resp >= config.ARCH_IMPULSE_RESP and vp.get('skew', 0.0) <= 0.0 and f.get('velocity', 0.0) > 0:
        return out('IMPULSE_REPRICING', 0.5 + min(0.5, resp), 'premium repricing ahead of peak volume')

    # 8) PERSISTENT_ACCUMULATION — repeated moderate participation surviving pauses.
    if burst >= config.VP_BURST_PERSIST_MIN and dominant < config.ARCH_SHOCK_DOMINANT:
        return out('PERSISTENT_ACCUMULATION', 0.45 + min(0.4, burst / 10.0),
                   'repeated moderate participation')

    return out('UNCLASSIFIED', 0.2, 'no dominant archetype signature')


# Per-archetype CampaignQualityScore weights (follow-up §17): acceleration should NOT dominate a
# persistent campaign, persistence should NOT dominate a shock, expiry concentration matters for a
# forward position, post-volume premium progress (self-sustainability) matters for expansion. Signals
# are all pre-normalised to 0-1: persistence, notional, control, continuation, low_dist (=1−dist_prob),
# acceleration, response, expiry, self_sust.
_QUALITY_W = {
    'SHOCK_ACCUMULATION':        dict(acceleration=.30, response=.20, control=.15, notional=.15, low_dist=.15, persistence=.05),
    'IMPULSE_REPRICING':         dict(acceleration=.30, response=.25, control=.10, notional=.15, low_dist=.15, persistence=.05),
    'PERSISTENT_ACCUMULATION':   dict(persistence=.40, notional=.20, control=.15, continuation=.10, low_dist=.10, acceleration=.05),
    'STAIR_STEP_ACCUMULATION':   dict(persistence=.40, notional=.20, control=.15, continuation=.10, low_dist=.10, acceleration=.05),
    'SELF_SUSTAINING_EXPANSION': dict(self_sust=.35, response=.20, persistence=.20, control=.10, low_dist=.15),
    'SHAKEOUT_AND_RECOVERY':     dict(response=.25, persistence=.20, control=.15, notional=.15, low_dist=.15, acceleration=.10),
    'FORWARD_POSITIONING':       dict(expiry=.30, persistence=.25, notional=.20, control=.15, low_dist=.10),
    'CROSS_EXPIRY_ACCUMULATION': dict(expiry=.30, persistence=.25, notional=.20, control=.15, low_dist=.10),
}
_QUALITY_DEFAULT = dict(persistence=.25, notional=.20, control=.15, continuation=.10, low_dist=.15, acceleration=.15)


def quality_score(arch: str, f: dict) -> float:
    """Archetype-aware CampaignQualityScore 0-100 (§17). f carries the 0-1 signals above. Computed
    and logged for research; it scores a campaign with archetype-appropriate evidence rather than one
    universal weighting (so an orderly AAPL-style build is not penalised for lacking a shock)."""
    w = _QUALITY_W.get(arch, _QUALITY_DEFAULT)
    score = sum(weight * max(0.0, min(1.0, f.get(sig, 0.0) or 0.0)) for sig, weight in w.items())
    return round(100.0 * score, 1)
