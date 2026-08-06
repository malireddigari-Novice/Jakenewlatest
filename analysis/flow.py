"""
Flow measurement (the raw signal every layer reads) — rolling, timestamped, self-normalised.

The v1 tracker diffed cumulative volume between two 60-second polls. That is too slow (a 0DTE
event that starts at 09:30:05 is up 30-100% by 09:31) and too crude (premium dollars alone
favour expensive chains). `FlowTracker` fixes both:

  • it ingests contract snapshots every few seconds, keeping ~3 minutes of timestamped samples,
  • it measures FRESH volume AND premium over rolling 30s / 60s / 180s windows (not a single
    minute), plus velocity (Δ over consecutive windows) and acceleration (Δ velocity),
  • it seeds baselines pre-open so the OPENING AUCTION is measured, not discarded,
  • it computes an Attention Shock per ticker: how abnormal this poll's activity is versus that
    ticker's OWN rolling baseline — so AAPL doing $500k when it usually does $80k outranks META
    doing $700k when META always does $600k.

Cumulative day volume is monotonic within a session; fresh flow over an interval [a,b] is
`cum(b) − cum(a)`. Everything downstream (control, events, attention) reads `symbol_flow()`.
"""
from collections import deque

import config


def _epoch(ts) -> float:
    """Accept a datetime or epoch float → epoch seconds."""
    return ts.timestamp() if hasattr(ts, 'timestamp') else float(ts)


