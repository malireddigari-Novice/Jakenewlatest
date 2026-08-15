"""
Qualified directional control (new-spec 8/11, NVDA 220C-vs-220P) — pure, I/O-free.

Side control must NOT be decided by raw fresh call-mass vs put-mass. The NVDA case: the 220C owned
the larger raw call pool, but its volume was sustained/DISTRIBUTED while premium bled steadily lower
(HEAVY_VOLUME_NEGATIVE_RESPONSE) — low-information background / systematic selling, not bullish
accumulation. The 220P carried the senior event: a compact abnormal burst with premium EXPANSION.

Principle: the cleanest informational event should be able to overpower the largest raw pool. So each
side's raw mass is multiplied by a 0..~1.2 QUALITY factor derived from —
  • event SHAPE       : DISTRIBUTED / THIN flow is heavily discounted vs a concentrated single-strike
                        or coordinated-chain event;
  • premium ACCEPTANCE: REJECTION (heavy volume, lower lows — premium bleed) is heavily discounted;
                        ABSORPTION (premium holding under volume) is boosted;
  • FRESHNESS         : a positive fresh-abnormality Z lifts it; a decelerating side (stale / no
                        longer fresh) is discounted (BackgroundFlowAdaptation).
— and the dominant side is re-derived from QualifiedCallMass / QualifiedPutMass. A smaller but
high-information opposite event can now outrank a much larger low-information pool.
"""
import config

_GOOD_SHAPES = ('SINGLE_STRIKE_DOMINANT', 'COORDINATED_CHAIN')


def side_quality(side_class, acceptance, z, acceleration) -> float:
    """0..~1.2 quality multiplier for one side's directional mass.
    side_class : the side's _side_quality classification (SINGLE_STRIKE_DOMINANT / COORDINATED_CHAIN /
                 DISTRIBUTED / THIN).
    acceptance : premium-acceptance label on the side's representative contract (ABSORPTION / REJECTION
                 / NEUTRAL / None).
    z          : the side's fresh-mass abnormality (call_z / put_z).
    acceleration : the side's fresh-mass acceleration (call/put) — <0 = decelerating / stale."""
    cls = (1.0 if side_class in _GOOD_SHAPES
           else config.QC_DISTRIBUTED_FACTOR if side_class == 'DISTRIBUTED'
           else config.QC_THIN_FACTOR)
    acc = {'REJECTION': config.QC_REJECT_FACTOR,
           'ABSORPTION': config.QC_ABSORB_BOOST}.get(acceptance, 1.0)
    fresh = 1.0 if (acceleration or 0.0) >= 0 else config.QC_STALE_FACTOR
    zb = 1.0 + config.QC_Z_BOOST * max(0.0, min(1.0, (z or 0.0) / config.QC_Z_REF))
    return round(max(0.0, cls * acc * fresh * zb), 4)


def qualified_control(call_mass, put_mass, call_q, put_q) -> dict:
    """Re-derive the dominant side from quality-weighted mass. Returns the qualified masses, the
    dominant side, qualified control shares, and whether qualification FLIPPED the raw-mass winner."""
    qcm = max(0.0, call_mass or 0.0) * (call_q or 0.0)
    qpm = max(0.0, put_mass or 0.0) * (put_q or 0.0)
    tot = qcm + qpm
    if tot <= 0:
        return {'q_call_mass': 0.0, 'q_put_mass': 0.0, 'dominant_side': None,
                'q_call_control': 0.0, 'q_put_control': 0.0, 'flipped_from_raw': False}
    dom = 'CALL' if qcm >= qpm else 'PUT'
    raw_dom = 'CALL' if (call_mass or 0.0) >= (put_mass or 0.0) else 'PUT'
    return {'q_call_mass': round(qcm), 'q_put_mass': round(qpm), 'dominant_side': dom,
            'q_call_control': round(qcm / tot, 3), 'q_put_control': round(qpm / tot, 3),
            'flipped_from_raw': dom != raw_dom}
