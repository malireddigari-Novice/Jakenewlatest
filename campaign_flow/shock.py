"""§2/§4 Completed option windows: validation and concentrated-shock qualification.

A window (built by an adapter) is a dict:
  contract, start, end (epoch), volume (incremental contracts), prints (count or a documented lower bound),
  baseline (comparable-window volume) + baseline_method, near_ask (contracts) + near_ask_provenance,
  bins (disjoint completed sub-window volumes summing to `volume`), largest_print (or None), prem_start /
  prem_end (same price basis), spot, iv, secs_to_last_trade, cum_volume (session cumulative at `end`),
  complex_status ('SIMPLE' | 'MIXED' | 'UNAVAILABLE'), value (value_gate.classify result), available_ts.

`eligible` = may receive buy attention (board); `accepted` = eligible AND premium rose across the window,
which is what campaign clusters count. One shock alone is WATCH (clusters decide control).
"""
from campaign_flow import settings as S
from campaign_flow.model import series_key, window_id


def shape(w: dict) -> dict:
    """Concentration evidence: largest bin share, largest-two share, largest print share (None = missing)."""
    vol = w.get('volume') or 0
    bins = [int(b) for b in (w.get('bins') or []) if b is not None]
    out = {'top_bin': None, 'top2': None, 'top_print': None}
    if vol > 0 and bins and sum(bins) == vol:
        s = sorted(bins, reverse=True)
        out['top_bin'] = s[0] / vol
        out['top2'] = (s[0] + (s[1] if len(s) > 1 else 0)) / vol
    lp = w.get('largest_print')
    if vol > 0 and lp is not None:
        out['top_print'] = min(1.0, lp / vol)
    return out


def _invalid(w: dict, decision_ts: float) -> list:
    r = []
    c = w.get('contract') or {}
    if not all(c.get(k) not in (None, '') for k in ('ticker', 'right', 'strike', 'expiry')):
        r.append('INVALID_CONTRACT_IDENTITY')
    try:
        if not (float(w['start']) < float(w['end'])):
            r.append('INVALID_WINDOW_BOUNDS')
    except Exception:
        r.append('INVALID_WINDOW_BOUNDS')
        return r
    vol = w.get('volume')
    if not isinstance(vol, int) or vol < 0:
        r.append('INVALID_VOLUME')
    if w.get('bins') is not None and isinstance(vol, int) and sum(int(b) for b in w['bins']) != vol:
        r.append('BINS_DO_NOT_SUM_TO_WINDOW_VOLUME')
    if w.get('near_ask') is not None and isinstance(vol, int) and not (0 <= w['near_ask'] <= vol):
        r.append('INVALID_NEAR_ASK')
    if w.get('largest_print') is not None and isinstance(vol, int) and w['largest_print'] > vol:
        r.append('INVALID_LARGEST_PRINT')
    for k in ('prem_start', 'prem_end'):
        if w.get(k) is not None and float(w[k]) < 0:
            r.append('INVALID_PREMIUM')
    if w.get('cum_volume') is not None and isinstance(vol, int) and w['cum_volume'] < vol:
        r.append('CUMULATIVE_BELOW_WINDOW_VOLUME')
    if float(w['end']) > decision_ts or float(w.get('available_ts') or w['end']) > decision_ts:
        r.append('FUTURE_WINDOW')
    return r


def validate_windows(windows, decision_ts: float):
    """Reject invalid, future, duplicate, overlapping and cumulatively inconsistent windows.
    Returns (valid, rejected) where rejected = [(window, [reasons])]. One print can never back two windows:
    of two overlapping windows for the same series, the later-starting one is rejected."""
    valid, rejected, seen = [], [], set()
    for w in sorted(windows, key=lambda w: (float(w.get('start') or 0), float(w.get('end') or 0))):
        reasons = _invalid(w, decision_ts)
        if not reasons:
            w.setdefault('id', window_id(w))
            if w['id'] in seen:
                reasons.append('DUPLICATE_WINDOW')
        if reasons:
            rejected.append((w, reasons))
        else:
            seen.add(w['id'])
            valid.append(w)
    by_series, out = {}, []
    for w in valid:
        by_series.setdefault(series_key(w['contract']), []).append(w)
    for key, ws in by_series.items():
        prev = None
        for w in ws:                                        # sorted by start
            reasons = []
            if prev is not None:
                if float(w['start']) < float(prev['end']):
                    reasons.append('OVERLAPPING_WINDOW')
                elif w.get('cum_volume') is not None and prev.get('cum_volume') is not None:
                    adv = w['cum_volume'] - prev['cum_volume']
                    if adv < w['volume'] or (float(w['start']) == float(prev['end']) and adv != w['volume']):
                        reasons.append('CUMULATIVE_VOLUME_INCONSISTENT')
            if reasons:
                rejected.append((w, reasons))
                continue
            out.append(w)
            prev = w
    out.sort(key=lambda w: (float(w['end']), series_key(w['contract'])))
    return out, rejected


