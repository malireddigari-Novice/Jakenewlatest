"""
Rotation resolver (spec §23-24) — pure, I/O-free.

When a position exits because attention *rotated* away, the engine should not fall back to the generic
entry queue — it should ask WHERE the attention went and hand the entry engine that destination to
interrogate on the same poll (AAPL deteriorates → TSLA accelerates → investigate TSLA's surface now).
The attention jump alone never trades; it only *directs investigation* — the destination still has to
pass every normal gate (event morphology, qualified control, campaign verdict).

RotationCandidate ≈ argmax_i( Δattention_i + event-shape_i + directional-control_i ), excluding the
ticker we just left. Returns the best destination (or None) with its component scores for the log.
"""
import config


def _shape_score(cand) -> float:
    """0..1 event-shape quality for a ticker's current candidate read (barshock event + surface)."""
    if not cand:
        return 0.0
    bs = cand.get('barshock') or {}
    surf = cand.get('surface') or {}
    s = 0.0
    if bs.get('significant'):
        s += 0.5
    et = bs.get('event_type') or ''
    if 'CONCENTRATED' in et or 'COORDINATED' in et or 'CLUSTER' in et:
        s += 0.3
    if (surf.get('breadth') or 0) >= 2:
        s += 0.2
    return min(1.0, s)


def resolve(exited_ticker, ranked, prev_scores, cand_by, metrics_by) -> dict:
    """Pick the rotation destination among currently-ranked tickers (≠ the one we left).
    ranked       : this poll's ranked attention rows (each has symbol, attention_score, dominant_side).
    prev_scores  : {symbol: attention_score} from the previous poll (for Δattention / velocity).
    cand_by      : {symbol: candidate read}   metrics_by: {symbol: metric row}.
    Returns {'ticker','side','delta','shape','control','score','reason'} or {'ticker': None}."""
    best = None
    for r in ranked:
        sym = r['symbol']
        if sym == exited_ticker:
            continue
        side = r.get('dominant_side')
        if not side:
            continue
        delta = r['attention_score'] - (prev_scores.get(sym) or r['attention_score'])
        if delta < config.ROT_MIN_DELTA_SCORE:
            continue                              # not actually accelerating — not a rotation destination
        shape = _shape_score(cand_by.get(sym))
        control = r.get('call_control', 0.0) if side == 'CALL' else r.get('put_control', 0.0)
        score = (config.ROT_W_DELTA * min(1.0, delta / 40.0)
                 + config.ROT_W_SHAPE * shape
                 + config.ROT_W_CONTROL * control)
        if best is None or score > best['score']:
            best = {'ticker': sym, 'side': side, 'delta': round(delta, 1), 'shape': round(shape, 2),
                    'control': round(control, 2), 'score': round(score, 3),
                    'reason': f'attention +{delta:.0f} into {sym} {side} (shape={shape:.2f} ctrl={control:.2f})'}
    return best or {'ticker': None, 'reason': 'no accelerating destination'}
