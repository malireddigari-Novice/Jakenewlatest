"""
Backtest — replay last week's real Alpaca 1-minute option bars THROUGH the live v2 engine.

How it works (and its honest limits):
  • It reconstructs, per symbol per minute, each near-ATM contract's cumulative volume + mark
    from real historical 1-min option bars (volume + VWAP). That is the exact fresh-flow signal
    the engine consumes — so Layers 1-3 (attention, control, events) run on REAL data.
  • A ReplayFeed stands in for the live Alpaca client; the real AttentionEngine ingests it minute
    by minute under a simulated clock. Entries/exits are captured as "alerts".

  Fidelity caveats (documented, not hidden):
    - 1-MINUTE granularity, not the live ~5s loop → sub-minute bursts and the fast-activation
      path are smoothed; velocity/accel use 1-min steps.
    - Historical bars carry NO bid/ask sizes or quote timestamps, so spreads/sizes/quote-age are
      SYNTHESIZED (spread ~6%, sizes 50, fresh ts) to pass the microstructure gates. Real spreads
      varied; thin-quote/stale-quote rejections that would happen live are not modelled.
    - Expiry: uses each name's same-day 0DTE when its bars exist, else the week's Friday weekly.
    - No live quote-location, so control uses premium + awakening + persistence only.
    - Fills are simulated at the engine's limit price off the bar mark (SHADOW accounting).

Run:  python backtest.py            (full Mon-Fri last week, all Mag-7)
      python backtest.py AAPL NVDA  (subset)
"""
import os
import time
import sys
from datetime import date, datetime, timedelta

import requests

import config
config.DISCORD_WEBHOOK_URL = ''          # never post
config.STATE_FILE = 'bt_state.json'      # throwaway, reset each day (isolate days)
config.COVERAGE_GAP_S = 150               # 1-min replay cadence: one missing bar-minute is not a gap
import notify
import state as _state
_state.save = lambda *a, **k: None       # no disk persistence during replay (in-memory only)
import engine as E
from data.alpaca_client import occ_symbol
from data.market_utils import CST

_H = {'APCA-API-KEY-ID': config.ALPACA_API_KEY, 'APCA-API-SECRET-KEY': config.ALPACA_SECRET_KEY}
_DATA = 'https://data.alpaca.markets'

LAST_FRIDAY = date(2026, 7, 24)   # most-recent validated week's Friday; weeks are generated back from here
DTE_BY_DAY: dict = {}          # day -> {symbol: days-to-expiry used}
INCR = {'AAPL': 2.5, 'MSFT': 5.0, 'AMZN': 2.5, 'GOOGL': 2.5, 'META': 5.0, 'NVDA': 2.5, 'TSLA': 2.5}
BAND = 0.05                              # strike grid half-width around opening spot


def gen_weeks(n_weeks: int, last_friday: date = LAST_FRIDAY):
    """N most-recent Mon-Fri weeks ending at `last_friday`, oldest first."""
    weeks, fri = [], last_friday
    for _ in range(n_weeks):
        mon = fri - timedelta(days=4)
        weeks.append([(mon + timedelta(days=i)).isoformat() for i in range(5)])
        fri -= timedelta(days=7)
    return list(reversed(weeks))