def qualify(w: dict, now_ts: float) -> dict:
    """§4 eligibility. Every failing requirement is recorded (not just the first)."""
    reasons, logs = [], []
    vol = w.get('volume') or 0
    dur = float(w['end']) - float(w['start'])
    if dur > S.SHOCK_MAX_WINDOW_S:
        reasons.append('WINDOW_LONGER_THAN_MAX')
    if now_ts - float(w['end']) > S.FLOW_LOOKBACK_S:
        reasons.append('OUTSIDE_FLOW_LOOKBACK')
    if vol < S.SHOCK_MIN_CONTRACTS:
        reasons.append('BELOW_MIN_CONTRACTS')
    if w.get('prints') is None:
        reasons.append('PRINT_COUNT_UNAVAILABLE')
    elif w['prints'] < S.SHOCK_MIN_PRINTS:
        reasons.append('BELOW_MIN_PRINTS')
    base = w.get('baseline')
    if base is None or base <= 0:
        reasons.append('COMPARABLE_BASELINE_MISSING')
    elif vol < S.SHOCK_MIN_SURPRISE * base:
        reasons.append('BELOW_VOLUME_SURPRISE')
    if w.get('near_ask') is None:
        reasons.append('NEAR_ASK_CLASSIFICATION_UNAVAILABLE')
    elif vol <= 0 or w['near_ask'] / vol < S.SHOCK_MIN_NEAR_ASK:
        reasons.append('NEAR_ASK_BELOW_MIN')
    if not (w.get('contract') or {}).get('expiry'):
        reasons.append('MISSING_EXPIRATION')
    cs = w.get('complex_status') or 'UNAVAILABLE'
    if cs == 'MIXED':
        reasons.append('KNOWN_COMPLEX_LEG_CONTAMINATION')
    elif cs == 'UNAVAILABLE':
        logs.append('COMPLEX_LEG_STATUS_UNAVAILABLE')
    val = w.get('value') or {}
    band = val.get('band') or 'UNRESOLVED'
    if band != 'LOW':
        reasons.extend(val.get('reasons') or ['EXACT_CONTRACT_VALUE_HISTORY_MISSING'])
    sh = shape(w)
    conc = None
    if sh['top_bin'] is None and sh['top_print'] is None:
        reasons.append('MISSING_EVENT_SHAPE_EXCLUDED')
    else:
        if sh['top_bin'] is not None and sh['top_bin'] >= S.SHAPE_TOP_BIN and sh['top2'] >= S.SHAPE_TOP2:
            conc = 'A_BINS'
        elif sh['top_print'] is not None and sh['top_print'] >= S.SHAPE_TOP_PRINT:
            conc = 'B_LARGEST_PRINT'
        if conc is None:
            reasons.append('PERSISTENT_OR_DIFFUSE_BACKGROUND_EXCLUDED')
    eligible = not reasons
    ps, pe = w.get('prem_start'), w.get('prem_end')
    accepted = eligible and ps is not None and pe is not None and float(pe) > float(ps)
    if eligible and not accepted:
        logs.append('FLOW_WITHOUT_PREMIUM_ACCEPTANCE_WATCH')
    return {'window_id': w.get('id') or window_id(w), 'eligible': eligible, 'accepted': accepted,
            'reasons': reasons, 'logs': logs, 'shape': sh, 'concentration': conc}
