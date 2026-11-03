"""§8 Contract eligibility and ranking. Every choice's rejection reasons are journaled.

Eligible: right matches the thesis (calls bullish / puts bearish); expiration survives the planned end plus
the horizon buffer (1 calendar day for SWING); a contract expiring on the planned-end date cannot be held past
the expiration liquidation deadline; quote not future-dated (beyond the clock tolerance) and <= 30 s old; bid >= 0, ask > 0, ask >= bid;
relative spread (ask - bid) / mid <= 0.30; ask size >= 1.

Ranking: by externally supplied utility ONLY when every eligible choice has one; otherwise tighter spread.
Tie-breaks: tighter spread, higher day volume, later expiration, contract symbol.
"""
from datetime import date, timedelta

from campaign_flow import calendar_ny as cal
from campaign_flow import settings as S
from campaign_flow.model import direction_right, is_adjusted


def rel_spread(bid, ask):
    mid = (float(bid) + float(ask)) / 2
    return (float(ask) - float(bid)) / mid if mid > 0 else None


def check(choice: dict, direction: str, horizon: str, planned_end_ts: float, now_ts: float) -> list:
    c, q = choice['contract'], choice.get('quote') or {}
    r = []
    if c['right'] != direction_right(direction):
        r.append('WRONG_RIGHT_FOR_THESIS')
    if is_adjusted(c) and not choice.get('multiplier_verified'):
        r.append('ADJUSTED_CONTRACT_MULTIPLIER_UNVERIFIED')
    exp = date.fromisoformat(str(c['expiry']))
    end_day = cal.ny_day(planned_end_ts)
    buffer_days = S.SWING_BUFFER_DAYS if horizon == 'SWING' else 0
    if exp < end_day + timedelta(days=buffer_days):
        r.append('EXPIRES_BEFORE_PLANNED_END_PLUS_BUFFER')
    elif exp == end_day and planned_end_ts > cal.expiry_deadline(c['expiry']):
        r.append('PLANNED_END_AFTER_EXPIRY_LIQUIDATION')
    ts = q.get('ts')
    if ts is None:
        r.append('QUOTE_MISSING')
    elif float(ts) > now_ts + S.QUOTE_CLOCK_TOL_S:
        r.append('QUOTE_FUTURE_DATED')
    elif now_ts - float(ts) > S.QUOTE_MAX_AGE_S:
        r.append('QUOTE_STALE')
    bid, ask = q.get('bid'), q.get('ask')
    if bid is None or ask is None or float(bid) < 0 or not (float(ask) > 0) or float(ask) < float(bid):
        r.append('INVALID_QUOTE')
    else:
        rs = rel_spread(bid, ask)
        if rs is None or rs > S.MAX_REL_SPREAD:
            r.append('SPREAD_TOO_WIDE')
    if (q.get('ask_size') or 0) < S.MIN_ASK_SIZE:
        r.append('ASK_SIZE_TOO_SMALL')
    return r


def select(choices, direction: str, horizon: str, planned_end_ts: float, now_ts: float) -> dict:
    journal, ok = [], []
    for ch in choices or ():
        reasons = check(ch, direction, horizon, planned_end_ts, now_ts)
        journal.append({'occ': ch['contract']['occ'], 'reasons': reasons})
        if not reasons:
            ok.append(ch)
    if not ok:
        return {'best': None, 'journal': journal, 'ranking': None}
    full_utility = all(ch.get('utility') is not None for ch in ok)

    def key(ch):
        q = ch['quote']
        spread = rel_spread(q['bid'], q['ask'])
        base = (spread, -(ch.get('day_volume') or 0), -date.fromisoformat(str(ch['contract']['expiry'])).toordinal(),
            ch['contract']['occ'])
        return ((-float(ch['utility']),) + base) if full_utility else base

    ok.sort(key=key)
    return {'best': ok[0], 'journal': journal, 'ranking': 'UTILITY' if full_utility else 'SPREAD'}
