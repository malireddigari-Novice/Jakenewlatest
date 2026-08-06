"""
Layer 2 — internal control (which side controls the fresh auction *within* a ticker).

More call premium does NOT prove bullish call buying — it can be call selling, spread legs,
rolls, closing transactions, or vol structures. We can't perfectly infer intent, so control is
treated as *evidence*, not proof, and resolves to one of five states rather than a naive
"calls control because more call premium traded":

    CALL_CONTROL · CALL_CONTROL_PUTS_AWAKENING · BALANCED_CONTEST ·
    PUT_CONTROL_CALLS_AWAKENING · PUT_CONTROL

The state blends the dominant side's premium share with (a) whether the OPPOSITE side is
awakening — its premium accelerating relative to the leader — and (b) how PERSISTENT the
dominance has been across polls. Quote-location and neighbour synchronisation refine strength
when available. Awakening/persistence need memory, so this is a small stateful tracker.
"""
import config


class ControlTracker:

    def __init__(self) -> None:
        self._prev: dict = {}     # symbol -> (call_prem, put_prem)
        self._persist: dict = {}  # symbol -> (dominant_side, consecutive_polls)

    def new_session(self) -> None:
        self._prev.clear(); self._persist.clear()

    def evaluate(self, symbol: str, call_prem: float, put_prem: float,
                 *, quote_bias: float = None) -> dict:
        """
        quote_bias (optional, -1..+1): net buy pressure proxy from quote-location on the
        controlling side (marks near ask = buying = +, near bid = selling = -). When absent,
        control rests on premium share + awakening + persistence only.

        Returns {state, dominant_side, control_share, strength, awakening, persist_polls}.
        """
        total = call_prem + put_prem
        if total <= 0:
            self._persist[symbol] = (None, 0)
            return {'state': 'BALANCED_CONTEST', 'dominant_side': None, 'control_share': 0.0,
                    'strength': 0.0, 'awakening': False, 'persist_polls': 0}

        dominant = 'CALL' if call_prem >= put_prem else 'PUT'
        share = max(call_prem, put_prem) / total

        # Awakening: the opposite side grew faster than the leader since the last poll.
        pc, pp = self._prev.get(symbol, (call_prem, put_prem))
        d_call, d_put = call_prem - pc, put_prem - pp
        if dominant == 'CALL':
            awakening = d_put > config.CONTROL_AWAKEN_ACCEL and d_put > d_call
        else:
            awakening = d_call > config.CONTROL_AWAKEN_ACCEL and d_call > d_put
        self._prev[symbol] = (call_prem, put_prem)

        # Persistence: consecutive polls the same side has led.
        prev_side, streak = self._persist.get(symbol, (None, 0))
        streak = streak + 1 if prev_side == dominant else 1
        self._persist[symbol] = (dominant, streak)

        # Resolve state.
        if share < config.CONTROL_BALANCED_BAND:
            state = 'BALANCED_CONTEST'
        elif share >= config.CONTROL_STRONG_SHARE and not awakening:
            state = f'{dominant}_CONTROL'
        elif awakening:
            other = 'PUTS' if dominant == 'CALL' else 'CALLS'
            state = f'{dominant}_CONTROL_{other}_AWAKENING'
        else:
            state = f'{dominant}_CONTROL'

        # Strength 0-1: share scaled into [balanced_band, 1] → [0,1], docked for awakening /
        # thin persistence, nudged by observed quote buy-pressure when available.
        lo = config.CONTROL_BALANCED_BAND
        strength = max(0.0, min(1.0, (share - lo) / (1.0 - lo)))
        if awakening:
            strength *= 0.6
        if streak < config.CONTROL_PERSIST_POLLS:
            strength *= 0.8
        if quote_bias is not None:
            strength = max(0.0, min(1.0, strength * (0.7 + 0.3 * max(0.0, quote_bias))))

        return {'state': state, 'dominant_side': dominant, 'control_share': round(share, 3),
                'strength': round(strength, 3), 'awakening': awakening, 'persist_polls': streak}


def quote_bias(mark, bid, ask) -> float:
    """
    Buy-pressure proxy from where the mark sits in the bid/ask: near ask → +1 (lifting offers),
    near bid → −1 (hitting bids), mid → 0. Not intent-proof, but observable. None if unquotable.
    """
    if mark is None or bid is None or ask is None or ask <= bid:
        return 0.0
    pos = (float(mark) - float(bid)) / (float(ask) - float(bid))   # 0 at bid, 1 at ask
    return max(-1.0, min(1.0, 2.0 * pos - 1.0))
