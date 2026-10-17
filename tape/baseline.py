"""
Production baseline job + point-in-time baseline reads (flow handoff §4).

For a trade in session S every relative metric compares against history ending at the LAST COMPLETED
session before S:
  • series volume  — median daily contract volume over the previous BASELINE_SESSIONS completed sessions
                     (Alpaca daily bars). Sessions before the series was first observed are MISSING, not 0;
                     a session after first observation with no bar is a genuine 0-volume day.
  • name premium   — the underlying's PREMIUM_PCTL single-print premium over the same lookback, pooled
                     from per-session log-bucket histograms (captured prints, or a bounded REST bootstrap).
  • prior OI       — the latest published OI vintage dated BEFORE S (the contract master's
                     open_interest_date), stored with its fetch time.
Each relative metric needs ≥ BASELINE_MIN_SESSIONS sampled sessions, and a baseline whose as-of is the
same day, in the future, or > BASELINE_MAX_STALE_D calendar days old is rejected. Missing history is
recorded as MISSING with a reason, never as zero.
"""
import json
import math
from datetime import date, datetime, timedelta

from data import exchange_calendar as xcal
from tape import conditions, events, settings

# Log-spaced premium buckets: $10 … $1e9, 40 per decade (~6% width).
_LO, _PER_DECADE, _DECADES = 1.0, 40, 8


def _bucket(v: float) -> int:
    if v <= 10 ** _LO:
        return 0
    return min(_PER_DECADE * _DECADES - 1, int((math.log10(v) - _LO) * _PER_DECADE))


def _bucket_value(b: int) -> float:
    return 10 ** (_LO + (b + 1) / _PER_DECADE)          # upper edge — conservative for a "≥ 2×p95" screen


def histogram(premiums) -> dict:
    h = {}
    for p in premiums:
        b = _bucket(p)
        h[b] = h.get(b, 0) + 1
    return h


def pooled_percentile(hists, pct) -> float | None:
    tot = {}
    for h in hists:
        for b, n in h.items():
            tot[int(b)] = tot.get(int(b), 0) + n
    n = sum(tot.values())
    if not n:
        return None
    need, run = pct / 100.0 * n, 0
    for b in sorted(tot):
        run += tot[b]
        if run >= need:
            return _bucket_value(b)
    return _bucket_value(max(tot))


def completed_sessions(before: date, n: int) -> list:
    out, d = [], before - timedelta(days=1)
    while len(out) < n and d > before - timedelta(days=n * 3 + 15):
        if xcal.is_trading_day(d):
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def validate_asof(as_of: date, for_session: date) -> str | None:
    """Reject same-day / future / stale baselines. Returns a rejection reason or None."""
    if as_of is None:
        return 'no_as_of'
    if as_of >= for_session:
        return 'same_day_or_future'
    if (for_session - as_of).days > settings.BASELINE_MAX_STALE_D:
        return 'stale'
    return None


def series_median(daily: dict, sessions: list) -> dict:
    """daily: {date: volume} from bars (absent day after first observation = 0). sessions: completed
    sessions to sample. Returns {value, n, status, as_of, reason}."""
    seen = sorted(daily)
    if not seen:
        return {'value': None, 'n': 0, 'status': 'MISSING', 'as_of': sessions[-1] if sessions else None,
                'reason': 'series never observed in lookback (newly listed or no trades)'}
    first = seen[0]
    sampled = [daily.get(s, 0) for s in sessions if s >= first]
    n = len(sampled)
    if n < settings.BASELINE_MIN_SESSIONS:
        return {'value': None, 'n': n, 'status': 'INSUFFICIENT', 'as_of': sessions[-1],
                'reason': f'{n} sampled sessions < {settings.BASELINE_MIN_SESSIONS}'}
    s = sorted(sampled)
    med = s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])
    return {'value': float(med), 'n': n, 'status': 'OK', 'as_of': sessions[-1], 'reason': None}


def quiet_build(daily: dict, sessions: list) -> dict | None:
    """Quiet-campaign retention: ≥ QUIET_MIN_TOTAL contracts over the last QUIET_SESSIONS sampled
    sessions, each < QUIET_MAX_DAILY. Returned for review — not an alert."""
    first = min(daily) if daily else None
    if first is None:
        return None
    sampled = [(s, daily.get(s, 0)) for s in sessions if s >= first][-settings.QUIET_SESSIONS:]
    if len(sampled) < settings.QUIET_SESSIONS:
        return None
    vols = [v for _, v in sampled]
    if sum(vols) >= settings.QUIET_MIN_TOTAL and all(0 < v < settings.QUIET_MAX_DAILY for v in vols):
        return {'total': sum(vols), 'sessions': len(vols), 'daily': {s.isoformat(): v for s, v in sampled}}
    return None


