"""
Event-level provenance (v3-canonicalization item 17) — pure helpers over a persistent append list.

Inventory memory collapses prints into ONE size-weighted cost basis. That is the right summary for the
"is this still funded?" question, but it destroys the information needed to recognize that MULTIPLE
latent campaigns can occupy the same contract through time (one participant accumulates while another
monetizes; a roll replaces an outright; a new buyer arrives after an old seller leaves).

So, in addition to the inventory summary, each SIGNIFICANT contract event is recorded IMMUTABLY — never
merged, never overwritten — with everything needed to later separate superposed campaigns:

    event_id, ts, size, price, spot, moneyness, iv, delta, shape,
    direction_hypothesis, inventory_hypothesis

The store is a capped append list per contract (ticker|side|strike|expiry). Nothing here interprets or
collapses; it just preserves the raw event stream for future campaign-superposition analysis.
"""
import config


def contract_key(ticker, side, strike, expiry):
    k = ('%g' % strike) if strike is not None else 'x'
    return f"{ticker}|{side}|{k}|{expiry}"


def event_id(ticker, side, strike, expiry, ts) -> str:
    """Stable per-event id: CONTRACT@timestamp (immutable — a later poll of the same minute reuses it,
    so re-observation updates in place rather than duplicating)."""
    k = ('%g' % strike) if strike is not None else 'x'
    return f"{ticker}-{side}-{k}-{expiry}-{ts}"


def record(store, *, ticker, side, strike, expiry, ts, size, price, spot=None, iv=None, delta=None,
           moneyness=None, shape=None, direction_hyp=None, inventory_hyp=None) -> dict:
    """Append an IMMUTABLE event to this contract's list (idempotent on event_id). `store` is the whole
    events dict {contract_key: [events]}; returns it for the caller to persist."""
    store = store if store is not None else {}
    key = contract_key(ticker, side, strike, expiry)
    lst = store.setdefault(key, [])
    eid = event_id(ticker, side, strike, expiry, ts)
    if any(e.get('event_id') == eid for e in lst):
        return store                                   # already recorded this minute — do not duplicate
    lst.append({'event_id': eid, 'ts': ts, 'size': size, 'price': price, 'spot': spot, 'iv': iv,
                'delta': delta, 'moneyness': moneyness, 'shape': shape,
                'direction_hyp': direction_hyp, 'inventory_hyp': inventory_hyp})
    store[key] = lst[-config.EVENT_MEMORY_MAX:]        # cap, keep most recent
    return store


def events_for(store, ticker, side, strike, expiry) -> list:
    return (store or {}).get(contract_key(ticker, side, strike, expiry), [])


def prune(store, today, survives_fn) -> dict:
    """Drop event lists whose expiry is no longer alive today (same rule as inventory/value memory)."""
    out = {}
    for key, lst in (store or {}).items():
        if survives_fn(key.rsplit('|', 1)[-1], today):
            out[key] = lst
    return out
