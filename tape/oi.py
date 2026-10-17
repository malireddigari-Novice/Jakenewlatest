"""
OI intervals, buyback-plausibility and possible rolls (flow handoff §7) — aggregate context only.

  interval(occ, old, new)  V = complete volume of the sessions in (old.oi_date, new.oi_date], Δ = OI change;
                           bounds + label from analysis.oi_confirm (oi-recon-v1). Incomplete V → INCONCLUSIVE.
  buyback_alternative(...) an earlier full-coverage call session that was sell-side, BUILT OI, and whose net
                           build is still ≥ BB_RETAIN in published OI, plus a fresh buy-side print BELOW that
                           session's VWAP → "short-call buyback plausible" as an ALTERNATIVE (never a BTC, never
                           a trader's profit; later ask-side trades could equally be new longs or a hedge).
  possible_rolls(...)      same issuer/right/multiplier, old-series OI down + new-series OI up in the SAME vintage,
                           comparable size, nearby print timing, no expiry/exercise/adjustment/correction
                           explanation → POSSIBLE_ROLL with every competing assignment (never an account move).
Session VWAP here is market activity, not anyone's cost basis.
"""
from datetime import date, timedelta

from analysis import oi_confirm
from data import exchange_calendar as xcal
from tape import settings
from tape.side import BUY, SELL


def _vintages(store, occ):
    return store.q("SELECT oi_date, oi FROM oi_vintages WHERE occ=? ORDER BY oi_date", (occ,))


def _sessions_between(d0: date, d1: date) -> list:
    out, d = [], d0 + timedelta(days=1)
    while d <= d1:
        if xcal.is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def interval(store, occ, old_date: str, new_date: str) -> dict:
    vs = dict(_vintages(store, occ))
    if old_date not in vs or new_date not in vs:
        return {'label': 'INCONCLUSIVE', 'reason': 'vintage missing'}
    sess = _sessions_between(date.fromisoformat(old_date), date.fromisoformat(new_date))
    vols = dict(store.q("SELECT session, volume FROM daily_volume WHERE occ=? AND session>? AND session<=?",
                        (occ, old_date, new_date)))
    missing = [s.isoformat() for s in sess if s.isoformat() not in vols]
    if missing:
        return {'label': 'INCONCLUSIVE', 'reason': f'incomplete intervening volume {missing}',
                'old': old_date, 'new': new_date}
    V = sum(vols.get(s.isoformat(), 0) for s in sess)
    rec = oi_confirm.reconcile(vs[old_date], V, vs[new_date])
    return {**rec, 'old': old_date, 'new': new_date, 'sessions': [s.isoformat() for s in sess]}


def _session_stats(store, occ, session):
    rows = store.q("SELECT side, size, price FROM prints WHERE occ=? AND session=? AND status='COUNTED'",
                   (occ, session))
    vol = sum(r[1] for r in rows)
    buy = sum(r[1] for r in rows if r[0] == BUY)
    sell = sum(r[1] for r in rows if r[0] == SELL)
    vwap = (sum(r[1] * r[2] for r in rows) / vol) if vol else None
    return {'vol': vol, 'buy': buy, 'sell': sell, 'vwap': vwap}


def _full_coverage(store, occ, session) -> bool:
    bad = store.q("SELECT COUNT(*) FROM incidents WHERE session=? AND (scope=? OR scope='*' OR scope=?)",
                  (session, occ, occ[:-15]))
    return bad[0][0] == 0


def buyback_alternative(store, occ, right, now_session: str, print_side, print_price) -> dict | None:
    if right != 'C' or print_side != BUY:
        return None
    vs = _vintages(store, occ)
    if len(vs) < 2:
        return None
    current_oi = vs[-1][1]
    lo = (date.fromisoformat(now_session) - timedelta(days=settings.BB_DAYS)).isoformat()
    for i in range(1, len(vs)):
        prev_d, prev_oi = vs[i - 1]
        d, oi = vs[i]
        if d < lo or d >= now_session:
            continue
        st = _session_stats(store, occ, d)
        classified = st['buy'] + st['sell']
        if not st['vol'] or not classified or not _full_coverage(store, occ, d):
            continue
        build = oi - prev_oi
        if (st['sell'] / classified >= settings.BB_SELL_SHARE and build >= settings.BB_BUILD * st['vol']
                and current_oi - prev_oi >= settings.BB_RETAIN * build and st['vwap'] and print_price < st['vwap']):
            return {'label': 'SHORT_CALL_BUYBACK_PLAUSIBLE', 'session': d, 'build': build,
                    'retained': current_oi - prev_oi, 'session_vwap': round(st['vwap'], 4),
                    'text': (f"Alternative: short-call buyback plausible — {d} was sell-side and built {build:,} OI "
                             f"still largely in place; this buy prints below that session's VWAP "
                             f"${st['vwap']:.2f}. Equally possible: new call longs or a hedge.")}
    return None


def possible_rolls(store, underlying, vintage_date: str, contracts: dict) -> list:
    """contracts: {occ: {expiry, right, strike, multiplier, adjusted}}. Returns POSSIBLE_ROLL records."""
    deltas = {}
    for occ, c in contracts.items():
        if c.get('adjusted'):
            continue
        vs = dict(_vintages(store, occ))
        prior = [d for d in vs if d < vintage_date]
        if vintage_date in vs and prior:
            deltas[occ] = vs[vintage_date] - vs[max(prior)]
    downs = {o: d for o, d in deltas.items() if d < 0}
    ups = {o: d for o, d in deltas.items() if d > 0}
    corrected = {r[0] for r in store.q("SELECT DISTINCT occ FROM prints WHERE session=? AND status IN "
                                       "('CANCELLED','CANCEL_RECORD')", (vintage_date,))}
    out = []
    for old, dn in downs.items():
        co = contracts[old]
        if str(co['expiry']) <= vintage_date or old in corrected:
            continue                                  # expiry/exercise or correction explains the decline
        cands = []
        for new, up in ups.items():
            cn = contracts[new]
            if (cn['right'] != co['right'] or cn.get('multiplier') != co.get('multiplier') or new in corrected
                    or new == old):
                continue
            if abs(up - abs(dn)) / max(up, abs(dn)) > settings.ROLL_SIZE_TOL:
                continue
            t_old = store.q("SELECT MIN(event_ns), MAX(event_ns) FROM prints WHERE occ=? AND session=? AND "
                            "status='COUNTED'", (old, vintage_date))[0]
            t_new = store.q("SELECT MIN(event_ns), MAX(event_ns) FROM prints WHERE occ=? AND session=? AND "
                            "status='COUNTED'", (new, vintage_date))[0]
            if None in t_old or None in t_new:
                continue
            gap_s = max(0, max(t_old[0], t_new[0]) - min(t_old[1], t_new[1])) / 1e9
            if gap_s > 300:
                continue
            cands.append({'new': new, 'oi_up': up, 'geometry': _roll_geom(co, cn)})
        if cands:
            out.append({'label': 'POSSIBLE_ROLL', 'underlying': underlying, 'vintage': vintage_date, 'old': old,
                        'oi_down': dn, 'candidates': cands,
                        'text': (f"POSSIBLE_ROLL (not a confirmed account migration): {old} OI {dn:,} while "
                                 f"{len(cands)} candidate destination(s) gained OI in the same vintage.")})
    return out


def _roll_geom(old, new):
    from tape import taxonomy
    return taxonomy.roll_label(old, new)
