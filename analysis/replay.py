"""
Campaign replay + candidate archive + missed-event diagnostics (spec §41-45).

Development cannot depend on hand-picked screenshots and hindsight. For every candidate — including
rejected ones — the engine should archive a structured, poll-by-poll record (the §46 field set,
subject to what is currently computable), so a campaign can be reconstructed minute-by-minute and
a missed winner (AMZN, the earlier NVDA setup) can be turned into a reproducible diagnostic:
did the ticker ever rank top-1/2/3? did any expiry/strike qualify? was it rejected for a specific
gate, or genuinely invisible?

`candidate_record()` and `diagnose_missed()` are pure. `ResearchArchive` is a thin JSONL appender.
Gated by RESEARCH_ARCHIVE_ENABLED (default OFF): when off the engine never constructs or writes a
record, so there is zero effect on live behaviour and no disk I/O.
"""
import json
from collections import Counter


def _iso(ts):
    return ts.isoformat() if hasattr(ts, 'isoformat') else ts


def candidate_record(now, sym, side, metric, cand, wave_state, decision, reason=None,
                     extra=None) -> dict:
    """One archive row for a (ticker, side) candidate at this poll. `decision` is one of
    OBSERVED / WATCH / BUILDING / ENTERED / REJECTED / EXIT; `reason` carries the reject/exit cause.
    Tolerant of missing keys (the backtest carries no IV, etc.)."""
    m = metric or {}
    c = cand or {}
    best = c.get('best') or {}
    rec = {
        'ts': _iso(now), 'symbol': sym, 'side': side, 'wave_state': wave_state,
        'decision': decision, 'reason': reason,
        # attention / abnormality
        'rank': m.get('rank'), 'attention_score': m.get('attention_score'),
        'attention_share': m.get('attention_share'), 'mass_z': m.get('mass_z'),
        'velocity': m.get('velocity'), 'acceleration': m.get('acceleration'),
        'control': (m.get('call_control') if side == 'CALL' else m.get('put_control')),
        # chosen contract
        'strike': best.get('strike'), 'mark': best.get('mark'), 'iv': c.get('iv_now'),
        'notional': c.get('notional'), 'delta_adj_notional': c.get('delta_adj_notional'),
        'dist_low': c.get('dist_low'), 'freshness': (c.get('freshness') or {}).get('label')
        if isinstance(c.get('freshness'), dict) else c.get('freshness'),
        # accumulation / response / lifecycle
        'accumulation': c.get('accumulation'), 'acc_label': c.get('acc_label'),
        'shape': c.get('shape'), 'resp_event': c.get('resp_event'),
        'dist_prob': c.get('dist_prob'), 'cont_prob': c.get('cont_prob'),
        'self_sust': c.get('self_sust'), 'eff_trend': c.get('eff_trend'),
        'rel_premium': c.get('rel_premium'), 'mfe': c.get('mfe'), 'shakeout': c.get('shakeout'),
        # new-phase reads
        'eas': c.get('eas'), 'archetype': (c.get('archetype') or {}).get('archetype'),
        'surface_class': (c.get('surface') or {}).get('classification'),
        'first_ts': c.get('first_ts'),
    }
    if extra:
        rec.update(extra)
    return rec


def diagnose_missed(records: list) -> dict:
    """Answer the §45 questions for one symbol/side from its archived records over a session:
    did it ever qualify at the aggregate level, which gate blocked it most, was it ever seen?"""
    if not records:
        return {'observed': False}
    ranks = [r['rank'] for r in records if r.get('rank')]
    best_rank = min(ranks) if ranks else None
    reasons = [r['reason'] for r in records
               if r.get('decision') == 'REJECTED' and r.get('reason')]
    counts = dict(Counter(reasons))
    return {
        'observed': True,
        'entered': any(r.get('decision') == 'ENTERED' for r in records),
        'best_rank': best_rank,
        'ranked_top1': best_rank == 1 if best_rank else False,
        'ranked_top3': (best_rank <= 3) if best_rank else False,
        'max_attention_share': round(max((r.get('attention_share') or 0.0) for r in records), 4),
        'ever_accumulation': any(r.get('accumulation') for r in records),
        'rejection_reasons': counts,
        'dominant_block': max(counts, key=counts.get) if counts else None,
        'n_polls': len(records),
    }


class ResearchArchive:
    """Append-only JSONL writer for candidate/entry/exit records. Failures are swallowed — research
    logging must never disrupt the trading loop."""

    def __init__(self, path: str):
        self.path = path

    def write(self, record: dict) -> None:
        try:
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, default=str) + '\n')
        except Exception:
            pass

    def load(self) -> list:
        """Read every archived record back (for offline diagnostics / replay)."""
        out = []
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        out.append(json.loads(line))
        except FileNotFoundError:
            pass
        return out
