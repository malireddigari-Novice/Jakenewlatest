"""
Event-information contract selection (new-spec P4, §16) — pure.

The best contract is not necessarily the most active or the mass-center strike. It is often the strike
carrying the highest-information EVENT at the most actionable moment: high BarVolumeShock (P2, and
`significant` — clears the absolute floor), near-ATM / relevant, executable (liquid, tight spread),
and still favorably priced (room from its low). This is how the engine can pick NVDA 222.5P over the
noisier, higher-volume 220P. Consumes the per-strike shocks P2 produces.
"""
import config


def _room_from_low(mark, low, high):
    if not mark or not low or low <= 0:
        return 0.5
    ext = mark / low
    return max(0.0, min(1.0, 1.0 - (ext - 1.0) / max(config.GATE_MAX_DIST_FROM_LOW - 1.0, 1e-9)))


def event_score(sd, spot, shock_info):
    """0-1 selection score by event information; None if the contract is not quotable."""
    mark = sd.get('mark')
    if not mark or not (sd.get('ask') or mark):
        return None
    shock = (shock_info or {}).get('shock', 0.0) or 0.0
    sig = 1.0 if (shock_info or {}).get('significant') else 0.0
    shock_term = max(0.0, min(1.0, shock / 8.0))
    bid, ask = sd.get('bid'), sd.get('ask')
    spread_pct = ((ask - bid) / mark) if (bid and ask and mark > 0) else 1.0
    spread_term = max(0.0, 1.0 - spread_pct / config.GATE_MAX_SPREAD_PCT)
    liq = min(1.0, min(sd.get('bid_size') or 0, sd.get('ask_size') or 0) / max(1, config.GATE_MIN_QUOTE_SIZE))
    relevance = max(0.0, 1.0 - abs(sd['strike'] - spot) / (spot * 0.01)) if spot else 0.5
    room = _room_from_low(mark, sd.get('day_low'), sd.get('day_high'))
    return round(config.ES_W_SHOCK * shock_term + config.ES_W_SIG * sig
                 + config.ES_W_RELEVANCE * relevance + config.ES_W_SPREAD * spread_term
                 + config.ES_W_LIQ * liq + config.ES_W_ROOM * room, 4)


def select(side, side_strikes, spot, shocks):
    """Pick the highest event-information contract in the ATM±EVENT_SELECT_WINDOW window (shocks keyed
    by strike). Returns the chosen strike dict enriched with event_score, or None if nothing quotable."""
    quotable = [s for s in side_strikes if s.get('mark') and (s.get('ask') or s.get('mark'))]
    if not quotable:
        return None
    quotable.sort(key=lambda s: abs(s['strike'] - spot))
    window = quotable[:config.EVENT_SELECT_WINDOW + 1]
    scored = [(s, event_score(s, spot, (shocks or {}).get(s['strike']))) for s in window]
    scored = [(s, sc) for s, sc in scored if sc is not None]
    if not scored:
        return None
    best, sc = max(scored, key=lambda x: x[1])
    out = dict(best)
    out['event_score'] = sc
    out['event_selected'] = True
    out['low_score'] = _room_from_low(out.get('mark'), out.get('day_low'), out.get('day_high'))
    out['is_atm'] = (out['strike'] == quotable[0]['strike'])
    return out
