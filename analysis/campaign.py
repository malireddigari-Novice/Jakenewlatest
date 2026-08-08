"""
Campaign assessment (spec §14-15) — the single explicit question the engine asks.

The philosophical shift (§14): the engine must stop asking "did this strike exceed a threshold?"
and instead ask ONE question — *is this the beginning of a genuine institutional campaign while
convexity is still cheap?* This module turns the scattered gates into one first-class verdict.

It names the six campaign signals the detector exists to find (§15):
  1. WHERE capital is concentrating   — this ticker leads the Mag-7 fresh-premium pool
  2. dormant activity WAKING UP        — a statistical shock (dormant → abnormal)
  3. accumulation BEGINNING            — premium responding positively in a compact shape
  4. who CONTROLS the tape             — the trade side owns the majority of fresh premium
  5. still CHEAP convexity             — the contract is near its value low, not chased
(5→6: leadership TRANSFER and campaign ENDING are the *exit* side of the campaign, narrated by
`campaign_end()` and driven by the wave engine's rotation/control-transfer/exhaustion.)

`assess()` is the final entry verdict + the human thesis the engine logs and posts. A campaign
is CONFIRMED only when all five entry signals are present AND the combined conviction clears
CAMPAIGN_MIN_SCORE — precision over frequency (§1). The success metric is not alerts; it is the
few genuine campaigns caught while the options were still inexpensive.
"""
import config


def context_prior(ctx: dict) -> float:
    """
    Prior P(campaign) from context — morning bias, DTE, time-of-day, regime, liquidity. A
    neutral 0.5 when no context is supplied (the tests' path). The engine builds `ctx` per
    poll; the whole point is that each new minute UPDATES this prior rather than resetting it.
    """
    if not ctx:
        return 0.5
    p = float(ctx.get('prior', 0.5))
    return min(0.95, max(0.05, p))


def posterior(signals: dict, ctx: dict = None, spot_confirms=None) -> float:
    """
    HEURISTIC POSTERIOR PROXY (uncalibrated) — a Bayesian-INSPIRED score, not a calibrated
    probability: prior odds from context × a likelihood ratio per observed signal (present →
    LR_pos, absent → LR_neg). Each signal multiplies the odds rather than adding a weighted term.
    Until `analysis.calibration` demonstrates reliability (Brier / log-loss / ECE / decile
    monotonicity, in and out of sample), treat the output as a rank-ish proxy and the
    CAMPAIGN_MIN_POSTERIOR threshold as a heuristic knob with no rigorous probabilistic meaning
    (spec §46-47). Returns 1.0 when the path is disabled (gate always passes).
    """
    if not config.CAMPAIGN_BAYES_ENABLED:
        return 1.0
    p0 = context_prior(ctx)
    odds = p0 / (1.0 - p0)
    for key, (lp, ln) in (('leadership', config.LR_LEADERSHIP), ('waking', config.LR_WAKING),
                          ('accumulation', config.LR_ACCUMULATION), ('control', config.LR_CONTROL),
                          ('cheap', config.LR_CHEAP)):
        odds *= lp if signals.get(key) else ln
    if spot_confirms is not None:                      # optional 6th signal (dS/dt confirmation)
        lp, ln = config.LR_SPOT
        odds *= lp if spot_confirms else ln
    return round(odds / (1.0 + odds), 4)


def expected_value(p_continue, remaining_convexity, p_false, expected_loss) -> float:
    """
    EV = P(continue)·RemainingConvexity − P(false)·ExpectedLoss. The optimal entry is not
    maximum confirmation — as the engine waits, P(continue) rises but RemainingConvexity
    falls. Enter at the earliest moment this is positive (spec: earliest positive asymmetry).
    """
    return round((p_continue or 0.0) * (remaining_convexity or 0.0)
                 - (p_false or 0.0) * (expected_loss or 0.0), 4)