def _get(url, params, _tries=4):
    """GET with retry/backoff — a transient reset must not drop a whole trading day."""
    last = None
    for i in range(_tries):
        try:
            r = requests.get(url, headers=_H, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            last = exc
            time.sleep(1.5 * (i + 1))
    raise last


def _epoch(iso):
    return datetime.fromisoformat(iso.replace('Z', '+00:00')).timestamp()


def stock_bars(sym, day):
    j = _get(f"{_DATA}/v2/stocks/{sym}/bars",
             {'timeframe': '1Min', 'start': f"{day}T13:29:00Z", 'end': f"{day}T20:01:00Z",
              'feed': 'sip', 'limit': 10000, 'sort': 'asc'})
    return [(_epoch(b['t']), float(b['c'])) for b in (j.get('bars') or [])]


def option_bars(occs, day):
    """{occ: [(epoch, cum_vol, mark, low, high)...]} for the RTH session."""
    out = {}
    start, end = f"{day}T13:29:00Z", f"{day}T20:01:00Z"
    for i in range(0, len(occs), 100):
        chunk = occs[i:i + 100]
        page = None
        raw = {occ: [] for occ in chunk}
        while True:
            params = {'symbols': ','.join(chunk), 'timeframe': '1Min', 'start': start,
                      'end': end, 'limit': 10000, 'sort': 'asc'}
            if page:
                params['page_token'] = page
            j = _get(f"{_DATA}/v1beta1/options/bars", params)
            for occ, bars in (j.get('bars') or {}).items():
                raw.setdefault(occ, []).extend(bars)
            page = j.get('next_page_token')
            if not page:
                break
        for occ, bars in raw.items():
            if not bars:
                continue
            series, cum, lo, hi = [], 0, None, None
            for b in sorted(bars, key=lambda x: x['t']):
                cum += int(b['v'])
                mk = float(b['vw'] or b['c'])
                lo = mk if lo is None else min(lo, mk)
                hi = mk if hi is None else max(hi, mk)
                series.append((_epoch(b['t']), cum, mk, lo, hi))
            out[occ] = series
    return out


def _grid(spot, incr):
    lo, hi = spot * (1 - BAND), spot * (1 + BAND)
    k = round(lo / incr) * incr
    strikes = []
    while k <= hi:
        strikes.append(round(k, 2)); k += incr
    return strikes


def _at(series, t):
    """(cum_vol, mark, low, high) at time t = last bar with epoch <= t, else None."""
    hit = None
    for s in series:
        if s[0] <= t:
            hit = s
        else:
            break
    return hit


class ReplayFeed:
    """Stands in for AlpacaDataClient — serves reconstructed history at the current sim time."""

    def __init__(self, day: str):
        self.day = day
        self._t = 0.0
        self.spots: dict = {}       # sym -> [(epoch, spot)]
        self.opt: dict = {}         # sym -> {occ: series}
        self.meta: dict = {}        # sym -> {'expiry': date, 'occ_info': {occ:(strike,side)}}

    def load(self, sym):
        sb = stock_bars(sym, self.day)
        if not sb:
            return False
        self.spots[sym] = sb
        open_spot = sb[0][1]
        incr = INCR[sym]
        d = date.fromisoformat(self.day)
        exp = self._nearest_expiry(sym, d, open_spot, incr)   # TRUE nearest listed expiry
        occs, info = [], {}
        for k in _grid(open_spot, incr):
            for side in ('CALL', 'PUT'):
                occ = occ_symbol(sym, exp, k, side)
                occs.append(occ); info[occ] = (k, side)
        self.opt[sym] = option_bars(occs, self.day)
        self.meta[sym] = {'expiry': exp, 'dte': (exp - d).days, 'occ_info': info}
        return True

    def _nearest_expiry(self, sym, d, spot, incr):
        """
        The nearest LISTED expiry with real 1-min bars on `d` — probing same-day 0DTE first, then
        each following weekday (this week's remaining days, the weekly Friday, next week). Mirrors
        the live engine's get_nearest_expiry: on an expiry day this is a true 0DTE contract; on a
        non-expiry day it is whatever nearest weekly actually trades that day.
        """
        atm = round(spot / incr) * incr
        cands = []
        for off in range(0, 15):
            e = d + timedelta(days=off)
            if e.weekday() < 5:
                cands.append(e)
            if len(cands) >= 8:
                break
        probe = [occ_symbol(sym, e, atm + j * incr, 'CALL') for e in cands for j in (-1, 0, 1)]
        bars = option_bars(probe, self.day)
        for e in cands:
            if any(bars.get(occ_symbol(sym, e, atm + j * incr, 'CALL')) for j in (-1, 0, 1)):
                return e
        return d + timedelta(days=(4 - d.weekday()) % 7)   # fallback: that week's Friday

    def set_time(self, dt):
        self._t = dt.timestamp()

    # ── AlpacaDataClient interface ──
    def login(self): return None
    def verify(self): return True

    def get_spot(self, sym):
        hit = _at(self.spots.get(sym, []), self._t)
        return hit[1] if hit else None

    def get_nearest_expiry(self, sym):
        return self.meta.get(sym, {}).get('expiry')

    def get_option_snapshots(self, sym, expiry, spot, band=None):
        band = (band or config.PREMIUM_BAND_PCT) * 1.5
        lo, hi = spot * (1 - band), spot * (1 + band)
        info = self.meta.get(sym, {}).get('occ_info', {})
        out = {}
        for occ, series in self.opt.get(sym, {}).items():
            strike, side = info[occ]
            if not (lo <= strike <= hi):
                continue
            hit = _at(series, self._t)
            if not hit:
                continue
            _t, cum, mark, low, high = hit
            out[(strike, side)] = {
                'volume': cum, 'mark': mark, 'bid': round(mark * 0.97, 2),
                'ask': round(mark * 1.03, 2), 'bid_size': 50, 'ask_size': 50,
                'quote_ts': datetime.fromtimestamp(self._t, tz=CST).isoformat(),
                'day_low': low, 'day_high': high, 'delta': 0.5, 'gamma': 0.1}
        return out


def run_day(day: str, symbols: list) -> list:
    for f in (config.STATE_FILE, config.STATE_FILE + '.tmp'):   # isolate each day
        if os.path.exists(f):
            os.remove(f)
    feed = ReplayFeed(day)
    loaded = [s for s in symbols if feed.load(s)]
    if not loaded:
        return []
    DTE_BY_DAY[day] = {s: feed.meta[s]['dte'] for s in loaded}
    alerts = []
    d = date.fromisoformat(day)

    # Exits/scales via the notify hooks (they carry reason + pnl); entries via position-diff
    # (the position dict carries wave_id, event class, and entry metrics).
    def rec_exit(kind):
        def f(*a, **k):
            p = a[0] if a else k.get('pos')
            alerts.append({'t': k.get('now'), 'kind': kind, 'sym': p['symbol'], 'side': p['side'],
                           'reason': k['reason'], 'pnl': k['pnl'], 'wave': p.get('wave_id')})
        return f
    notify.entry_card = lambda *a, **k: None
    notify.scale_card, notify.exit_card = rec_exit('SCALE'), rec_exit('EXIT')

    eng = E.AttentionEngine(feed, alpaca_exec=None, schwab=None)
    E.now_cst = lambda: eng._clock
    E.today_cst = lambda: eng._clock.date()

    # Capture every entry the instant it opens (even if it round-trips in the same minute).
    _orig_open = eng._open_wave
    def _wrapped(en, cand, ranked, mm, now):
        before = len(eng.state.get('positions', []))
        _orig_open(en, cand, ranked, mm, now)
        pos = eng.state.get('positions', [])
        if len(pos) > before:
            p = pos[-1]
            alerts.append({'t': now, 'kind': 'ENTER', 'sym': p['symbol'], 'side': p['side'],
                           'strike': p['strike'], 'price': p['entry_price'],
                           'score': p.get('entry_score', 0), 'shock': p.get('entry_z', 0),
                           'share': p.get('entry_share', 0), 'ctrl': p.get('entry_control', 0),
                           'event': p.get('event_class'), 'wave': p.get('wave_id'),
                           'fresh': p.get('freshness'), 'acc': p.get('acc_label'),
                           'shape': p.get('shape'), 'resp': p.get('resp_event')})
    eng._open_wave = _wrapped

    t = CST.localize(datetime(d.year, d.month, d.day, 8, 20))
    end = CST.localize(datetime(d.year, d.month, d.day, 14, 56))
    while t <= end:
        eng._clock = t
        feed.set_time(t)
        eng.poll()
        eng.maybe_eod_flatten(t)
        t += timedelta(minutes=1)
    alerts.sort(key=lambda a: (a['t'], 0 if a['kind'] == 'ENTER' else 1))
    return alerts


def main():
    args = sys.argv[1:]
    n_weeks = 4
    if args and args[0].isdigit():
        n_weeks = int(args[0]); args = args[1:]
    quiet = '--quiet' in args
    args = [a for a in args if a != '--quiet']
    symbols = [s.upper() for s in args] or config.MAG7
    weeks = gen_weeks(n_weeks)
    print(f"MULTI-WEEK BACKTEST  {n_weeks} weeks ({weeks[0][0]} .. {weeks[-1][-1]})  "
          f"symbols={','.join(symbols)}")
    print("Real 1-min Alpaca option bars replayed through the engine. Quotes synthesized; "
          "1-min granularity; SHADOW accounting.\n")

    week_stats, grand = [], []
    for wk in weeks:
        wk_alerts = {}
        for day in wk:
            try:
                a = run_day(day, symbols)
            except Exception as exc:
                print(f"{day}: data/replay error: {exc}"); a = []
            wk_alerts[day] = a
            if not quiet:
                _print_day(day, a)
        st = _week_summary(wk, wk_alerts)
        week_stats.append(st)
        grand.extend([al for d in wk_alerts.values() for al in d])
    _grand_summary(week_stats, grand)


def _stats(alerts):
    entries = [a for a in alerts if a['kind'] == 'ENTER']
    exits = [a for a in alerts if a['kind'] == 'EXIT']
    days = len({a['t'].date() for a in entries}) if entries else 0
    wins = [e for e in exits if e['pnl'] >= 0]
    pnls = [e['pnl'] for e in exits]
    return {'entries': len(entries), 'exits': len(exits), 'wins': len(wins),
            'win_pct': (100 * len(wins) / len(exits)) if exits else 0.0,
            'avg': (sum(pnls) / len(pnls)) if pnls else 0.0,
            'best': max(pnls) if pnls else 0.0, 'worst': min(pnls) if pnls else 0.0,
            'total_pnl': sum(pnls)}


def _week_summary(wk, wk_alerts):
    alerts = [al for d in wk_alerts.values() for al in d]
    s = _stats(alerts)
    label = f"{wk[0]}..{wk[-1]}"
    print("=" * 82)
    print(f"WEEK {label}:  {s['entries']} entries ({s['entries']/5:.1f}/day)  "
          f"win {s['win_pct']:.0f}%  avg {'+' if s['avg']>=0 else ''}{100*s['avg']:.0f}%  "
          f"best {100*s['best']:.0f}%  worst {100*s['worst']:.0f}%")
    print()
    return {'label': label, **s}


def _grand_summary(week_stats, grand):
    g = _stats(grand)
    print("#" * 82)
    print("MULTI-WEEK VALIDATION SUMMARY")
    print("#" * 82)
    print(f"{'week':<24}{'entr':>5}{'/day':>6}{'win%':>6}{'avg%':>7}{'best%':>7}{'worst%':>8}")
    for w in week_stats:
        print(f"{w['label']:<24}{w['entries']:>5}{w['entries']/5:>6.1f}{w['win_pct']:>6.0f}"
              f"{100*w['avg']:>+7.0f}{100*w['best']:>+7.0f}{100*w['worst']:>+8.0f}")
    print("-" * 82)
    nd = len(week_stats) * 5
    print(f"{'ALL WEEKS':<24}{g['entries']:>5}{g['entries']/nd:>6.1f}{g['win_pct']:>6.0f}"
          f"{100*g['avg']:>+7.0f}{100*g['best']:>+7.0f}{100*g['worst']:>+8.0f}")
    profitable = sum(1 for w in week_stats if w['avg'] > 0)
    print(f"\nProfitable weeks: {profitable}/{len(week_stats)}   "
          f"Total closed: {g['exits']}   Overall avg/trade: {'+' if g['avg']>=0 else ''}{100*g['avg']:.1f}%")
    print("Caveat: 1-min granularity, synthesized quotes, SHADOW fills — a directional check, not live P&L.")


def _fmt_t(dt):
    return dt.strftime('%H:%M') if hasattr(dt, 'strftime') else str(dt)


def _print_day(day, alerts):
    wd = date.fromisoformat(day).strftime('%a')
    print("=" * 82)
    print(f"{wd} {day}")
    dte = DTE_BY_DAY.get(day, {})
    if dte:
        print("  expiry used: " + "  ".join(f"{s}={d}DTE" for s, d in dte.items()))
    print("-" * 82)
    entries = [a for a in alerts if a['kind'] == 'ENTER']
    if not entries and not any(a['kind'] == 'EXIT' for a in alerts):
        print("  (no waves reached ACTIVE + led attention — no alerts)")
        return
    for al in alerts:
        if al['kind'] == 'ENTER':
            print(f"  {_fmt_t(al['t'])}  ENTER {al['sym']:<5} {al['side']:<4} {al['strike']:>7g} "
                  f"@ ${al['price']:.2f}  wave={al['wave']}  z={al['shock']:.1f} "
                  f"share={100*al['share']:.0f}% ctrl={al['ctrl']:.2f} "
                  f"resp={100*(al.get('resp') or 0):+.0f}% [{al.get('acc')}/{al.get('shape')}]")
        elif al['kind'] == 'SCALE':
            print(f"  {_fmt_t(al['t'])}   scale {al['sym']:<5} {al['side']:<4}   "
                  f"{al['reason']} (+{100*al['pnl']:.0f}%)  wave={al['wave']}")
        else:
            print(f"  {_fmt_t(al['t'])}   EXIT  {al['sym']:<5} {al['side']:<4}   "
                  f"{al['reason']} ({'+' if al['pnl']>=0 else ''}{100*al['pnl']:.0f}%)  wave={al['wave']}")
    print(f"  -> {len(entries)} primary entr{'y' if len(entries)==1 else 'ies'} this day")


def _summary(all_alerts):
    print("=" * 82)
    entries = [a for day in all_alerts.values() for a in day if a['kind'] == 'ENTER']
    exits = [a for day in all_alerts.values() for a in day if a['kind'] == 'EXIT']
    waves = {e['wave'] for e in entries if e.get('wave')}
    # duplicate entries within a single wave (should be zero by design)
    per_wave = {}
    for e in entries:
        per_wave[e['wave']] = per_wave.get(e['wave'], 0) + 1
    dups = sum(c - 1 for c in per_wave.values() if c > 1)
    reasons = {}
    for e in exits:
        reasons[e['reason']] = reasons.get(e['reason'], 0) + 1
    print("WEEK SUMMARY (wave-centric, per spec §20)")
    print(f"  distinct waves entered : {len(waves)}")
    print(f"  primary entries        : {len(entries)}   (avg {len(entries)/5:.1f}/day; target <= 5/day)")
    print(f"  duplicate in-wave entries: {dups}   (target 0)")
    if exits:
        wins = [e for e in exits if e['pnl'] >= 0]
        avg = sum(e['pnl'] for e in exits) / len(exits)
        print(f"  closed                 : {len(exits)}  win {100*len(wins)/len(exits):.0f}%  "
              f"avg {'+' if avg>=0 else ''}{100*avg:.0f}%  "
              f"best {100*max(e['pnl'] for e in exits):.0f}%  worst {100*min(e['pnl'] for e in exits):.0f}%")
        print(f"  exit reasons           : {', '.join(f'{r}={c}' for r,c in sorted(reasons.items(), key=lambda x:-x[1]))}")


if __name__ == '__main__':
    main()
