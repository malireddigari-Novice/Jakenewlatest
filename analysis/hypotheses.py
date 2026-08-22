"""
Multi-hypothesis engine (addendum #9) — pure, I/O-free.

Do not force every event into BUY or SELL. Maintain competing hypotheses and let evidence move their
probabilities; ambiguity should PERSIST until evidence resolves it (that is itself a reason to PASS).

  H1 FRESH_DIRECTIONAL   — fresh opening conviction (the trade we actually want)
  H2 CLOSING_PROFITABLE  — closing inventory bought lower (unwind into strength)
  H3 CLOSING_LOSING      — closing inventory bought higher (capitulation / stop)
  H4 OVERWRITE           — systematic premium sale / covered writing
  H5 ROLL                — rolling an existing position (strike/expiry)
  H6 SPREAD_LEG          — one leg of a multi-leg package
  H7 HEDGE               — convexity/vol demand, not a directional stock bet
  H8 UNKNOWN             — no hypothesis dominates

This is a light evidence-weighted scheme (not full Bayes): start from a flat-ish prior and apply
multiplicative evidence from the reads the engine already computes (premium acceptance, response,
inventory ambiguity, package label, hedge read, self-sustainability). Normalised to a distribution.
"""
import config

H = ('FRESH_DIRECTIONAL', 'CLOSING_PROFITABLE', 'CLOSING_LOSING', 'OVERWRITE',
     'ROLL', 'SPREAD_LEG', 'HEDGE', 'UNKNOWN')


def assess(evidence: dict) -> dict:
    """evidence keys (all optional; missing = neutral):
        acceptance   : 'ABSORPTION'/'REJECTION'/'NEUTRAL'  (premium acceptance on the event)
        resp_event   : premium response since the event (fraction)
        self_sust    : 0..1 self-sustainability
        inv_ambiguity: 'LOW'/'MED'/'HIGH'  inv_state: inventory state
        package      : package label ('VERTICAL_LIKELY'/'ROLL_LIKELY'/'OUTRIGHT_LIKELY'/…)
        hedge        : 'CONVEXITY'/'DIRECTIONAL'/'NEUTRAL'
        drift        : current premium / basis (rel_premium)
    Returns {probs: {H: p}, top, top_p, directional_p, ambiguous(bool), reason}."""
    w = {h: 1.0 for h in H}
    acc = evidence.get('acceptance')
    resp = evidence.get('resp_event') or 0.0
    sust = evidence.get('self_sust') or 0.0
    amb = evidence.get('inv_ambiguity')
    inv_state = evidence.get('inv_state') or ''
    pkg = evidence.get('package') or 'OUTRIGHT_LIKELY'
    hedge = evidence.get('hedge')
    drift = evidence.get('drift')

    # premium ACCEPTANCE + positive response + self-sustaining → fresh directional accumulation
    if acc == 'ABSORPTION':
        w['FRESH_DIRECTIONAL'] *= 1.8
        w['CLOSING_LOSING'] *= 0.6
    if acc == 'REJECTION':
        w['FRESH_DIRECTIONAL'] *= 0.5
        w['OVERWRITE'] *= 1.6
        w['CLOSING_PROFITABLE'] *= 1.3
    if resp > 0.05:
        w['FRESH_DIRECTIONAL'] *= 1.4
    elif resp < -0.05:
        w['CLOSING_LOSING'] *= 1.5
        w['FRESH_DIRECTIONAL'] *= 0.7
    if sust >= 0.5:
        w['FRESH_DIRECTIONAL'] *= 1.3

    # inventory ambiguity → closing/unwind hypotheses rise
    if amb == 'HIGH':
        w['FRESH_DIRECTIONAL'] *= 0.4
        if 'PARTIAL_EXIT' in inv_state:
            w['CLOSING_PROFITABLE'] *= 1.8
            w['OVERWRITE'] *= 1.3
    elif amb == 'MED':
        w['FRESH_DIRECTIONAL'] *= 0.8
        w['CLOSING_PROFITABLE'] *= 1.2

    # package → roll / spread hypotheses
    if pkg == 'ROLL_LIKELY':
        w['ROLL'] *= 3.0
        w['FRESH_DIRECTIONAL'] *= 0.5
    elif pkg in ('VERTICAL_LIKELY', 'RATIO_LIKELY'):
        w['SPREAD_LEG'] *= 2.5
        w['FRESH_DIRECTIONAL'] *= 0.7
    elif pkg == 'STRADDLE_COMBO_LIKELY':
        w['HEDGE'] *= 2.2
        w['FRESH_DIRECTIONAL'] *= 0.7

    # hedge/convexity read
    if hedge == 'CONVEXITY':
        w['HEDGE'] *= 2.0
        w['FRESH_DIRECTIONAL'] *= 0.8
    elif hedge == 'DIRECTIONAL':
        w['FRESH_DIRECTIONAL'] *= 1.3

    # premium far above basis with rejection → distribution/overwrite, not fresh
    if drift is not None and drift > 1.5 and acc == 'REJECTION':
        w['CLOSING_PROFITABLE'] *= 1.4
        w['OVERWRITE'] *= 1.3

    total = sum(w.values()) or 1.0
    probs = {h: round(w[h] / total, 3) for h in H}
    # UNKNOWN absorbs residual uncertainty: if nothing separated, it stays ~flat and can top out.
    top = max(probs, key=probs.get)
    top_p = probs[top]
    dir_p = probs['FRESH_DIRECTIONAL']
    # 2026-08-22 recalibration for the 8-way split: an absolute top-prob bar (0.35) is unreachable in
    # an 8-way distribution, so it abstained on ~everything. For a DIRECTIONAL entry the gate should
    # abstain only when the intent reads NON-directional — a roll / spread-leg / hedge / closing
    # hypothesis clearly LEADS fresh-directional (by HYP_ABSTAIN_MARGIN) — or when UNKNOWN dominates.
    # When FRESH_DIRECTIONAL is the leading interpretation (even at a modest 8-way prob), it is NOT
    # ambiguous for the purpose of a directional trade. Every non-directional family is a reason to pass.
    non_directional_lead = (top != 'FRESH_DIRECTIONAL' and top != 'UNKNOWN'
                            and (top_p - dir_p) >= config.HYP_ABSTAIN_MARGIN)
    ambiguous = (top == 'UNKNOWN') or non_directional_lead
    return {'probs': probs, 'top': top, 'top_p': top_p, 'directional_p': dir_p,
            'ambiguous': ambiguous, 'abstain_cause': ('UNKNOWN' if top == 'UNKNOWN'
                          else top if non_directional_lead else None),
            'reason': f'{top} p={top_p:.2f} (directional={dir_p:.2f})'
                      + (f' — non-directional lead {top}' if non_directional_lead else '')}
