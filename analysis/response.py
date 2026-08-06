"""
Price-response validation — distinguishing ACCUMULATION from DISTRIBUTION.

Large option volume is not inherently directional. The same heavy print can be institutions
accumulating cheap convexity (buy) or distributing / liquidating / hedging / selling into a
dying move. The only tradeable case is accumulation: fresh volume arriving while the option is
still cheap AND the premium then RESPONDS positively (expands). Heavy volume while the premium
COLLAPSES is distribution — management information, never a new entry.

This module turns a contract's recent per-minute volume series + its price response since the
event into:
  • the volume-pattern metrics (EventShare20, Top3Share20, DominantSingleBar, BurstPersistence,
    CompactCluster, PersistentDistributedFlow, ActiveDensity20),
  • an event SHAPE (DORMANT_BACKGROUND / ISOLATED_PRINT / COMPACT_SHOCK /
    PERSISTENT_COMPACT_WAVE / DISTRIBUTED_BACKGROUND / MATURE_SCALING_ACTIVITY /
    EXHAUSTION_OR_EXIT_FLOW),
  • an accumulation/distribution LABEL and an `eligible` flag — only accumulation is tradeable.

The TSLA 312.5P case is the positive control: dormant background → a compact statistically
abnormal shock near the contract's value low, premium expanding immediately after. TSLA 315C /
NVDA 207.5C (heavy volume while premium makes lower lows) are the negatives → rejected.

Pure functions. `classify()` is the entry point.
"""
import math

import config

ACCUMULATION = {'COMPACT_ACCUMULATION', 'PERSISTENT_ACCUMULATION',
                'SINGLE_STRIKE_ACCUMULATION', 'COORDINATED_CHAIN_ACCUMULATION'}


def price_response(event_price, current_price) -> float:
    """(current − event) / event, the option's response since the volume event began."""
    if not event_price or event_price <= 0 or current_price is None:
        return 0.0
    return round(current_price / event_price - 1.0, 4)


def response_efficiency(resp_event, fresh_notional, ref=None) -> float:
    """
    Premium-response EFFICIENCY — how much price progress each unit of fresh flow bought.
        efficiency = ΔP% / (fresh_notional / ref_notional)
    High in early accumulation ($300k lifts the premium 35%); low or negative in maturity /
    distribution ($1.2M and the premium is flat). `ref` sets the $ of fresh notional that
    counts as one unit of flow.
    """
    ref = ref or config.RESP_EFF_REF_NOTIONAL
    units = max((fresh_notional or 0.0) / ref, 0.05)
    return round((resp_event or 0.0) / units, 4)


def distribution_probability(*, extension=1.0, eff_decay=0.0, rel_premium=1.0, iv_slope=None,
                             giveback=0.0, opp_accel_norm=0.0, spot_confirms=True) -> float:
    """
    Joint probability [0-1] that heavy activity is DISTRIBUTION rather than accumulation, a
    weighted logistic over the deterioration features (no single component decides it):
      • extension       — how far above the value low the premium already is,
      • eff_decay        — response efficiency falling from the campaign's peak (negative = worse),
      • rel_premium      — premium high vs the campaign's start (2×, 6× …),
      • iv_slope         — IV rolling over (dIV/dt < 0) while premium stalls,
      • giveback         — premium giving back from its own peak (fraction),
      • opp_accel_norm   — opposite side accelerating (0-1),
      • spot_confirms    — the underlying still confirming the direction.
    All inputs are pre-normalised by the caller. Returns 0.0 when the feature is disabled.
    """
    if not config.DIST_PROB_ENABLED:
        return 0.0
    logit = config.DIST_PROB_BIAS
    logit += config.DW_EXTENSION * max(0.0, (extension or 0.0) - config.GATE_MAX_DIST_FROM_LOW)
    logit += config.DW_EFF_DECAY * max(0.0, -(eff_decay or 0.0))
    logit += config.DW_REL_PREMIUM * min(3.0, max(0.0, (rel_premium or 1.0) - 2.0))
    if iv_slope is not None:
        logit += config.DW_IV_ROLL * min(1.0, max(0.0, -iv_slope) * 20.0)
    logit += config.DW_GIVEBACK * min(1.5, max(0.0, giveback or 0.0) / 0.35)
    logit += config.DW_OPP_ACCEL * max(0.0, min(1.0, opp_accel_norm or 0.0))
    logit += config.DW_SPOT_FADE * (0.0 if spot_confirms else 1.0)
    return round(1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, logit)))), 3)