class FlowTracker:

    def __init__(self) -> None:
        # (symbol, strike, side) -> deque of (ts, cum_vol, mark, bid, ask, bsz, asz, qts,
        #                                     day_low, day_high, delta, gamma, iv)
        self._samples: dict = {}
        self._spot: dict = {}          # symbol -> deque of (ts, spot)
        self._baseline: dict = {}      # symbol -> {'mean': float, 'mad': float}
        self._last_poll_ts: dict = {}  # symbol -> ts of the previous poll (for per-poll shock)
        self._session = None
        self._keep = max(config.WINDOW_SLOW * 2, 240)  # seconds of history to retain

    # ── ingest ────────────────────────────────────────────────────────────────

    def new_session(self, session_date) -> None:
        if self._session != session_date:
            self._samples.clear(); self._spot.clear()
            self._baseline.clear(); self._last_poll_ts.clear()
            self._session = session_date

    def ingest(self, symbol: str, snapshots: dict, spot: float, ts) -> None:
        """Store one poll's snapshots for a symbol (called pre-open to seed, and every poll)."""
        t = _epoch(ts)
        self._spot.setdefault(symbol, deque()).append((t, float(spot)))
        for (strike, side), q in snapshots.items():
            key = (symbol, strike, side)
            self._samples.setdefault(key, deque()).append((
                t, int(q.get('volume') or 0), q.get('mark'), q.get('bid'), q.get('ask'),
                int(q.get('bid_size') or 0), int(q.get('ask_size') or 0), q.get('quote_ts'),
                q.get('day_low'), q.get('day_high'), q.get('delta'), q.get('gamma'),
                q.get('implied_vol')))
        self._prune(t)

    def _prune(self, now_t: float) -> None:
        cutoff = now_t - self._keep
        for dq in self._samples.values():
            while dq and dq[0][0] < cutoff:
                dq.popleft()
        for dq in self._spot.values():
            while dq and dq[0][0] < cutoff:
                dq.popleft()

    # ── fresh-flow primitives ───────────────────────────────────────────────────

    @staticmethod
    def _cum_at(dq: deque, t: float) -> int:
        """Cumulative volume at time t = last sample with ts <= t (else earliest sample)."""
        val = None
        for s in dq:
            if s[0] <= t:
                val = s[1]
            else:
                break
        if val is None:
            val = dq[0][1] if dq else 0
        return val

    def _fresh_interval(self, key, a: float, b: float) -> int:
        dq = self._samples.get(key)
        if not dq:
            return 0
        return max(0, self._cum_at(dq, b) - self._cum_at(dq, a))

    def _last(self, key):
        dq = self._samples.get(key)
        return dq[-1] if dq else None

    # ── per-contract series (for price-response / volume-pattern validation) ─────

    def contract_mark_at(self, symbol, strike, side, t):
        """The contract's mark at time t (last sample with ts <= t), or None."""
        dq = self._samples.get((symbol, strike, side))
        if not dq:
            return None
        val = None
        for s in dq:
            if s[0] <= t:
                val = s[2]
            else:
                break
        return val if val is not None else dq[0][2]

    def contract_iv_at(self, symbol, strike, side, t):
        """The contract's implied vol at time t (last sample with ts <= t), or None."""
        dq = self._samples.get((symbol, strike, side))
        if not dq:
            return None
        val = None
        for s in dq:
            if s[0] <= t:
                val = s[12] if len(s) > 12 else None
            else:
                break
        if val is not None:
            return val
        return dq[0][12] if (dq and len(dq[0]) > 12) else None

    def contract_marks(self, symbol, strike, side, now, window_s=None):
        """
        The contract's premium series [(ts, mark), ...] over the trailing `window_s`, oldest→
        newest — the raw marks (max resolution) that the lifecycle layer reads for windowed
        response, max-favourable-excursion, shakeout, and self-sustainability.
        """
        window_s = window_s if window_s is not None else config.RESP_WINDOW_S
        dq = self._samples.get((symbol, strike, side))
        if not dq:
            return []
        cutoff = _epoch(now) - window_s
        return [(s[0], s[2]) for s in dq if s[0] >= cutoff and s[2] is not None]

    def contract_minute_vols(self, symbol, strike, side, now, window_s=None, bin_s=60):
        """
        Per-minute FRESH volume for one contract over the trailing `window_s`, oldest→newest.
        At the 1-min backtest cadence each bin is one bar; at the live 5s cadence bins aggregate.
        """
        window_s = window_s if window_s is not None else config.VP_TRAIL_S
        dq = self._samples.get((symbol, strike, side))
        if not dq:
            return []
        now_t = _epoch(now)
        vols, b = [], now_t - window_s
        while b < now_t - 1:
            vols.append(max(0, self._cum_at(dq, b + bin_s) - self._cum_at(dq, b)))
            b += bin_s
        return vols

    # ── per-symbol structured flow ──────────────────────────────────────────────

    def symbol_flow(self, symbol: str, now) -> dict | None:
        """
        Aggregate this symbol into the structured record every downstream layer reads.
        Windowed fresh premium/volume + velocity + acceleration + per-strike breakdown +
        spot series. Returns None if the symbol has no samples.
        """
        now_t = _epoch(now)
        spots = self._spot.get(symbol)
        if not spots:
            return None
        spot = spots[-1][1]
        spot_prev = self._spot_at(symbol, now_t - config.WINDOW_FAST) or spot

        w = config.WINDOW_MID
        call_prem = put_prem = 0.0
        call_vol = put_vol = 0
        strikes: dict = {}
        for key, dq in self._samples.items():
            if key[0] != symbol or not dq:
                continue
            _sym, strike, side = key
            last = dq[-1]
            mark = last[2]
            fresh_vol = self._fresh_interval(key, now_t - w, now_t)
            if mark is None:
                continue
            fresh_prem = fresh_vol * float(mark) * 100.0
            strikes[(strike, side)] = {
                'strike': strike, 'side': side, 'fresh_vol': fresh_vol, 'fresh_prem': fresh_prem,
                'mark': mark, 'bid': last[3], 'ask': last[4], 'bid_size': last[5],
                'ask_size': last[6], 'quote_ts': last[7], 'day_low': last[8],
                'day_high': last[9], 'delta': last[10], 'gamma': last[11],
                'iv': last[12] if len(last) > 12 else None,
            }
            if side == 'CALL':
                call_prem += fresh_prem; call_vol += fresh_vol
            else:
                put_prem += fresh_prem; put_vol += fresh_vol

        fresh_prem_window = call_prem + put_prem
        fresh_vol_window = call_vol + put_vol

        # Velocity / acceleration from consecutive non-overlapping windows.
        f0 = self._symbol_fresh_prem(symbol, now_t - w, now_t)
        f1 = self._symbol_fresh_prem(symbol, now_t - 2 * w, now_t - w)
        f2 = self._symbol_fresh_prem(symbol, now_t - 3 * w, now_t - 2 * w)
        velocity = f0 - f1
        acceleration = (f0 - f1) - (f1 - f2)

        # Per-poll fresh (since the previous poll) — the non-overlapping series for shock.
        last_poll = self._last_poll_ts.get(symbol)
        poll_fresh = (self._symbol_fresh_prem(symbol, last_poll, now_t)
                      if last_poll is not None else fresh_prem_window)

        return {
            'symbol': symbol, 'spot': spot, 'spot_prev': spot_prev,
            'fresh_prem_window': fresh_prem_window, 'fresh_vol_window': fresh_vol_window,
            'fresh_prem_poll': poll_fresh, 'velocity': velocity, 'acceleration': acceleration,
            'call_prem': call_prem, 'put_prem': put_prem,
            'call_vol': call_vol, 'put_vol': put_vol, 'strikes': strikes,
        }

    def mark_poll(self, symbol: str, now) -> None:
        """Record that a poll completed for this symbol (advances the per-poll shock baseline)."""
        self._last_poll_ts[symbol] = _epoch(now)

    def _spot_at(self, symbol: str, t: float):
        dq = self._spot.get(symbol)
        if not dq:
            return None
        val = None
        for s in dq:
            if s[0] <= t:
                val = s[1]
            else:
                break
        return val if val is not None else (dq[0][1] if dq else None)

    def _symbol_fresh_prem(self, symbol: str, a: float, b: float) -> float:
        total = 0.0
        for key, dq in self._samples.items():
            if key[0] != symbol or not dq:
                continue
            mark = dq[-1][2]
            if mark is None:
                continue
            total += self._fresh_interval(key, a, b) * float(mark) * 100.0
        return total

    # ── attention shock (self-normalised) ───────────────────────────────────────

    def update_shock(self, symbol: str, poll_fresh: float) -> float:
        """
        Attention Shock z-score for this poll: (poll_fresh − baseline_mean) / (dispersion + eps),
        where the baseline is a rolling EWMA of the ticker's OWN per-poll fresh premium and its
        mean-absolute-deviation. Updates the baseline. Clipped to +/- SHOCK_CLIP.
        """
        b = self._baseline.get(symbol)
        if b is None:
            self._baseline[symbol] = {'mean': poll_fresh, 'mad': max(poll_fresh, config.SHOCK_EPS)}
            return 0.0
        dev = poll_fresh - b['mean']
        disp = 1.4826 * b['mad'] + config.SHOCK_EPS
        z = max(-config.SHOCK_CLIP, min(config.SHOCK_CLIP, dev / disp))
        a = config.SHOCK_BASELINE_ALPHA
        b['mean'] = (1 - a) * b['mean'] + a * poll_fresh
        b['mad'] = (1 - a) * b['mad'] + a * abs(dev)
        return round(z, 3)
