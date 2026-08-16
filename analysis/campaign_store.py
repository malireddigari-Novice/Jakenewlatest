"""
Cross-session campaign memory (new-spec P1) — pure helpers over plain dicts.

An institutional campaign does not die because the calendar changed. If a contract's expiration is
still alive in the next session, the campaign is serialized (in the engine's state file, which is
saved every poll — so it also survives a mid-day process restart) and restored at startup. Key rules:

  • An inherited campaign is UNDER MANAGEMENT, not a new entry — it does NOT consume the new day's
    CALL/PUT slot (safeguard #4).
  • Campaign identity is (ticker, side, origin_date, lead strike) — it can migrate strikes without
    becoming a new campaign (safeguard #2/#5); `lead_strike` and `trade_contract` are separate ideas.
  • A surviving prior campaign raises the bar for an OPPOSITE-side entry that session (hysteresis,
    safeguard #9/#23) — Friday's first AMZN put must overcome Thursday's funded call campaign.
  • Terminal states (EXITED/INVALIDATED/COMPLETED/EXPIRED) stop imposing hysteresis (safeguard #20).
"""
from datetime import date

_TERMINAL = {'EXITED', 'INVALIDATED', 'COMPLETED', 'EXPIRED'}


def campaign_id(ticker, side, origin_date, strike) -> str:
    d = str(origin_date).replace('-', '')
    k = ('%g' % strike) if strike is not None else 'x'
    return f"{ticker}-{side}-{d}-{k}"


def _as_date(x):
    if hasattr(x, 'isoformat') and not isinstance(x, str):
        return x
    try:
        return date.fromisoformat(str(x))
    except Exception:
        return None


def survives(expiry, today) -> bool:
    """True if the option expiration is still alive today (expiry >= today) — a Friday 0DTE campaign
    is still live on Friday, but not on Saturday."""
    e, t = _as_date(expiry), _as_date(today)
    return bool(e and t and e >= t)


def record(ticker, side, strike, expiry, origin_date, confidence, state, notional=None) -> dict:
    return {'campaign_id': campaign_id(ticker, side, origin_date, strike),
            'ticker': ticker, 'side': side, 'lead_strike': strike, 'expiry': str(expiry),
            'origin_date': str(origin_date), 'confidence': confidence, 'state': state,
            'notional': notional, 'overnight': False}


def classify_overnight(camp, today) -> str:
    if camp.get('state') in _TERMINAL:
        return 'OVERNIGHT_' + camp['state']
    if not survives(camp.get('expiry'), today):
        return 'OVERNIGHT_EXPIRED'
    return 'OVERNIGHT_INTACT'


def carry_forward(campaigns, today) -> dict:
    """Keep only non-terminal campaigns whose expiry is still alive `today`, marked inherited."""
    out = {}
    for cid, c in (campaigns or {}).items():
        if c.get('state') in _TERMINAL:
            continue
        if survives(c.get('expiry'), today):
            c = dict(c)
            c['overnight'] = True
            c['overnight_state'] = 'OVERNIGHT_INTACT'
            out[cid] = c
    return out


def classify_end(reason, pnl=None, carried=False) -> str:
    """Campaign END taxonomy (addendum #21) — an ended campaign is not one thing. Maps the exit reason
    (+ realized P&L, + whether the contract was carried overnight) to a durable historical label:
    FAILED / DISTRIBUTED / REALIZED_PROFIT / EXPIRED_PROFITABLY / ROLLED / CARRIED_OVERNIGHT / UNKNOWN."""
    r = (reason or '').upper()
    if carried:
        return 'CARRIED_OVERNIGHT'
    if 'REVERS' in r or 'ROLL' in r:
        return 'ROLLED'
    if 'STOP_LOSS' in r or 'INVALID' in r:
        return 'FAILED'
    if 'DISTRIBUTION' in r:
        return 'DISTRIBUTED'
    if r in ('EOD_FLATTEN',) and pnl is not None:
        return 'EXPIRED_PROFITABLY' if pnl > 0 else 'FAILED'
    if r in ('STRUCTURAL_TP1', 'STRUCTURAL_TP2', 'RUNNER_TRAIL', 'TRAIL_GIVEBACK') or (pnl is not None and pnl > 0):
        return 'REALIZED_PROFIT'
    if pnl is not None and pnl <= 0:
        return 'FAILED'
    return 'UNKNOWN'


def opposite_inherited(campaigns, ticker, side):
    """An inherited, non-terminal campaign on the OPPOSITE side for this ticker (raises the entry
    bar for `side`), or None."""
    opp = 'PUT' if side == 'CALL' else 'CALL'
    for c in (campaigns or {}).values():
        if (c.get('ticker') == ticker and c.get('side') == opp and c.get('overnight')
                and c.get('state') not in _TERMINAL):
            return c
    return None
