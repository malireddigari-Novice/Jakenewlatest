"""
Verified catalysts (flow handoff §8) — pure reads over an optional JSON calendar.

A catalyst may only colour a signal if it was KNOWABLE at the signal: the source must have been
published at or before the signal time, and the event must still be in the future. Each entry in
`config.CATALYST_FILE` (a JSON list; absent file = no calendar) is:

    {"symbol": "NVDA",                       # or "*" for a market-wide event (CPI, FOMC)
     "event": "earnings",
     "event_time": "2026-11-19T16:05:00-05:00",
     "timing": "AMC",                        # BMO / AMC / UNKNOWN
     "source_url": "https://investor.nvidia.com/...",
     "published_at": "2026-10-01T09:00:00-04:00",
     "observed_at": "2026-10-02T08:00:00-05:00"}

An entry missing any of those fields is UNVERIFIED (shown as such, never as fact). An option that
expires before the event is an EVENT_MISMATCH — it cannot be positioned for that event. The card gets
at most one short conditional sentence; the full record goes to the decision ledger.
"""
import json
import os
from datetime import date, datetime

import config
from data import exchange_calendar as xcal

_REQUIRED = ('symbol', 'event', 'event_time', 'timing', 'source_url', 'published_at', 'observed_at')
_cache = {'path': None, 'mtime': None, 'rows': []}


def _load() -> list | None:
    """Calendar rows, or None when no calendar file is configured/present."""
    path = config.CATALYST_FILE
    if not path or not os.path.exists(path):
        return None
    mtime = os.path.getmtime(path)
    if _cache['path'] != path or _cache['mtime'] != mtime:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                rows = json.load(f)
            _cache.update(path=path, mtime=mtime, rows=rows if isinstance(rows, list) else [])
        except Exception:
            _cache.update(path=path, mtime=mtime, rows=[])
    return _cache['rows']


def _ts(v):
    try:
        t = datetime.fromisoformat(str(v))
        return t if t.tzinfo else None            # a naive time is ambiguous → treated as missing
    except Exception:
        return None


def assess(symbol: str, now: datetime, expiry=None, rows=None) -> dict:
    """{status, event, mismatch, sentence}. status: NO_CALENDAR · NONE_ON_FILE · VERIFIED · UNVERIFIED."""
    rows = _load() if rows is None else rows
    if rows is None:
        return {'status': 'NO_CALENDAR', 'event': None, 'mismatch': None,
                'sentence': 'Catalyst: no verified calendar loaded.'}
    exp = expiry if isinstance(expiry, date) or expiry is None else date.fromisoformat(str(expiry)[:10])
    best = None
    for r in rows:
        if r.get('symbol') not in (symbol, '*'):
            continue
        ev_t = _ts(r.get('event_time'))
        pub_t = _ts(r.get('published_at'))
        if ev_t is None or ev_t <= now:
            continue                                   # past (or undatable) event — cannot explain a print
        if pub_t is not None and pub_t > now:
            continue                                   # not yet published at signal time — not knowable
        missing = [k for k in _REQUIRED if not r.get(k)] + ([] if pub_t else ['published_at'])
        if best is None or ev_t < best[0]:
            best = (ev_t, r, sorted(set(missing)))
    if best is None:
        return {'status': 'NONE_ON_FILE', 'event': None, 'mismatch': None,
                'sentence': 'Catalyst: none on file before expiry.' if exp else 'Catalyst: none on file.'}
    ev_t, r, missing = best
    ev_day = xcal.ny_date(ev_t)
    timing = (r.get('timing') or 'UNKNOWN').upper()
    mismatch = None
    if exp is not None:
        # expires before the release: before the event day, or on it when the release is after the close
        mismatch = exp < ev_day or (exp == ev_day and timing == 'AMC')
    status = 'UNVERIFIED' if missing else 'VERIFIED'
    who = 'market' if r.get('symbol') == '*' else r.get('symbol')
    s = f"{who} {r.get('event')} {ev_day.isoformat()} {timing}"
    if status == 'UNVERIFIED':
        sentence = f"Catalyst (unverified — missing {', '.join(missing)}): {s}."
    elif mismatch:
        sentence = f"Catalyst: {s} — this expiry ends BEFORE the event (event mismatch)."
    else:
        sentence = f"Catalyst: {s} — if the flow is event positioning, IV crush after the release applies."
    return {'status': status, 'event': {**r, 'missing': missing}, 'mismatch': mismatch, 'sentence': sentence}