class Baselines:
    """Point-in-time baseline reads for one session, backed by the tape DB."""

    def __init__(self, store, for_session: date) -> None:
        self.store, self.session = store, for_session
        self._cache = {}

    def _row(self, scope, kind):
        k = (scope, kind)
        if k not in self._cache:
            r = self.store.q("SELECT value, n_sessions, as_of, status, detail FROM baselines WHERE scope=? AND kind=? "
                             "AND for_session=?", (scope, kind, self.session.isoformat()))
            self._cache[k] = r[0] if r else None
        return self._cache[k]

    def _read(self, scope, kind) -> dict:
        r = self._row(scope, kind)
        if not r:
            return {'value': None, 'status': 'MISSING', 'n': 0, 'as_of': None, 'reason': 'baseline job has not run'}
        value, n, as_of, status, detail = r
        if status != 'OK':
            return {'value': None, 'status': status, 'n': n, 'as_of': as_of, 'reason': detail}
        rej = validate_asof(date.fromisoformat(as_of), self.session)
        if rej:
            return {'value': None, 'status': 'REJECTED', 'n': n, 'as_of': as_of, 'reason': rej}
        return {'value': value, 'status': 'OK', 'n': n, 'as_of': as_of, 'reason': None}

    def series_median(self, occ) -> dict:
        return self._read(occ, 'series_median_volume')

    def name_premium(self, underlying) -> dict:
        return self._read(underlying, 'name_premium_p%g' % settings.PREMIUM_PCTL)

    def prior_oi(self, occ, at_ns: int = None) -> dict:
        """Latest OI vintage dated before this session AND fetched before `at_ns` (point-in-time)."""
        rows = self.store.q("SELECT oi, oi_date, fetched_at FROM oi_vintages WHERE occ=? AND oi_date<? "
                            "ORDER BY oi_date DESC", (occ, self.session.isoformat()))
        for oi, oi_date, fetched_at in rows:
            if at_ns is not None and fetched_at and events.iso_to_ns(fetched_at) > at_ns:
                continue
            rej = validate_asof(date.fromisoformat(oi_date), self.session)
            if rej:
                return {'value': None, 'status': 'REJECTED', 'as_of': oi_date, 'reason': rej}
            return {'value': int(oi), 'status': 'OK', 'as_of': oi_date, 'fetched_at': fetched_at, 'reason': None}
        return {'value': None, 'status': 'MISSING', 'as_of': None, 'reason': 'no dated OI vintage before session'}


def _put(store, scope, kind, for_session, value, n, as_of, status, detail, now_iso):
    store.x("INSERT OR REPLACE INTO baselines VALUES (?,?,?,?,?,?,?,?,?,?)",
            (scope, kind, for_session.isoformat(), value, n, as_of.isoformat() if as_of else None, now_iso,
             status, json.dumps(detail, default=str) if not isinstance(detail, str) else detail,
             settings.RULE_VERSION))


def store_session_histogram(store, underlying, session: str, source: str) -> int:
    """Persist the premium histogram of one COMPLETED captured session (COUNTED prints only)."""
    rows = store.q("SELECT p.price*p.size*COALESCE(c.multiplier,100) FROM prints p LEFT JOIN contracts c "
                   "ON c.occ=p.occ WHERE p.underlying=? AND p.session=? AND p.status='COUNTED'",
                   (underlying, session))
    h = histogram(r[0] for r in rows)
    store.x("CREATE TABLE IF NOT EXISTS premium_hist (underlying TEXT, session TEXT, n INTEGER, bins TEXT, "
            "source TEXT, PRIMARY KEY (underlying, session))")
    store.x("INSERT OR REPLACE INTO premium_hist VALUES (?,?,?,?,?)",
            (underlying, session, sum(h.values()), json.dumps(h), source))
    return sum(h.values())