def early_accumulation_score(metric: dict, cand: dict) -> float:
    """EarlyAccumulationScore (0-100, spec §15) — a SEPARATE early-phase score, deliberately not
    the same as mature campaign confidence/posterior. It is optimised for the earliest favorable
    phase: fresh-premium velocity, abnormal participation, value proximity (low extension),
    emerging one-sided control, a firming/recovering premium response, and low distribution
    evidence. It is computed and logged for research; it never gates an entry on its own."""
    if not metric or not cand:
        return 0.0
    side = cand.get('side')
    z = metric.get('mass_z', 0.0) or 0.0
    impulse = metric.get('impulse', 1.0) or 1.0
    vel = metric.get('velocity', 0.0) or 0.0
    ctrl = metric.get('call_control', 0.0) if side == 'CALL' else metric.get('put_control', 0.0)
    dist = cand.get('dist_low', 9.9)
    resp = cand.get('resp_event', 0.0) or 0.0
    shakeout = cand.get('shakeout', 0.0) or 0.0
    dist_prob = cand.get('dist_prob', 0.0) or 0.0

    s_freshvel = _clamp(0.5 * (impulse - 1.0) + (0.5 if vel > 0 else 0.0))
    s_part = _clamp(z / 5.0)
    s_value = (_clamp(1.0 - (dist - 1.0) / max(config.GATE_MAX_DIST_FROM_LOW - 1.0, 1e-9))
               if dist >= 1 else 1.0)
    s_ctrl = _clamp((ctrl - 0.5) * 2.0)
    s_resp = _clamp(max(0.5 + resp * 2.0, shakeout))
    s_nodist = _clamp(1.0 - dist_prob)
    score = 100.0 * (config.EAS_W_FRESHVEL * s_freshvel + config.EAS_W_PARTICIPATION * s_part
                     + config.EAS_W_VALUE * s_value + config.EAS_W_CONTROL * s_ctrl
                     + config.EAS_W_RESPONSE * s_resp + config.EAS_W_NODIST * s_nodist)
    return round(score, 1)


def assess(metric: dict, cand: dict, ctx: dict = None) -> dict:
    """
    metric: the ranked per-ticker row (attention_share, mass_z, rank, call/put_control...).
    cand:   the entry candidate (side, accumulation, dist_low, resp_event, acc_label, shape,
            spot_confirms...).
    ctx:    optional context for the Bayesian prior (prior, dte, minutes_open, regime).
    Returns {confirmed, score, posterior, thesis, signals, missing}.
    """
    side = cand.get('side')
    share = metric.get('attention_share', 0.0)
    z = metric.get('mass_z', 0.0)
    ctrl = metric.get('call_control', 0.0) if side == 'CALL' else metric.get('put_control', 0.0)
    dist = cand.get('dist_low', 9.9)
    resp = cand.get('resp_event', 0.0) or 0.0

    # ── the five entry signals (present / absent) ──
    leadership = metric.get('rank') == 1 and share >= config.WAVE_LEAD_SHARE
    waking = z >= config.CAMPAIGN_WAKE_Z
    accumulation = bool(cand.get('accumulation'))
    control = ctrl >= config.CAMPAIGN_CONTROL_MIN
    cheap = dist <= config.GATE_MAX_DIST_FROM_LOW
    signals = {'leadership': leadership, 'waking': waking, 'accumulation': accumulation,
               'control': control, 'cheap': cheap}
    missing = [k for k, ok in signals.items() if not ok]

    # ── conviction score (0-100), a blend of how STRONGLY each signal holds ──
    s_lead = _clamp(share / 0.60)
    s_wake = _clamp(z / 5.0)
    s_accum = _clamp(0.5 + resp * 2.0) if accumulation else 0.0     # positive premium response lifts it
    s_ctrl = _clamp((ctrl - 0.5) * 2.0)
    s_cheap = _clamp(1.0 - (dist - 1.0) / max(config.GATE_MAX_DIST_FROM_LOW - 1.0, 1e-9)) if dist >= 1 else 1.0
    score = 100.0 * (config.CW_LEADERSHIP * s_lead + config.CW_WAKING * s_wake
                     + config.CW_ACCUMULATION * s_accum + config.CW_CONTROL * s_ctrl
                     + config.CW_CHEAP * s_cheap)

    # Bayesian posterior — the probabilistic complement to the linear score. Entry requires
    # BOTH the linear conviction AND a posterior clearing CAMPAIGN_MIN_POSTERIOR.
    post = posterior(signals, ctx, cand.get('spot_confirms'))
    confirmed = ((not missing) and score >= config.CAMPAIGN_MIN_SCORE
                 and post >= config.CAMPAIGN_MIN_POSTERIOR)

    thesis = _thesis(cand.get('symbol') or metric.get('symbol'), side, share, z, ctrl, dist, resp,
                     cand.get('acc_label'), confirmed, missing)
    return {'confirmed': confirmed, 'score': round(score, 1), 'posterior': post, 'thesis': thesis,
            'signals': signals, 'missing': missing}