def volume_pattern(minute_vols: list, event_min: int = None) -> dict:
    """
    Compact-burst metrics from a contract's per-minute fresh-volume series (oldest→newest,
    trailing ~20 min). Detects the shape of the TSLA 312.5P compact institutional burst vs
    broadly-distributed background.
    """
    event_min = event_min if event_min is not None else config.VP_EVENT_MIN
    n = len(minute_vols)
    total = float(sum(minute_vols))
    if n == 0 or total <= 0:
        return {'total': 0.0, 'event_vol': 0.0, 'event_share': 0.0, 'top3_share': 0.0,
                'dominant': 0.0, 'burst': 0, 'active_density': 0.0, 'pre_mean': 0.0,
                'skew': 0.0, 'entropy': 0.0, 'gini': 0.0, 'decay_rate': 0.0,
                'half_life': 0.0, 'reaccel': 0.0, 'silence': 1.0,
                'compact': False, 'distributed': False}
    ev = minute_vols[-event_min:]
    event_vol = float(sum(ev))
    top3 = float(sum(sorted(minute_vols)[-3:]))
    dominant = max(minute_vols) / max(event_vol, 1e-9)
    pre = minute_vols[:-event_min] if n > event_min else []
    pre_mean = (sum(pre) / len(pre)) if pre else 0.0
    thresh = max(pre_mean * config.VP_MEANINGFUL_MULT, 1.0)
    meaningful = sum(1 for v in minute_vols if v > thresh)
    burst = 0
    for v in reversed(minute_vols):          # trailing consecutive elevated minutes
        if v > thresh:
            burst += 1
        else:
            break
    event_share = event_vol / total
    top3_share = top3 / total
    active_density = meaningful / max(n, 1)
    # VolumeSkew: did activity arrive EARLY (−1), CENTRALLY (0), or LATE (+1) in the window?
    # Volume-weighted mean bin position mapped to [-1, 1]. Late-arriving volume after a run is
    # a distribution / late-chasing tell; early volume that has since gone quiet is stale.
    if n > 1:
        centre = (n - 1) / 2.0
        wpos = sum(i * v for i, v in enumerate(minute_vols)) / total
        skew = (wpos - centre) / centre
    else:
        skew = 0.0
    # ── geometry of the volume through time (Gini/entropy = concentration; decay/half-life/
    # reaccel/silence = how the burst fades and whether it fires again) ──
    ps = [v / total for v in minute_vols]
    entropy = -sum(p * math.log(p) for p in ps if p > 0) / math.log(n) if n > 1 else 0.0
    sv = sorted(minute_vols)
    cum = sum((i + 1) * v for i, v in enumerate(sv))
    gini = (2.0 * cum) / (n * total) - (n + 1.0) / n if n > 0 else 0.0
    peak = max(minute_vols)
    peak_i = minute_vols.index(peak)
    post = minute_vols[peak_i + 1:]
    decay_rate = max(0.0, 1.0 - (sum(post) / len(post)) / peak) if (post and peak > 0) else 0.0
    half_life = 0
    for j, v in enumerate(post):                 # bins after the peak until volume halves
        half_life = j + 1
        if v <= peak / 2.0:
            break
    else:
        half_life = len(post)
    # Reacceleration: after fading below half-peak, does a later bin climb back above half-peak?
    reaccel = 0.0
    if post:
        faded = False
        for v in post:
            if v <= peak / 2.0:
                faded = True
            elif faded and v > peak / 2.0:
                reaccel = round(min(1.0, v / peak), 3)
                break
    silence = sum(1 for v in minute_vols if v <= thresh) / max(n, 1)
    compact = event_share >= config.VP_EVENTSHARE20_MIN and top3_share >= config.VP_TOP3SHARE20_MIN
    # Distributed background: volume smeared across many minutes, no dominant recent burst.
    distributed = top3_share < 0.45 and active_density > 0.4 and dominant < 0.4
    return {'total': round(total), 'event_vol': round(event_vol),
            'event_share': round(event_share, 3), 'top3_share': round(top3_share, 3),
            'dominant': round(dominant, 3), 'burst': burst,
            'active_density': round(active_density, 3), 'pre_mean': round(pre_mean, 1),
            'skew': round(skew, 3), 'entropy': round(entropy, 3), 'gini': round(max(0.0, gini), 3),
            'decay_rate': round(decay_rate, 3), 'half_life': half_life,
            'reaccel': reaccel, 'silence': round(silence, 3),
            'compact': compact, 'distributed': distributed}


