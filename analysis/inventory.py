"""
Inventory Memory Layer (addendum #1-4, #22) — pure helpers over a persistent per-contract dict.

The bridge from "unusual options flow scanner" to "infer the lifecycle of institutional positioning":
a print has no meaning in isolation from the inventory history that preceded it.

  Yesterday: 1,000 @ ~$3.00      Today: another 1,000 @ ~$1.00

The second lot is NOT automatically another huge directional event — depending on history it may be
liquidation, covering, rolling or overwriting. We cannot know from the print alone, but we CAN know
when the ambiguity is high enough that the correct decision is to PASS.

This layer keeps, per surviving contract (ticker|side|strike|expiry), the significant prints it has
seen (size + price) and derives:
  • a COST-BASIS zone         : size-weighted VWAP of remembered prints, with lo/hi;
  • InventoryAmbiguity        : LOW / MED / HIGH — HIGH when a fresh same-side print lands far away
                                from an established basis (below → likely unwind; above → likely
                                distribution-into-strength);
  • MarginalFlowEfficiency    : ΔP since the basis / additional same-side flow — the "slow hidden exit"
                                detector (#3): repeated same-side prints that no longer advance premium
                                are more likely inventory being monetized than reinforcement;
  • an inventory STATE        : UNKNOWN / LIKELY_BUILDING / LIKELY_FUNDED / LIKELY_PARTIAL_EXIT.

The engine uses this to DISCOUNT low-confidence flow and to ABSTAIN (first-class PASS) on HIGH
ambiguity, and to SUPPRESS a false CAMPAIGN STRENGTHENING when MFE has gone weak. Records survive the
session boundary while the expiry is alive (same rule as campaign memory). No I/O here.
"""
import config

_AMBIG = ('LOW', 'MED', 'HIGH')


def contract_key(ticker, side, strike, expiry) -> str:
    k = ('%g' % strike) if strike is not None else 'x'
    return f"{ticker}|{side}|{k}|{expiry}"


def _basis(rec: dict) -> dict:
    """Size-weighted cost-basis zone from remembered prints."""
    prints = rec.get('prints') or []
    tot = sum(p['size'] for p in prints) or 0.0
    if tot <= 0:
        return {'vwap': None, 'lo': None, 'hi': None, 'size': 0.0}
    vwap = sum(p['size'] * p['price'] for p in prints) / tot
    lows = [p['price'] for p in prints]
    return {'vwap': round(vwap, 4), 'lo': round(min(lows), 4), 'hi': round(max(lows), 4),
            'size': round(tot, 1)}


def observe(rec, *, price, size, ts, spot=None, iv=None) -> dict:
    """Record a fresh significant print on this contract (fold it into inventory memory).
    A sub-floor print is ignored (returns the record unchanged) so background churn does not create a
    phantom basis. Returns the (possibly new) record dict — the caller persists it in state."""
    rec = rec or {'prints': [], 'first_ts': None, 'last_ts': None, 'peak_price': None}
    if not price or (size or 0) < config.INV_EVENT_MIN_CONTRACTS:
        return rec
    rec.setdefault('prints', []).append({'price': round(float(price), 4), 'size': float(size),
                                         'ts': ts, 'iv': iv})
    rec['prints'] = rec['prints'][-config.INV_MAX_PRINTS:]
    rec['first_ts'] = rec['first_ts'] or ts
    rec['last_ts'] = ts
    rec['peak_price'] = max(rec.get('peak_price') or price, price)
    return rec


def marginal_flow_efficiency(rec, current_price) -> float:
    """ΔP since the MOST-RECENT recorded clip, per contract of that clip — the genuinely *marginal*
    read (#3). Positive = the latest same-side flow is still advancing premium (accumulation). Near
    zero = premium stalling on new flow. Negative = premium rolling over while flow continues (the
    hidden partial-exit / distribution signature). Returns a small positive default with no history."""
    prints = (rec or {}).get('prints') or []
    if not prints or not current_price:
        return 1.0
    last = prints[-1]
    if (last.get('size') or 0) <= 0:
        return 1.0
    return round((float(current_price) - float(last['price'])) / float(last['size']), 6)


def assess(rec, *, current_price, new_size=0.0) -> dict:
    """Interpret a fresh same-side print against remembered inventory on this contract.
    Returns ambiguity / state / discount (a 0..1 multiplier for qualified mass or entry quality) /
    mfe / reason. With no prior inventory it is a clean fresh anomaly → LOW ambiguity, no discount."""
    b = _basis(rec or {})
    mfe = marginal_flow_efficiency(rec, current_price)
    if b['vwap'] is None or not current_price:
        return {'ambiguity': 'LOW', 'state': 'UNKNOWN', 'discount': 1.0, 'mfe': mfe,
                'basis_vwap': None, 'reason': 'no prior inventory — fresh anomaly'}
    drift = (float(current_price) - b['vwap']) / b['vwap'] if b['vwap'] else 0.0
    below = drift <= -config.INV_BASIS_BELOW_PCT
    above = drift >= config.INV_BASIS_ABOVE_PCT
    stalling = mfe <= config.INV_MFE_WEAK          # premium no longer advancing on the latest flow
    if below:
        # a new same-side print far under the established basis is as consistent with liquidation /
        # covering as with fresh conviction — the ambiguity itself is the signal to stand down.
        amb, state = 'HIGH', 'LIKELY_PARTIAL_EXIT'
        reason = f'print {100*drift:+.0f}% below basis ${b["vwap"]:.2f} — unwind vs fresh ambiguous'
    elif above and stalling:
        # ran far above basis and the latest same-side clip no longer advances premium — the
        # classic distribution-into-strength top (#3).
        amb, state = 'HIGH', 'LIKELY_PARTIAL_EXIT'
        reason = f'{100*drift:+.0f}% above basis with MFE stalling ({mfe:.4f}) — distribution-into-strength'
    elif above or stalling:
        amb, state = 'MED', 'LIKELY_FUNDED'
        reason = ('extended above basis — add-to-winner vs distribute ambiguous' if above
                  else 'MFE stalling — premium no longer advancing on new flow')
    else:
        amb, state = 'LOW', 'LIKELY_BUILDING'
        reason = f'adding near basis ${b["vwap"]:.2f} with premium advancing — coherent build'
    discount = (config.INV_HIGH_DISCOUNT if amb == 'HIGH'
                else config.INV_MED_DISCOUNT if amb == 'MED' else 1.0)
    return {'ambiguity': amb, 'state': state, 'discount': discount, 'mfe': mfe,
            'basis_vwap': b['vwap'], 'basis_lo': b['lo'], 'basis_hi': b['hi'],
            'basis_size': b['size'], 'drift': round(drift, 3), 'reason': reason}


