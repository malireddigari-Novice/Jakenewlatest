"""
Feed coverage per ticker (flow handoff §3) — pure, I/O-free.

Fresh flow is `cum(b) − cum(a)` between snapshots. After a gap (failed fetch, empty chain, every
snapshot dropped by data-quality, the process stalling) the next read lumps the WHOLE gap's volume into
one window — a fake shock. A gap is therefore a coverage incident, not data: the ticker is DEGRADED
until fresh windows have refilled from continuous post-gap samples (COVERAGE_RECOVERY_S), and the
engine takes no new entry on it meanwhile (exits and management still run). The first ingest of a
session is not a gap.

A gap is either
  MISSED_CYCLE  the ticker was absent from at least one completed poll cycle (fetch failed / empty chain /
                every snapshot dropped) — always an incident, however short the cycle was; or
  SLOW_CYCLE    consecutive ingests further apart than gap_s. gap_s must sit above the normal cycle or every
                slow-but-normal cycle reads as an outage (2026-10-19, sequential fetches: median 17 s, p99 44 s
                with the periodic multi-expiry reads; fetches are parallel since).
`t` is the ticker's own data-receipt time, not the cycle start.

States: HEALTHY · DEGRADED (recovering after an incident) · NO_DATA (never ingested this session).
"""


class CoverageTracker:

    def __init__(self, gap_s: float, recovery_s: float) -> None:
        self.gap_s, self.recovery_s = float(gap_s), float(recovery_s)
        self._last_ok: dict = {}         # symbol -> epoch of last successful ingest
        self._degraded_until: dict = {}  # symbol -> epoch when the ticker becomes HEALTHY again
        self.incidents: list = []        # [{symbol, gap_start, gap_end, gap_s, cause}] this session
        self._missed: dict = {}          # symbol -> completed cycles it was absent from since its last ingest

    def reset(self) -> None:
        self._last_ok.clear(); self._degraded_until.clear(); self.incidents.clear(); self._missed.clear()

    def cycle_done(self, ingested, t: float) -> None:
        """A poll cycle completed; every known ticker not in `ingested` missed it."""
        got = set(ingested)
        for sym in self._last_ok:
            if sym not in got:
                self._missed[sym] = self._missed.get(sym, 0) + 1

    def ok(self, symbol: str, t: float) -> dict | None:
        """Record a successful ingest at epoch t. Returns the incident when this ingest closes a gap."""
        last = self._last_ok.get(symbol)
        self._last_ok[symbol] = t
        missed = self._missed.pop(symbol, 0)
        if last is not None and (missed or t - last > self.gap_s):
            inc = {'symbol': symbol, 'gap_start': last, 'gap_end': t, 'gap_s': round(t - last, 1),
                   'cause': 'MISSED_CYCLE' if missed else 'SLOW_CYCLE', 'missed_cycles': missed}
            self.incidents.append(inc)
            self._degraded_until[symbol] = t + self.recovery_s
            return inc
        return None

    def state(self, symbol: str, t: float) -> str:
        if symbol not in self._last_ok:
            return 'NO_DATA'
        if t - self._last_ok[symbol] > self.gap_s:
            return 'DEGRADED'                       # currently inside an open gap
        if t < self._degraded_until.get(symbol, 0.0):
            return 'DEGRADED'
        return 'HEALTHY'