def classify(vp: dict, resp_event: float, resp_recent: float,
             value_low_dist, strike_class: str, mfe=None, shakeout=0.0) -> dict:
    """
    Combine the volume pattern + price response + value-low distance into an event shape and an
    accumulation/distribution label. Returns {shape, label, eligible, reason}.
    Only accumulation labels are eligible for a new entry.

    `mfe` (max favourable excursion since the event) and `shakeout` (dip-then-recover score) enable
    the DELAYED-CONVEXITY tolerance: a compact campaign that briefly consolidated — showed a real
    positive excursion and is recovering back through its event price — is NOT rejected merely
    because this instant's response is slightly negative (the NVDA-put shakeout case).
    """
    # Delayed convexity: the premium already expanded (mfe) and, after a shakeout, is recovering.
    delayed = (config.ALLOW_DELAYED_CONVEXITY and (mfe or 0.0) >= config.RESP_MFE_MIN
               and (shakeout or 0.0) >= config.SHAKEOUT_MIN and resp_event >= config.RESP_DELAYED_FLOOR)
    # ── event shape ──
    if vp['total'] <= 0 or vp['event_vol'] <= 0:
        shape = 'DORMANT_BACKGROUND'
    elif resp_event <= config.RESP_NEG_REJECT and not delayed:
        shape = 'EXHAUSTION_OR_EXIT_FLOW'          # heavy volume, premium collapsing since event
    elif value_low_dist is not None and value_low_dist > config.VP_VALUE_LOW_MAX:
        # Already extended from the value low. If the premium is ALSO giving back recently,
        # this is the classic heavy-volume-at-the-high distribution; otherwise mature scaling.
        shape = ('DISTRIBUTION_AT_PREMIUM_HIGH' if (resp_recent is not None and resp_recent < 0)
                 else 'MATURE_SCALING_ACTIVITY')
    elif vp['distributed']:
        shape = 'DISTRIBUTED_BACKGROUND'
    elif vp['dominant'] > 0.85 and vp['burst'] < config.VP_BURST_PERSIST_MIN:
        shape = 'ISOLATED_PRINT'                   # one lone bar, no follow-through
    elif vp['compact'] and vp['burst'] >= config.VP_BURST_PERSIST_MIN:
        shape = 'PERSISTENT_COMPACT_WAVE'
    elif vp['compact']:
        shape = 'COMPACT_SHOCK'
    elif vp.get('skew', 0.0) <= -0.5 and vp['burst'] < config.VP_BURST_PERSIST_MIN:
        shape = 'STALE_OPENING_VOLUME'             # volume arrived early, gone quiet since
    else:
        shape = 'DISTRIBUTED_BACKGROUND'

    positive = resp_event >= config.RESP_EVENT_MIN and resp_recent > -0.10   # premium not making lower lows
    positive = positive or delayed          # a recovering shakeout with prior positive excursion qualifies

    # ── accumulation (tradeable) ──
    if shape in ('COMPACT_SHOCK', 'PERSISTENT_COMPACT_WAVE') and positive:
        if strike_class and 'CHAIN' in strike_class:
            label = 'COORDINATED_CHAIN_ACCUMULATION'
        elif strike_class and 'SINGLE' in strike_class:
            label = 'SINGLE_STRIKE_ACCUMULATION'
        elif shape == 'PERSISTENT_COMPACT_WAVE':
            label = 'PERSISTENT_ACCUMULATION'
        else:
            label = 'COMPACT_ACCUMULATION'
        return {'shape': shape, 'label': label, 'eligible': True, 'reason': 'ACCUMULATION'}

    # ── distribution / management-only ──
    if shape == 'EXHAUSTION_OR_EXIT_FLOW':
        label = 'HEAVY_VOLUME_NEGATIVE_RESPONSE'
    elif shape == 'DISTRIBUTION_AT_PREMIUM_HIGH':
        label = 'DISTRIBUTION_AT_HIGH'
    elif shape == 'MATURE_SCALING_ACTIVITY':
        label = 'MATURE_DISTRIBUTION'
    elif shape == 'STALE_OPENING_VOLUME':
        label = 'STALE_OPENING'
    elif shape == 'ISOLATED_PRINT':
        label = 'LATE_CHASING_ACTIVITY'
    elif not positive:
        label = 'HEAVY_VOLUME_NEGATIVE_RESPONSE'
    else:
        label = 'DISTRIBUTED_BACKGROUND'
    reason = ('NEGATIVE_PREMIUM_RESPONSE' if not positive else shape)
    return {'shape': shape, 'label': label, 'eligible': False, 'reason': reason}
