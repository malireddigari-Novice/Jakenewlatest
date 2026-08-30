"""
Absolute entry-quality gate (handoff Priority 1) — pure, I/O-free.

The recurring failure across every case study: the engine entered on a weak ABSOLUTE signal merely
because the ticker ranked #1 (AAPL score 49 / dominance 0.57 / 6% share; MSFT dominance 0.54; META
score 42). Rank tells the engine WHERE to investigate; it must NOT authorize a trade. Authorization
requires the signal to clear absolute floors regardless of rank:

  • attention_score >= ABS_MIN_SCORE        (a rank-#1 ticker on a quiet day still fails)
  • directional dominance >= ABS_MIN_DOMINANCE (a 0.54-0.57 read is a LEAN, not CONTROL)

A signal that fails is not an entry — it is a WATCH (weak absolute → observe, don't buy). Calibrated
to the case studies: passes NVDA (94/0.73) and TSLA (75/CALL-control), blocks META (42), MSFT (0.54)
and AAPL (49/0.57) — the three that lost money.
"""
import config


def lean(dominance) -> str:
    """CONTROL / WEAK_LEAN / BALANCED from directional dominance (0-1). A 0.54-0.57 read is a LEAN, not
    control — the NVDA-0.55 / MSFT-0.54 / AAPL-0.57 correction."""
    d = 0.5 if dominance is None else dominance
    if d >= config.ABS_MIN_DOMINANCE:
        return 'CONTROL'
    if d >= 0.5:
        return 'WEAK_LEAN'
    return 'BALANCED'


def authorize(score, dominance) -> dict:
    """Absolute-quality authorization, rank-INDEPENDENT. Returns {authorized, lean, reasons, verdict}.
    verdict: AUTHORIZED_ENTRY / WATCH_WEAK_ABSOLUTE."""
    if not config.ABS_GATE_ENABLED:
        return {'authorized': True, 'lean': lean(dominance), 'reasons': [], 'verdict': 'GATE_DISABLED'}
    d = 0.5 if dominance is None else dominance
    reasons = []
    if (score or 0.0) < config.ABS_MIN_SCORE:
        reasons.append(f'score {score or 0:.0f} < {config.ABS_MIN_SCORE:.0f}')
    if d < config.ABS_MIN_DOMINANCE:
        reasons.append(f'dominance {d:.2f} < {config.ABS_MIN_DOMINANCE:.2f} ({lean(d)})')
    ok = not reasons
    return {'authorized': ok, 'lean': lean(d), 'reasons': reasons,
            'verdict': 'AUTHORIZED_ENTRY' if ok else 'WATCH_WEAK_ABSOLUTE'}