def run_job(store, rest, for_session: date, universe: dict, now_iso: str, bootstrap: bool = False,
            log=print) -> dict:
    """Compute and persist every baseline for `for_session`. universe: {underlying: [occ, ...]}."""
    sessions = completed_sessions(for_session, settings.BASELINE_SESSIONS)
    start, end = sessions[0].isoformat(), sessions[-1].isoformat()
    all_occ = [o for occs in universe.values() for o in occs]
    bars = rest.daily_bars(all_occ, start, (sessions[-1] + timedelta(days=1)).isoformat()) if all_occ else {}
    stats = {'series_ok': 0, 'series_missing': 0, 'quiet': 0, 'names_ok': 0, 'universe': len(all_occ)}
    for occ in all_occ:
        daily = {}
        for b in bars.get(occ, []):
            d = date.fromisoformat(events.ny_dt(events.iso_to_ns(b['t'])).date().isoformat())
            if sessions[0] <= d <= sessions[-1]:
                daily[d] = int(b.get('v') or 0)
                store.x("INSERT OR REPLACE INTO daily_volume VALUES (?,?,?,?,?)",
                        (occ, d.isoformat(), int(b.get('v') or 0), b.get('vw'), 'alpaca_bars'))
        sm = series_median(daily, sessions)
        _put(store, occ, 'series_median_volume', for_session, sm['value'], sm['n'], sm['as_of'], sm['status'],
             sm['reason'] or 'ok', now_iso)
        stats['series_ok' if sm['status'] == 'OK' else 'series_missing'] += 1
        qb = quiet_build(daily, sessions)
        if qb:
            store.x("INSERT OR REPLACE INTO quiet_builds VALUES (?,?,?,?,?)",
                    (occ, for_session.isoformat(), qb['total'], qb['sessions'], json.dumps(qb['daily'])))
            stats['quiet'] += 1

    store.x("CREATE TABLE IF NOT EXISTS premium_hist (underlying TEXT, session TEXT, n INTEGER, bins TEXT, "
            "source TEXT, PRIMARY KEY (underlying, session))")
    if bootstrap:
        _bootstrap_premiums(store, rest, universe, sessions, log)
    for und in universe:
        rows = store.q("SELECT session, bins FROM premium_hist WHERE underlying=? AND session>=? AND session<=? "
                       "AND n>0", (und, start, end))
        hists = [{int(k): v for k, v in json.loads(b).items()} for _, b in rows]
        n = len(hists)
        kind = 'name_premium_p%g' % settings.PREMIUM_PCTL
        if n < settings.BASELINE_MIN_SESSIONS:
            _put(store, und, kind, for_session, None, n, sessions[-1], 'INSUFFICIENT', f'{n} sessions with premium '
                 f'samples < {settings.BASELINE_MIN_SESSIONS}', now_iso)
        else:
            _put(store, und, kind, for_session, pooled_percentile(hists, settings.PREMIUM_PCTL), n,
                 date.fromisoformat(max(s for s, _ in rows)), 'OK', 'ok', now_iso)
            stats['names_ok'] += 1
    store.flush()
    log(f"BASELINE-JOB {for_session}: series OK {stats['series_ok']} / missing {stats['series_missing']} of "
        f"{stats['universe']} · names OK {stats['names_ok']}/{len(universe)} · quiet builds {stats['quiet']}")
    return stats


def _bootstrap_premiums(store, rest, universe, sessions, log) -> None:
    """Bounded REST bootstrap of per-session premium histograms for sessions not yet captured. Uses the
    current universe's contracts only — the coverage denominator is recorded in `source`."""
    mult = dict(store.q("SELECT occ, multiplier FROM contracts"))
    for und, occs in universe.items():
        have = {r[0] for r in store.q("SELECT session FROM premium_hist WHERE underlying=?", (und,))}
        for s in sessions:
            if s.isoformat() in have or not occs:
                continue
            b = xcal.session_bounds(s, events.NY)
            if not b:
                continue
            prem = []
            for occ, r in rest.option_trades(occs, b[0].isoformat(), b[1].isoformat(),
                                             max_pages=settings.BOOTSTRAP_PAGES):
                if conditions.is_cancel(conditions.tags(r.get('c'))):
                    continue
                prem.append(float(r['p']) * int(r['s']) * float(mult.get(occ) or 100))
            if not rest.complete:
                log(f"BOOTSTRAP {und} {s}: page budget hit — session marked partial, not used")
                continue
            h = histogram(prem)
            store.x("INSERT OR REPLACE INTO premium_hist VALUES (?,?,?,?,?)",
                    (und, s.isoformat(), sum(h.values()), json.dumps(h), f'rest_bootstrap:{len(occs)}_contracts'))
