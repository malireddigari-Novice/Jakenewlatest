"""
Fresh-premium + within-name control (Layer 2 — "what is the money doing?").

The attention board (Layer 1) needs one number per name — its share of the day's FRESH
institutional premium — plus which side (call/put) controls that name and how one-sided it
is. This module produces exactly that from Alpaca option snapshots.

Why *fresh*, not cumulative:  cumulative day volume tells you what already happened; the
market's attention is about what is happening THIS minute. So we diff each contract's
cumulative day volume against the prior poll to recover the minute's new contracts, then
dollar-weight them:

    fresh_premium(contract) = Δvolume × mark × 100          (premium notional this minute)
                              × relevance_to_spot           (ATM matters, far-OTM doesn't)

Raw contract count is a poor signal — 5,000 contracts at $0.05 is not 1,000 at $1.00, and
far-OTM churn shouldn't move the needle — hence the dollar + relevance weighting.

`PremiumTracker` holds the per-contract cumulative-volume baseline across polls; everything
else here is a pure function.
"""
from typing import Optional


def relevance_to_spot(spot: Optional[float], strike: float, band_pct: float = 0.03) -> float:
    """1.0 at ATM, decaying linearly to 0 at `band_pct` (default 3%) from spot."""
    if not spot or spot <= 0:
        return 1.0
    d = abs(strike - spot) / spot
    return max(0.0, 1.0 - d / band_pct)


def _room_from_low(mark: Optional[float], low: Optional[float], high: Optional[float]) -> Optional[float]:
    """
    Distance-from-low score (0-1): 1.0 when the contract sits ON its day low (max room /
    convexity left), 0.0 at the day high. None when the range is unknown. Feeds the
    Attention Score's optional 'low' term.
    """
    if mark is None or low is None or high is None or high <= low:
        return None
    pos = (float(mark) - float(low)) / (float(high) - float(low))
    return max(0.0, min(1.0, 1.0 - pos))


def directional_premium(*, delta_vol, mark, spot, strike, band_pct=0.03) -> float:
    """Dollar-weighted fresh directional contribution of one contract this poll."""
    if not delta_vol or not mark or mark <= 0:
        return 0.0
    notional = float(delta_vol) * float(mark) * 100.0
    return notional * relevance_to_spot(spot, strike, band_pct)


def symbol_attention_input(contracts: list, spot: Optional[float],
                           band_pct: float = 0.03) -> Optional[dict]:
    """
    Aggregate one name's contracts into the attention-board input row.

    contracts : list of {strike, side ('CALL'/'PUT'), delta_vol, mark, day_low, day_high}
                — delta_vol is THIS poll's fresh contracts (see PremiumTracker).

    Returns {premium, control_side, control_share, low_score} or None if no premium moved.
      premium       : total fresh $-premium across both sides (this name's pool contribution)
      control_side  : 'CALL' | 'PUT' — the side committing more fresh premium
      control_share : dominant / total ∈ [0.5, 1.0] — how one-sided the name is
      low_score     : room-from-low of the control side's heaviest contract (optional)
    """
    call_w = put_w = 0.0
    # Track the heaviest contract on each side so low_score reflects where the money is.
    heaviest = {'CALL': (0.0, None), 'PUT': (0.0, None)}  # side -> (premium, contract)
    for c in contracts:
        w = directional_premium(delta_vol=c.get('delta_vol'), mark=c.get('mark'),
                                spot=spot, strike=c.get('strike'), band_pct=band_pct)
        if w <= 0:
            continue
        side = c.get('side')
        if side == 'CALL':
            call_w += w
        elif side == 'PUT':
            put_w += w
        else:
            continue
        if w > heaviest[side][0]:
            heaviest[side] = (w, c)

    total = call_w + put_w
    if total <= 0:
        return None
    control_side = 'CALL' if call_w >= put_w else 'PUT'
    lead = call_w if control_side == 'CALL' else put_w
    lead_contract = heaviest[control_side][1]
    low_score = None
    if lead_contract is not None:
        low_score = _room_from_low(lead_contract.get('mark'),
                                   lead_contract.get('day_low'), lead_contract.get('day_high'))
    return {
        'premium':       round(total),
        'control_side':  control_side,
        'control_share': round(lead / total, 3),
        'low_score':     low_score,
    }


class PremiumTracker:
    """
    Holds each contract's last-seen CUMULATIVE day volume so per-poll deltas can be recovered.

    First sighting of a contract records a baseline and reports delta 0 — otherwise the entire
    day's already-accumulated volume would read as one giant burst of "fresh" attention on the
    first poll (or right after a mid-session restart). A cumulative volume that drops (new
    session) resets the baseline.
    """

    def __init__(self) -> None:
        self._cum: dict = {}         # (symbol, strike, side) -> last cumulative volume
        self._session = None         # date; baselines reset on a new session

    def new_session(self, session_date) -> None:
        if self._session != session_date:
            self._cum.clear()
            self._session = session_date

    def contracts_with_deltas(self, symbol: str, snapshots: dict) -> list:
        """
        Convert {(strike, side): snapshot} into the contract list `symbol_attention_input`
        wants, attaching each contract's fresh (delta) volume for this poll.
        """
        out = []
        for (strike, side), q in snapshots.items():
            key = (symbol, strike, side)
            cum = int(q.get('volume') or 0)
            prev = self._cum.get(key)
            if prev is None:
                delta = 0                       # first sighting → baseline only
            elif cum < prev:
                delta = 0                       # session reset / correction
            else:
                delta = cum - prev
            self._cum[key] = cum
            out.append({
                'strike':   strike,
                'side':     side,
                'delta_vol': delta,
                'mark':     q.get('mark'),
                'day_low':  q.get('day_low'),
                'day_high': q.get('day_high'),
            })
        return out