def depletion(rec) -> dict:
    """Coarse remaining-inventory estimate (addendum #4). Approximates how much of the position was
    distributed near strength: the fraction of remembered volume printed >= INV_BASIS_ABOVE_PCT above
    the contract's running low. Maps to FUNDED / PARTIAL_EXIT / MAJORITY_EXITED / LIKELY_CLOSED."""
    prints = (rec or {}).get('prints') or []
    total = sum(p['size'] for p in prints) or 0.0
    if total <= 0:
        return {'state': 'INVENTORY_UNKNOWN', 'remaining': 1.0, 'distributed': 0.0}
    lo = min(p['price'] for p in prints) or 0.0
    hi_gate = lo * (1.0 + config.INV_BASIS_ABOVE_PCT)
    distributed = sum(p['size'] for p in prints if p['price'] >= hi_gate and p['price'] > lo)
    frac = distributed / total
    if frac >= config.INV_DEPLETE_CLOSED:
        state = 'LIKELY_CLOSED'
    elif frac >= config.INV_DEPLETE_MAJORITY:
        state = 'MAJORITY_EXITED'
    elif frac >= config.INV_DEPLETE_PARTIAL:
        state = 'LIKELY_PARTIAL_EXIT'
    else:
        state = 'LIKELY_FUNDED'
    return {'state': state, 'remaining': round(max(0.0, 1.0 - frac), 3), 'distributed': round(frac, 3)}


def micro_distribution(minute_vols, marks, est_campaign_vol) -> dict:
    """Cumulative small-clip unwind detector (v3-review item 5). The 250-contract event floor misses a
    slow hidden exit — 1,000 accumulated, then 100-lots every ~10 min while premium rises. We do NOT
    need any single clip to be large: count minutes AFTER the premium peak that carry modest same-side
    volume while premium sits near its highs (exit-like distribution-into-strength), sum that exit-like
    volume, and compare it to the estimated original campaign volume. Probabilistic — never a ledger.
    Returns {chunked(bool), state, exit_like_vol, clips, frac, reason}."""
    v = [float(x) for x in (minute_vols or []) if x is not None and x >= 0]
    # marks may be plain floats or (ts, mark) tuples (the lifecycle layer's raw premium series).
    m = []
    for x in (marks or []):
        val = x[1] if isinstance(x, (tuple, list)) else x
        if val is not None:
            m.append(float(val))
    if len(v) < config.INV_MICRO_MIN_CLIPS or len(m) < 3 or not est_campaign_vol:
        return {'chunked': False, 'state': 'INSUFFICIENT', 'exit_like_vol': 0.0, 'clips': 0,
                'frac': 0.0, 'reason': 'not enough history'}
    peak = max(m)
    peak_i = m.index(peak)
    hi_gate = 0.85 * peak                       # "near the highs"
    # align vols to marks by trailing overlap (both oldest→newest); count post-peak elevated-premium minutes
    tail = v[-len(m):] if len(v) >= len(m) else v
    exit_like, clips = 0.0, 0
    for i in range(peak_i, len(m)):
        vi = tail[i] if i < len(tail) else 0.0
        if m[i] >= hi_gate and vi > 0:
            exit_like += vi
            clips += 1
    frac = exit_like / est_campaign_vol if est_campaign_vol else 0.0
    chunked = (clips >= config.INV_MICRO_MIN_CLIPS and frac >= config.INV_MICRO_EXIT_FRAC)
    state = 'LIKELY_DISTRIBUTING_IN_CHUNKS' if chunked else 'NO_CHUNKED_EXIT'
    return {'chunked': chunked, 'state': state, 'exit_like_vol': round(exit_like, 1), 'clips': clips,
            'frac': round(frac, 3),
            'reason': (f'{clips} small clips into strength = {100*frac:.0f}% of est campaign vol'
                       if chunked else f'{clips} clips, {100*frac:.0f}% of est vol — below chunk threshold')}


def prune(store, today, survives_fn) -> dict:
    """Drop inventory records whose expiry is no longer alive today (same rule as campaign memory).
    `survives_fn(expiry, today)` is campaign_store.survives — passed in to avoid a circular import."""
    out = {}
    for key, rec in (store or {}).items():
        exp = key.rsplit('|', 1)[-1]
        if survives_fn(exp, today):
            out[key] = rec
    return out
