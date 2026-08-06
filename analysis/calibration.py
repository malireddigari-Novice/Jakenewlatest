"""
Probability calibration (spec §46-47) — pure functions + an archive report.

The engine computes a "posterior" and gates on it (CAMPAIGN_MIN_POSTERIOR = 0.55), and blends a
continuation probability into expected value. Calling any of that "Bayesian" is only honest if the
numbers are CALIBRATED — i.e. among candidates the model says have a 0.6 chance of continuing, ~60%
actually do. Until that is demonstrated the outputs are a *heuristic posterior proxy*, and a 0.55
threshold has no rigorous probabilistic meaning.

This module measures calibration from the P6 candidate archive:
  • Brier score and log loss (lower = better),
  • a reliability curve + Expected Calibration Error (ECE),
  • a decile table (predicted-probability decile → realized continuation rate),
and can slice by ticker / DTE / archetype / decision for stability checks. Feed it (prob, outcome)
pairs, or let `pairs_from_archive` build them by matching each ENTERED record to its EXIT outcome.

Run:  python -m analysis.calibration   (reads config.RESEARCH_ARCHIVE_FILE)
"""
import math

import config


def _clip(p):
    return max(1e-6, min(1.0 - 1e-6, float(p)))


def brier_score(pairs) -> float:
    """Mean squared error between predicted probability and 0/1 outcome. 0 = perfect."""
    if not pairs:
        return float('nan')
    return round(sum((p - y) ** 2 for p, y in pairs) / len(pairs), 4)


def log_loss(pairs) -> float:
    """Mean negative log-likelihood. Punishes confident-and-wrong harder than Brier."""
    if not pairs:
        return float('nan')
    return round(-sum(y * math.log(_clip(p)) + (1 - y) * math.log(1 - _clip(p))
                      for p, y in pairs) / len(pairs), 4)


def base_rate(pairs) -> float:
    return round(sum(y for _, y in pairs) / len(pairs), 4) if pairs else float('nan')


def reliability_curve(pairs, bins: int = 10) -> list:
    """Per-bin {lo, hi, n, mean_pred, frac_pos} — the calibration plot as data. A well-calibrated
    model has mean_pred ≈ frac_pos in every populated bin."""
    out = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = [(p, y) for p, y in pairs if (lo <= p < hi or (b == bins - 1 and p == 1.0))]
        if sel:
            out.append({'lo': round(lo, 2), 'hi': round(hi, 2), 'n': len(sel),
                        'mean_pred': round(sum(p for p, _ in sel) / len(sel), 4),
                        'frac_pos': round(sum(y for _, y in sel) / len(sel), 4)})
        else:
            out.append({'lo': round(lo, 2), 'hi': round(hi, 2), 'n': 0,
                        'mean_pred': None, 'frac_pos': None})
    return out


def ece(pairs, bins: int = 10) -> float:
    """Expected Calibration Error — n-weighted mean |mean_pred − frac_pos| across bins. 0 = perfect."""
    if not pairs:
        return float('nan')
    total, acc = len(pairs), 0.0
    for row in reliability_curve(pairs, bins):
        if row['n']:
            acc += row['n'] / total * abs(row['mean_pred'] - row['frac_pos'])
    return round(acc, 4)


def decile_table(pairs) -> list:
    """Predicted-probability deciles → realized continuation rate. Monotonically rising realized
    rates across deciles is the minimum sign the score ranks risk correctly."""
    if not pairs:
        return []
    s = sorted(pairs, key=lambda x: x[0])
    n = len(s)
    out = []
    for d in range(10):
        chunk = s[d * n // 10:(d + 1) * n // 10]
        if chunk:
            out.append({'decile': d + 1, 'n': len(chunk),
                        'mean_pred': round(sum(p for p, _ in chunk) / len(chunk), 4),
                        'realized': round(sum(y for _, y in chunk) / len(chunk), 4)})
    return out


def report(pairs, bins: int = 10) -> dict:
    """Full calibration report for a set of (prob, outcome) pairs."""
    return {'n': len(pairs), 'base_rate': base_rate(pairs), 'brier': brier_score(pairs),
            'log_loss': log_loss(pairs), 'ece': ece(pairs, bins),
            'reliability': reliability_curve(pairs, bins), 'deciles': decile_table(pairs)}


def pairs_from_archive(records, prob_key: str = 'cont_prob', win_threshold: float = 0.0):
    """Build (predicted_prob, outcome) pairs by matching each ENTERED record to its next EXIT for
    the same (symbol, side). Outcome = the trade's P&L beat `win_threshold` (a proxy for the
    campaign continuing after entry). Returns (pairs, skipped) where skipped lacked a probability."""
    pending, pairs, skipped = {}, [], 0
    for r in records:
        key = (r.get('symbol'), r.get('side'))
        if r.get('decision') == 'ENTERED':
            pending[key] = r
        elif r.get('decision') == 'EXIT' and key in pending:
            ent = pending.pop(key)
            prob = ent.get(prob_key)
            if prob is None:
                skipped += 1
                continue
            pairs.append((_clip(prob), 1 if (r.get('pnl') or 0.0) > win_threshold else 0))
    return pairs, skipped


def slice_reports(records, by: str = 'archetype', prob_key: str = 'cont_prob') -> dict:
    """Calibration report per slice value (archetype / dte / symbol) for stability checks."""
    groups = {}
    pending = {}
    for r in records:
        key = (r.get('symbol'), r.get('side'))
        if r.get('decision') == 'ENTERED':
            pending[key] = r
        elif r.get('decision') == 'EXIT' and key in pending:
            ent = pending.pop(key)
            prob = ent.get(prob_key)
            if prob is None:
                continue
            g = ent.get(by) or r.get(by) or 'UNKNOWN'
            groups.setdefault(g, []).append((_clip(prob), 1 if (r.get('pnl') or 0.0) > 0 else 0))
    return {g: report(p) for g, p in groups.items()}


if __name__ == '__main__':
    from analysis.replay import ResearchArchive
    recs = ResearchArchive(config.RESEARCH_ARCHIVE_FILE).load()
    prs, skipped = pairs_from_archive(recs)
    rep = report(prs)
    print(f"Calibration over {config.RESEARCH_ARCHIVE_FILE}: {rep['n']} matched entries "
          f"({skipped} without a probability)")
    if rep['n']:
        print(f"  base rate={rep['base_rate']}  Brier={rep['brier']}  logloss={rep['log_loss']}  "
              f"ECE={rep['ece']}")
        print("  decile  n   mean_pred  realized")
        for d in rep['deciles']:
            print(f"    {d['decile']:>2}  {d['n']:>3}   {d['mean_pred']:>8}  {d['realized']:>8}")
    else:
        print("  (no matched ENTERED→EXIT pairs yet — enable RESEARCH_ARCHIVE_ENABLED and let it run)")
