"""
Quote / spot books and the tentative liquidity-taker reading (flow handoff §3).

A print's side is read ONLY from the last quote at or before the print (never a later quote), and only
when every condition holds: ordinary electronic single-leg condition, quote no older than
QUOTE_MAX_AGE_MS, bid > 0, ask > bid, (ask−bid)/mid ≤ QUOTE_MAX_WIDTH, and the print inside the quote
at ≥ ASK_FRAC (→ LIKELY_TAKER_BUY) or ≤ BID_FRAC (→ LIKELY_TAKER_SELL) of the bid/ask interval.
Everything else is UNKNOWN with the reason. The labels mean "the liquidity taker was probably a buyer /
seller". They never mean bought-to-open, sold-to-open or customer side.
"""
import bisect
from collections import defaultdict, deque

from tape import conditions, settings

BUY = 'LIKELY_TAKER_BUY'
SELL = 'LIKELY_TAKER_SELL'
UNKNOWN = 'UNKNOWN'


class _Book:
    """Per-key time series kept sorted by event time (late arrivals are inserted in place)."""

    def __init__(self, keep: int) -> None:
        self._t = defaultdict(list)
        self._v = defaultdict(list)
        self._keep = keep

    def add(self, key, ns, val) -> None:
        ts, vs = self._t[key], self._v[key]
        if ts and ns < ts[-1]:
            i = bisect.bisect_right(ts, ns)
            ts.insert(i, ns); vs.insert(i, val)
        else:
            ts.append(ns); vs.append(val)
        if len(ts) > self._keep:
            del ts[:len(ts) - self._keep]; del vs[:len(vs) - self._keep]

    def at(self, key, ns):
        """(event_ns, value) of the last entry with event_ns <= ns, else None."""
        ts = self._t.get(key)
        if not ts:
            return None
        i = bisect.bisect_right(ts, ns) - 1
        return (ts[i], self._v[key][i]) if i >= 0 else None

    def last(self, key):
        ts = self._t.get(key)
        return (ts[-1], self._v[key][-1]) if ts else None


class QuoteBook(_Book):
    def __init__(self, keep: int = 4096) -> None:
        super().__init__(keep)


class SpotBook(_Book):
    def __init__(self, keep: int = 4096) -> None:
        super().__init__(keep)


def classify(trade, quote_hit, *, quote_covered: bool = True) -> dict:
    """trade: events.Trade. quote_hit: (event_ns, Quote) from QuoteBook.at(occ, trade.event_ns) or None.
    quote_covered: False when the print falls in a quote-coverage gap (e.g. backfilled after a
    disconnect — quotes cannot be backfilled). Returns {side, reason, bid, ask, age_ms, loc}."""
    out = {'side': UNKNOWN, 'reason': None, 'bid': None, 'ask': None, 'age_ms': None, 'loc': None}
    tg = trade.tags
    if conditions.is_cancel(tg):
        out['reason'] = 'cancel_record'; return out
    if not conditions.side_eligible(tg):
        out['reason'] = 'condition:' + '+'.join(sorted(tg)); return out
    if not quote_covered:
        out['reason'] = 'quote_coverage_gap'; return out
    if quote_hit is None:
        out['reason'] = 'no_quote_at_or_before_print'; return out
    q_ns, q = quote_hit
    age_ms = (trade.event_ns - q_ns) / 1e6
    out.update(bid=q.bid, ask=q.ask, age_ms=round(age_ms, 3))
    if age_ms > settings.QUOTE_MAX_AGE_MS:
        out['reason'] = 'stale_quote'; return out
    if not q.bid or q.bid <= 0:
        out['reason'] = 'no_bid'; return out
    if q.ask <= q.bid:
        out['reason'] = 'crossed_or_locked'; return out
    mid = 0.5 * (q.bid + q.ask)
    if (q.ask - q.bid) / mid > settings.QUOTE_MAX_WIDTH:
        out['reason'] = 'wide_quote'; return out
    if trade.price < q.bid or trade.price > q.ask:
        out['reason'] = 'outside_quote'; return out
    loc = (trade.price - q.bid) / (q.ask - q.bid)
    out['loc'] = round(loc, 3)
    if loc >= settings.ASK_FRAC:
        out.update(side=BUY, reason='near_ask')
    elif loc <= settings.BID_FRAC:
        out.update(side=SELL, reason='near_bid')
    else:
        out['reason'] = 'mid_market'
    return out


def spot_at(spot_book: SpotBook, symbol: str, ns: int) -> dict:
    """Separately timestamped underlying spot observed at or before `ns`, ≤ SPOT_MAX_AGE_MS old.
    Missing or stale → {'spot': None, 'reason': ...} (an options-only feed leaves it missing)."""
    hit = spot_book.at(symbol, ns)
    if hit is None:
        return {'spot': None, 'age_ms': None, 'reason': 'no_spot'}
    age_ms = (ns - hit[0]) / 1e6
    if age_ms > settings.SPOT_MAX_AGE_MS:
        return {'spot': None, 'age_ms': round(age_ms, 1), 'reason': 'stale_spot'}
    return {'spot': hit[1], 'age_ms': round(age_ms, 1), 'reason': None}


class SweepDetector:
    """Rapid cross-venue sweep CANDIDATE: ≥ SWEEP_MIN contracts across ≥ SWEEP_VENUES venues within
    SWEEP_WINDOW_MS on one contract. A provisional research rule, never an exchange-certified parent."""

    def __init__(self) -> None:
        self._win = defaultdict(deque)          # occ -> deque[(ns, venue, size, key)]

    def add(self, trade) -> list:
        """Returns the print keys forming a sweep candidate that this print completes ([] otherwise)."""
        if not conditions.side_eligible(trade.tags) and 'ISO' not in trade.tags:
            return []
        w = self._win[trade.occ]
        w.append((trade.event_ns, trade.exchange, trade.size, trade.key))
        lim = settings.SWEEP_WINDOW_MS * 1e6
        while w and trade.event_ns - w[0][0] > lim:
            w.popleft()
        if (sum(s for _, _, s, _ in w) >= settings.SWEEP_MIN
                and len({v for _, v, _, _ in w}) >= settings.SWEEP_VENUES):
            return [k for _, _, _, k in w]
        return []
