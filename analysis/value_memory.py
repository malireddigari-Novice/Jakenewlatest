"""
Contract value memory (v3-review item 4) — persistent, state-adjusted historical value. Pure.

Inventory memory remembers PRINTS (size + basis). This remembers VALUE: what the contract has been
worth over time and how cheap it is *now* relative to its own robust history — with the explicit
caveat that a naive "$3 yesterday, $1 today" comparison is wrong, because the same option legitimately
reprices on spot / theta / IV / moneyness. So we store the state at each observation and judge
cheapness against a ROBUST low (a low percentile of marks), not the session low (a bad $0.05 print or
a wide opening spread must never anchor the day's value).

Per contract (ticker|side|strike|expiry) we keep a capped ring of samples {ts, mark, bid, ask, spot,
moneyness, delta, iv} and expose:
  • robust_low   : VALUE_LOW_PCTILE percentile of marks (noise-resistant floor)
  • cheapness    : where the current mark sits in the mark distribution (0 = cheapest seen, 1 = richest)
  • is_cheap     : current mark at/below the VALUE_CHEAP_PCTILE percentile
  • state_adjusted_ratio : current mark vs a delta/DTE-expected mark from the last sample — how much of
                   a move is NOT explained by spot/time (the piece that flags real cheapening vs repricing)
Cross-session: kept while the expiry is alive (pruned with campaign/inventory memory).
"""
import config


def contract_key(ticker, side, strike, expiry):
    k = ('%g' % strike) if strike is not None else 'x'
    return f"{ticker}|{side}|{k}|{expiry}"


def observe(rec, *, mark, bid=None, ask=None, spot=None, moneyness=None, delta=None, iv=None, ts=None):
    """Append a value sample (skips a non-positive mark). Returns the record for the caller to persist."""
    rec = rec or {'samples': []}
    if not mark or mark <= 0:
        return rec
    rec.setdefault('samples', []).append({
        'ts': ts, 'mark': round(float(mark), 4),
        'bid': bid, 'ask': ask, 'spot': spot,
        'moneyness': moneyness, 'delta': delta, 'iv': iv})
    rec['samples'] = rec['samples'][-config.VALUE_MAX_SAMPLES:]
    return rec


def _pctile(sorted_vals, p):
    if not sorted_vals:
        return None
    i = max(0, min(len(sorted_vals) - 1, int(round(p * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def assess(rec, *, current_mark, current_delta=None, current_spot=None) -> dict:
    """Where does current_mark sit in this contract's robust value history?
    Returns robust_low / cheapness(0-1) / is_cheap / state_adjusted_ratio / n. Empty history → neutral
    (is_cheap True, so a brand-new contract is not penalised for having no history)."""
    samples = (rec or {}).get('samples') or []
    marks = sorted(s['mark'] for s in samples if s.get('mark'))
    if not marks or not current_mark:
        return {'robust_low': None, 'cheapness': None, 'is_cheap': True,
                'state_adjusted_ratio': None, 'n': len(marks), 'reason': 'no value history'}
    robust_low = _pctile(marks, config.VALUE_LOW_PCTILE)
    cheap_gate = _pctile(marks, config.VALUE_CHEAP_PCTILE)
    below = sum(1 for m in marks if m <= current_mark)
    cheapness = round(below / len(marks), 3)                # fraction of history at/below current
    is_cheap = current_mark <= (cheap_gate if cheap_gate else current_mark)

    # state-adjusted: from the most recent PRIOR sample, what mark would delta·Δspot alone predict?
    # the residual (actual/expected) isolates cheapening NOT explained by the underlying move.
    sar = None
    prev = samples[-1] if samples else None
    if prev and current_delta is not None and current_spot is not None and prev.get('spot'):
        exp = (prev['mark'] or 0) + float(current_delta) * (current_spot - prev['spot'])
        if exp and exp > 0:
            sar = round(current_mark / exp, 3)             # <1 = cheaper than the spot move explains
    return {'robust_low': robust_low, 'cheap_gate': cheap_gate, 'cheapness': cheapness,
            'is_cheap': bool(is_cheap), 'state_adjusted_ratio': sar, 'n': len(marks),
            'reason': f'mark ${current_mark:.2f} at {100*cheapness:.0f}%ile (robust-low ${robust_low:.2f})'}


def prune(store, today, survives_fn) -> dict:
    """Drop value records whose expiry is no longer alive today (same rule as inventory/campaign)."""
    out = {}
    for key, rec in (store or {}).items():
        if survives_fn(key.rsplit('|', 1)[-1], today):
            out[key] = rec
    return out
