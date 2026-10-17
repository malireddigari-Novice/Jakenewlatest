"""§6/§7 Attention board: unusual CONCENTRATED events, never gross cumulative volume.

Per eligible event:
  surprise  = min(1, log2(volume / baseline) / 3)
  shape     = max(largest-bin share, largest-print share)
  recency   = max(0, 1 - age / 1200 s)
  relevance = 1 without valid spot/IV/time; else 0.65 + 0.35 * exp(-0.5 z^2),
              z = |ln(K/S)| / (IV * sqrt(seconds / 31,557,600))      — soft, bounded, never a rejection
  raw       = 100 * (0.55 surprise + 0.30 shape + 0.15 recency) * relevance

Discounted scenario (turnover resemblance r): unmatched = max(1, volume * (1 - r)); surprise recomputed from
unmatched (floored at 0); full weighted score * (1 - r), same relevance. Call attention = max call event,
put attention = max put event, ticker score = larger side. Board ORDER is by raw; both scenarios are kept.
"""
import math

from campaign_flow import settings as S


def relevance(strike, spot, iv, secs) -> float:
    try:
        if not (spot and spot > 0 and strike and strike > 0 and iv and iv > 0 and secs and secs > 0):
            return 1.0
        z = abs(math.log(float(strike) / float(spot))) / (float(iv) * math.sqrt(float(secs) / S.YEAR_S))
        return 0.65 + 0.35 * math.exp(-0.5 * z * z)
    except (ValueError, ZeroDivisionError):
        return 1.0


def _surprise(vol, base) -> float:
    if not base or base <= 0 or vol <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log2(vol / base) / 3.0))


def event_scores(w: dict, q: dict, now_ts: float, resemblance: float = 0.0) -> dict:
    vol, base = w.get('volume') or 0, w.get('baseline')
    sh = q['shape']
    shp = max(x for x in (sh.get('top_bin'), sh.get('top_print'), 0.0) if x is not None)
    rec = max(0.0, 1.0 - (now_ts - float(w['end'])) / S.RECENCY_S)
    rel = relevance(w['contract']['strike'], w.get('spot'), w.get('iv'), w.get('secs_to_last_trade'))
    raw = 100.0 * (0.55 * _surprise(vol, base) + 0.30 * shp + 0.15 * rec) * rel
    r = max(0.0, min(1.0, resemblance or 0.0))
    unmatched = max(1.0, vol * (1.0 - r))
    disc = 100.0 * (0.55 * _surprise(unmatched, base) + 0.30 * shp + 0.15 * rec) * rel * (1.0 - r)
    return {'raw': round(raw, 2), 'discounted': round(disc, 2), 'relevance': round(rel, 4),
            'shape': round(shp, 4), 'recency': round(rec, 4), 'resemblance': r}


def _rank(rows, key) -> dict:
    order = sorted(rows, key=lambda t: (-rows[t][key], t))           # deterministic ticker tie-break
    return {t: i + 1 for i, t in enumerate(order)}


def _unique_leader(rows, key):
    if not rows:
        return None
    top = max(r[key] for r in rows.values())
    if top <= 0:
        return None
    leaders = [t for t, r in rows.items() if r[key] == top]
    return leaders[0] if len(leaders) == 1 else None


def _side(row, scen):
    c, p = row[f'call_{scen}'], row[f'put_{scen}']
    return None if c == p else ('CALL' if c > p else 'PUT')


def build(events, now_ts: float, states: dict = None) -> dict:
    """events: [(window, qualification, resemblance_dict)] for ELIGIBLE events in the lookback.
    states: ticker -> board state from cluster assessment (WATCH default)."""
    rows = {}
    for w, q, res in events:
        if not q.get('eligible'):
            continue
        t = w['contract']['ticker']
        side = 'call' if w['contract']['right'] == 'C' else 'put'
        sc = event_scores(w, q, now_ts, (res or {}).get('resemblance', 0.0))
        row = rows.setdefault(t, {'call_raw': 0.0, 'put_raw': 0.0, 'call_discounted': 0.0,
                                  'put_discounted': 0.0, 'events': 0, 'labels': set()})
        row['events'] += 1
        row[f'{side}_raw'] = max(row[f'{side}_raw'], sc['raw'])
        row[f'{side}_discounted'] = max(row[f'{side}_discounted'], sc['discounted'])
        row['labels'].update((res or {}).get('labels') or [])
    for t, row in rows.items():
        row['ticker_raw'] = max(row['call_raw'], row['put_raw'])
        row['ticker_discounted'] = max(row['call_discounted'], row['put_discounted'])
        row['side_raw'], row['side_discounted'] = _side(row, 'raw'), _side(row, 'discounted')
        if row['side_raw'] != row['side_discounted']:
            row['labels'].add('SIDE_SCENARIO_DISAGREEMENT')
        row['state'] = (states or {}).get(t, 'WATCH')
        row['labels'] = sorted(row['labels'])
    rank_raw, rank_disc = _rank(rows, 'ticker_raw'), _rank(rows, 'ticker_discounted')
    for t, row in rows.items():
        row['rank_raw'], row['rank_discounted'] = rank_raw[t], rank_disc[t]
    lr, ld = _unique_leader(rows, 'ticker_raw'), _unique_leader(rows, 'ticker_discounted')
    agrees = lr is not None and lr == ld
    labels = [] if agrees or (lr is None and ld is None) else ['LEADER_SCENARIO_DISAGREEMENT']
    return {'rows': rows, 'order': sorted(rows, key=lambda t: rank_raw[t]), 'leader_raw': lr,
            'leader_discounted': ld, 'scenario_leader_agrees': agrees, 'labels': labels}
