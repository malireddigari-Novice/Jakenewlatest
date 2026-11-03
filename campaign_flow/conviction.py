"""Conviction tiers for one ticker's call side and put side (Mag 7 brief item 5).

A verified cluster (clusters.py) says WHERE flow concentrated. Conviction asks whether the flow behind it looks
like institutional positioning rather than an early or thin burst, built from the brief's suggested approach:

  1 normalized by time of day  every window is compared with the same contract's prior-session baseline for
                               the same time-of-day bucket, and with this side's earlier windows today
  2 across strikes/expiries    all near-the-money strikes of the right (|K/spot - 1| <= CF_CONV_MONEYNESS), every
                               observed expiration, summed per aligned window — never a single contract
  3 persistence                consecutive latest windows above CF_CONV_SLOT_REL_MIN x baseline
  4 aggressor side             near-ask share (the snapshot adapter's documented proxy)
  5 relative size              contracts vs baseline, and a premium-$ floor
  6 confirmation               the option mid rose across the windows carrying the volume (no reversal)
  7 score + tier               WEAK / BUILDING / CONFIRMED; every threshold is a CF_CONV_* setting
  9 logged inputs              the returned dict is journaled with every decision that uses it

Pure: windows in, a dict out. The pipeline supplies `history` = this side's per-window near-the-money volume
earlier in the session (for the intraday comparison).
"""
from statistics import median

from campaign_flow import settings as S

WEAK, BUILDING, CONFIRMED = 'WEAK', 'BUILDING', 'CONFIRMED'
RANK = {WEAK: 0, BUILDING: 1, CONFIRMED: 2}
MIN_HISTORY = 5                     # earlier windows needed before the intraday comparison is scored


def near_money(w: dict, spot) -> bool:
    s = spot or w.get('spot')
    return bool(s) and float(s) > 0 and abs(float(w['contract']['strike']) / float(s) - 1) <= S.CONV_MONEYNESS


def _unit_px(w: dict) -> float:
    for v in (w.get('event_premium'), w.get('prem_end'), w.get('prem_start')):
        if v:
            return float(v)
    return 0.0


def slot_totals(windows, right: str, spot) -> dict:
    """{(start, end): {vol, base, near, prem_usd, up_vol, priced_vol}} for one right, near the money."""
    out = {}
    for w in windows:
        c = w['contract']
        if c['right'] != right or not near_money(w, spot):
            continue
        s = out.setdefault((float(w['start']), float(w['end'])),
                           {'vol': 0, 'base': 0.0, 'near': 0, 'prem_usd': 0.0, 'up_vol': 0, 'priced_vol': 0})
        v = int(w.get('volume') or 0)
        s['vol'] += v
        s['base'] += float(w.get('baseline') or S.BASELINE_FLOOR)
        s['near'] += int(w.get('near_ask') or 0)
        s['prem_usd'] += v * _unit_px(w) * float(c.get('multiplier') or 100)
        ps, pe = w.get('prem_start'), w.get('prem_end')
        if ps is not None and pe is not None:
            s['priced_vol'] += v
            if float(pe) > float(ps):
                s['up_vol'] += v
    return out


def _side(slots: dict, opp_prem: float, history) -> dict:
    keys = sorted(slots, key=lambda k: k[1])
    vol = sum(slots[k]['vol'] for k in keys)
    base = sum(slots[k]['base'] for k in keys)
    prem = sum(slots[k]['prem_usd'] for k in keys)
    persist = 0
    for k in reversed(keys):
        s = slots[k]
        if s['base'] > 0 and s['vol'] >= S.CONV_SLOT_REL_MIN * s['base']:
            persist += 1
        else:
            break
    priced = sum(slots[k]['priced_vol'] for k in keys)
    hist = [h for h in (history or []) if h is not None]
    med = median(hist) if len(hist) >= MIN_HISTORY else None
    per_slot = vol / len(keys) if keys else 0.0
    comp = {
        'size': vol / base if base > 0 else 0.0,
        'intraday': None if med is None else (per_slot / med if med > 0 else (99.0 if per_slot else 0.0)),
        'persistence': float(persist),
        'aggressor': sum(slots[k]['near'] for k in keys) / vol if vol else 0.0,
        'dominance': prem / (prem + opp_prem) if prem + opp_prem > 0 else 0.0,
        'support': sum(slots[k]['up_vol'] for k in keys) / priced if priced else 0.0,
    }
    thr = {'size': S.CONV_MIN_REL_SIZE, 'intraday': S.CONV_MIN_INTRADAY_REL, 'persistence': S.CONV_MIN_PERSIST,
           'aggressor': S.CONV_MIN_NEAR_ASK, 'dominance': S.CONV_MIN_DOMINANCE, 'support': S.CONV_MIN_SUPPORT}
    parts = {k: min(1.5, comp[k] / thr[k]) / 1.5 for k in comp if comp[k] is not None and thr[k] > 0}
    score = round(100 * sum(parts.values()) / len(parts), 1) if parts and vol else 0.0
    gates = {'size': comp['size'] >= S.CONV_MIN_REL_SIZE, 'persistence': persist >= S.CONV_MIN_PERSIST,
             'premium_usd': prem >= S.CONV_MIN_PREMIUM_USD}
    if score >= S.CONV_CONFIRMED_SCORE and all(gates.values()):
        tier = CONFIRMED
    elif score >= S.CONV_BUILDING_SCORE and comp['size'] >= S.CONV_SLOT_REL_MIN:
        tier = BUILDING                  # building needs at least elevated volume, not just clean shape
    else:
        tier = WEAK
    return {'tier': tier, 'score': score, 'components': {k: (None if v is None else round(v, 3))
                                                           for k, v in comp.items()},
            'gates': gates, 'contracts': vol, 'baseline': round(base, 1), 'premium_usd': round(prem),
            'windows': len(keys), 'history_windows': len(hist), 'history_median': med}


def assess(items, now_ts: float, spot, history=None) -> dict:
    """{'C': side, 'P': side} over the windows that ended in the last CONV_SPAN_S. `items` are the pipeline's
    evaluated windows ({'w': window, ...}); `history` = {'C': [...], 'P': [...]} earlier per-window volumes."""
    ws = [it['w'] for it in items if 0 <= now_ts - float(it['w']['end']) <= S.CONV_SPAN_S]
    slots = {r: slot_totals(ws, r, spot) for r in ('C', 'P')}
    prem = {r: sum(s['prem_usd'] for s in slots[r].values()) for r in slots}
    out = {}
    for r, o in (('C', 'P'), ('P', 'C')):
        out[r] = _side(slots[r], prem[o], (history or {}).get(r))
        out[r]['span_s'] = S.CONV_SPAN_S
    return out


def at_least(side: dict, tier: str) -> bool:
    return bool(side) and RANK.get(side.get('tier'), -1) >= RANK[tier]