def _thesis(sym, side, share, z, ctrl, dist, resp, acc_label, confirmed, missing) -> str:
    verb = 'calls' if side == 'CALL' else 'puts'
    parts = [f"{sym} {verb} lead the Mag-7 ({100*share:.0f}% of fresh premium)",
             f"dormant flow woke (z={z:.1f})",
             f"accumulation begun (resp {100*resp:+.0f}%, {acc_label or 'n/a'})",
             f"{verb} control the tape ({ctrl:.2f})",
             f"still cheap ({dist:.2f}x low)"]
    head = "CAMPAIGN CONFIRMED" if confirmed else f"NOT A CAMPAIGN (missing: {','.join(missing) or 'score'})"
    return f"{head} — " + "; ".join(parts)


# Map an exit reason to the campaign's manner of death (§15: "when the campaign is ending").
_END = {
    'STRUCTURAL_TP1': 'objective — banked first slice',
    'STRUCTURAL_TP2': 'objective — profit target reached',
    'TRAIL_GIVEBACK': 'objective — trailing stop protected the run',
    'STOP_LOSS':      'risk — hard stop',
    'EOD_FLATTEN':    'objective — end of day',
    'CONTROL_TRANSFER':          'thesis dead — control transferred to the other side',
    'CONTROL_FLIP_OVERWHELMING': 'thesis dead — control seized by the other side',
    'ROTATION':                  'thesis dead — attention rotated to a stronger campaign',
    'STATISTICAL_EXHAUSTION':    'thesis dead — campaign statistically exhausted',
    'DISTRIBUTION_EXIT':         'distribution — coherent exit flow closed the runner',
    'RUNNER_TRAIL':              'objective — runner trailing stop protected the extended run',
    # Follow-up §20 — campaign-confidence exit labels (CampaignConfidence eroded below threshold)
    'VERIFIED_DISTRIBUTION':               'thesis dead — verified distribution',
    'PERSISTENT_CONTROL_TRANSFER':         'thesis dead — control persistently transferred',
    'OPPOSITE_SIDE_CAMPAIGN_CONFIRMED':    'thesis dead — opposite-side campaign confirmed',
    'ROTATION_WITH_CURRENT_CAMPAIGN_FAILURE': 'thesis dead — rotation AND the current campaign failed',
    'PREMIUM_STRUCTURE_FAILURE':           'thesis dead — premium structure broke',
    'RESILIENCE_FAILURE':                  'thesis dead — campaign resilience collapsed',
    'TRUE_MULTI_VARIABLE_EXHAUSTION':      'thesis dead — genuine multi-variable exhaustion',
    'REVERSAL_ACTIVATED':                  'reversed — a confirmed opposite-side campaign took over',
}


def campaign_end(reason: str) -> str:
    return _END.get(reason, reason)


