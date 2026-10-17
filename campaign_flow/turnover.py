"""§7 Historical turnover memory → turnover RESEMBLANCE (not known closing volume, not a probability).

Memory per exact contract (append-only, point in time):
  {series, session, prev_volume, prior_ref_premium, oi_current, oi_earlier (or None), source,
   available_ts}

Match budget:
  both OI observations: min(prev_volume, oi_current, max(0, oi_current - oi_earlier))   (full weight)
  only the current OI:  min(prev_volume, oi_current)                                    (half weight)

A window covers the cumulative-volume interval [cum - vol, cum]. Its resemblance is the part of that interval
inside [0, budget], divided by vol, times the weight — so only the first `budget` contracts of the session can
resemble yesterday's turnover, not every later window. For 0DTE an earlier qualified same-day cohort gives a
half-weight intraday budget [anchor, anchor + cohort volume]. Historical and intraday are combined with max().
Premium ratios never change the score.
"""
from campaign_flow import settings as S


def _overlap(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def budget(mem: dict):
    """(budget, weight) or (None, 0) when the memory is unusable."""
    if not mem:
        return None, 0.0
    pv, cur = mem.get('prev_volume'), mem.get('oi_current')
    if pv is None or cur is None or pv < 0 or cur < 0:
        return None, 0.0
    if mem.get('oi_earlier') is not None:
        return min(pv, cur, max(0, cur - mem['oi_earlier'])), 1.0
    return min(pv, cur), 0.5


def resemblance(w: dict, mem: dict = None, cohort: dict = None) -> dict:
    """Turnover resemblance of one window. Uses history only if it was available by the window start."""
    vol, cum = w.get('volume') or 0, w.get('cum_volume')
    out = {'historical': 0.0, 'intraday': 0.0, 'resemblance': 0.0, 'labels': [], 'budget': None,
           'weight': 0.0, 'cohort_id': None}
    if vol <= 0 or cum is None:
        return out
    lo, hi = cum - vol, cum
    if mem and mem.get('available_ts') is not None and float(mem['available_ts']) <= float(w['start']):
        b, wt = budget(mem)
        if b is not None and b > 0:
            out['historical'] = round(_overlap(lo, hi, 0, b) / vol * wt, 4)
            out['budget'], out['weight'] = b, wt
    if (cohort and cohort.get('window_id') != w.get('id')
            and float(cohort['end']) <= float(w['start'])
            and str(w['contract']['expiry']) == str(cohort.get('session'))):
        a = cohort['anchor_cum']
        out['intraday'] = round(_overlap(lo, hi, a, a + cohort['volume']) / vol * 0.5, 4)
        out['cohort_id'] = cohort.get('window_id')
    out['resemblance'] = round(max(out['historical'], out['intraday']), 4)
    if out['resemblance'] > 0:
        out['labels'].append('OPEN_CLOSE_UNRESOLVED')
    if out['historical'] >= S.PRIOR_TURNOVER_LABEL_MIN:
        out['labels'].append('PRIOR_SESSION_POSITION_TURNOVER_POSSIBLE')
    if out['intraday'] > 0:
        out['labels'].append('INTRADAY_POSITION_TURNOVER_POSSIBLE')
    return out