# Exit taxonomy (spec §33-36, §40) — group each exit reason into WHY the campaign was left, so exit
# quality can be analysed by cause (objective vs thesis-death vs risk vs distribution).
_EXIT_CATEGORY = {
    'STRUCTURAL_TP1': 'OBJECTIVE', 'STRUCTURAL_TP2': 'OBJECTIVE', 'TRAIL_GIVEBACK': 'OBJECTIVE',
    'RUNNER_TRAIL': 'OBJECTIVE', 'EOD_FLATTEN': 'EOD', 'STOP_LOSS': 'RISK_STOP',
    'CONTROL_TRANSFER': 'CONTROL_TRANSFER', 'CONTROL_FLIP_OVERWHELMING': 'CONTROL_TRANSFER',
    'ROTATION': 'THESIS_DEATH', 'STATISTICAL_EXHAUSTION': 'THESIS_DEATH',
    'DISTRIBUTION_EXIT': 'DISTRIBUTION', 'DISTRIBUTION_REDUCE': 'DISTRIBUTION',
    # Follow-up §20 confidence-exit labels
    'VERIFIED_DISTRIBUTION': 'DISTRIBUTION',
    'PERSISTENT_CONTROL_TRANSFER': 'CONTROL_TRANSFER',
    'OPPOSITE_SIDE_CAMPAIGN_CONFIRMED': 'CONTROL_TRANSFER',
    'REVERSAL_ACTIVATED': 'REVERSAL',
    'ROTATION_WITH_CURRENT_CAMPAIGN_FAILURE': 'THESIS_DEATH',
    'PREMIUM_STRUCTURE_FAILURE': 'THESIS_DEATH',
    'RESILIENCE_FAILURE': 'THESIS_DEATH',
    'TRUE_MULTI_VARIABLE_EXHAUSTION': 'THESIS_DEATH',
}


def exit_category(reason: str) -> str:
    return _EXIT_CATEGORY.get(reason, 'OTHER')


# Which decision path OWNED the exit (for precedence auditing — was it the new hold engine or a
# legacy/structural rule?). The confidence hold-engine labels are §20; legacy wave labels are the
# old rotation/exhaustion/control-transfer; the rest are risk/objective/EOD/overwhelming.
_CONFIDENCE_EXITS = {'VERIFIED_DISTRIBUTION', 'PERSISTENT_CONTROL_TRANSFER',
                     'OPPOSITE_SIDE_CAMPAIGN_CONFIRMED', 'ROTATION_WITH_CURRENT_CAMPAIGN_FAILURE',
                     'PREMIUM_STRUCTURE_FAILURE', 'RESILIENCE_FAILURE', 'TRUE_MULTI_VARIABLE_EXHAUSTION'}
_LEGACY_EXITS = {'ROTATION', 'STATISTICAL_EXHAUSTION', 'CONTROL_TRANSFER'}


def decision_path(reason: str) -> str:
    if reason == 'REVERSAL_ACTIVATED':
        return 'REVERSAL_CLUSTER'
    if reason in _CONFIDENCE_EXITS:
        return 'CAMPAIGN_CONFIDENCE'
    if reason in _LEGACY_EXITS:
        return 'LEGACY_WAVE'
    if reason == 'CONTROL_FLIP_OVERWHELMING':
        return 'OVERWHELMING_FLIP'
    if reason == 'STOP_LOSS':
        return 'RISK_STOP'
    if reason == 'EOD_FLATTEN':
        return 'EOD'
    return 'STRUCTURAL_OBJECTIVE'


# Rejection taxonomy (follow-up §19) — WHY an entry candidate did not become a trade. Distinguishes
# a disciplined/valid rejection from a model failure worth researching as a false negative.
_VALID_REJECTS = {'ECONOMICALLY_VALID_REJECTION', 'DATA_QUALITY_REJECTION', 'MISSED_DUE_TO_CAPACITY'}
_MODEL_MISSES = {
    'MISSED_DUE_TO_DETECTION_LATENCY', 'MISSED_DUE_TO_PRICE_EXTENSION',
    'MISSED_DUE_TO_SINGLE_STRIKE_NOTIONAL', 'MISSED_DUE_TO_CLUSTER_AGGREGATION',
    'MISSED_DUE_TO_TICKER_AGGREGATION', 'MISSED_DUE_TO_OPENING_GATE',
    'MISSED_DUE_TO_CONTROL_CONFIRMATION', 'MISSED_DUE_TO_RANK_REQUIREMENT',
    'MISSED_DUE_TO_PERSISTENCE_LOGIC', 'MISSED_DUE_TO_ARCHETYPE_MISCLASSIFICATION',
    'MISSED_DUE_TO_POSTERIOR_GATE', 'MISSED_DUE_TO_EV_GATE',
}


def reject_is_model_miss(label: str) -> bool:
    """True if the rejection is a candidate false-negative worth researching (§19), not a
    disciplined/valid rejection (economically-invalid, bad data, or an accepted capacity limit)."""
    return label in _MODEL_MISSES


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))
