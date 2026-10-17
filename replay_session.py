"""
Session campaign replay — the TSLA (and AAPL) control/detection replay (new-spec §1-37, P5).

The single-contract tool (replay_campaign.py) answers "was this ONE option catchable early and cheap?"
This tool answers the different, campaign-level question the spec demands after the TSLA/AAPL misses:

    Replay the whole (ticker, side) campaign poll-by-poll through the REAL analysis modules and show
    exactly WHY the engine left — which module owned the exit, what the incumbent CampaignConfidence
    was at that minute, whether ANOTHER module simultaneously classified the campaign as strengthening
    (the "EXIT while STRENGTHENING" contradiction), and how much convexity the early exit forfeited
    (MFE/MAE measured from ENTRY and from EXIT).

It reuses the live logic — attention_board (Layer 1), per-strike BarVolumeShock (P2, barshock),
event-information contract selection (P4, contract_select), the cross-strike ReversalCluster state
machine (P3, reversal), and the CampaignConfidence hold engine (hold) — so it VALIDATES the actual
detection/hold code, not a re-implementation. It is read-only research: it places no orders and
mutates no state; the analysis modules stay flag-independent here (we call them directly).

Bid/ask/quote-size are not in 1-min bars, so they are synthesized from the bar (mark ± a nominal
spread, deep size) exactly as the backtest does — the executability terms are therefore indicative,
not live. Everything volume/premium/price-path is REAL Alpaca 1-min data.

Usage:
    python replay_session.py TSLA 2026-08-03 CALL
    python replay_session.py TSLA 2026-08-03 CALL --entry 09:45 --exit 10:01
    python replay_session.py AAPL 2026-08-04 CALL --window 2 --incr 2.5 --exp 2026-08-08
"""
import argparse
from datetime import date, datetime

import config
from analysis import attention, barshock, contract_select, flow_response, hold, reversal
from data.alpaca_client import occ_symbol
from data.market_utils import CST
from replay_campaign import candidate_expiries, option_bars, stock_bars

MAG7 = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'META', 'TSLA']
# Near-ATM strike increment per name (used to build the strike surface + the pool proxy).
INCR = {'AAPL': 2.5, 'MSFT': 5.0, 'NVDA': 2.5, 'AMZN': 2.5, 'GOOGL': 2.5, 'META': 5.0, 'TSLA': 2.5}


def _round_to(x, step):
    return round(round(x / step) * step, 2)


def _synth_strike(strike, mk, lo, hi):
    """A strike dict shaped like the live strike surface, with quote fields synthesized from the bar."""
    return {'strike': strike, 'mark': mk, 'bid': round(mk * 0.98, 2), 'ask': round(mk * 1.02, 2),
            'bid_size': 500, 'ask_size': 500, 'day_low': lo, 'day_high': hi}


def load_surface(sym, day, exp, spot0, side, window, incr):
    """Fetch ATM±window option bars for one side; return {strike: [(t, cumV, mk, lo, hi)...]}."""
    atm = _round_to(spot0, incr)
    strikes = [round(atm + i * incr, 2) for i in range(-window, window + 1)]
    out = {}
    for k in strikes:
        bars = option_bars(occ_symbol(sym, exp, k, side), day)
        if bars:
            out[k] = bars
    return out


def _series_by_minute(surface):
    """Index each strike's bar series by minute-epoch → {t: {strike: (cumV, mk, lo, hi)}}, plus the
    sorted list of all minutes and, per strike, the trailing per-minute FRESH-volume series."""
    minutes = sorted({b[0] for s in surface.values() for b in s})
    per_min = {t: {} for t in minutes}
    fresh_hist = {k: [] for k in surface}      # strike -> [fresh vol per elapsed minute]
    prev_cum = {k: 0 for k in surface}
    marks_hist = {k: [] for k in surface}      # strike -> [(t, mk)...]
    for t in minutes:
        for k, s in surface.items():
            row = next((b for b in s if b[0] == t), None)
            if row is None:
                fresh_hist[k].append(0)
                continue
            _, cum, mk, lo, hi = row
            fresh = max(0, cum - prev_cum[k]); prev_cum[k] = cum
            fresh_hist[k].append(fresh)
            marks_hist[k].append((t, mk))
            per_min[t][k] = (cum, mk, lo, hi, fresh)
    return minutes, per_min, fresh_hist, marks_hist


def _pool_premium(day, exp, spot_series):
    """Per-minute MAG7 fresh-premium pool proxy: each name's ATM call + ATM put fresh notional, and
    its call-vs-put control. Returns {t: {sym: {'premium','control_share','control_side'}}}."""
    pools = {}      # sym -> (minutes, per_min, fresh_hist)  for that name's 2 ATM contracts
    for sym in MAG7:
        ss = spot_series.get(sym) or []
        if not ss:
            continue
        spot0 = ss[0][1]
        atm = _round_to(spot0, INCR[sym])
        surf = {}
        for side in ('CALL', 'PUT'):
            bars = option_bars(occ_symbol(sym, exp, atm, side), day)
            if bars:
                surf[(side, atm)] = bars
        if surf:
            pools[sym] = surf
    # reduce to per-minute fresh notional per side
    by_min = {}
    prev = {sym: {'CALL': 0, 'PUT': 0} for sym in pools}
    all_min = sorted({b[0] for surf in pools.values() for s in surf.values() for b in s})
    for t in all_min:
        row = {}
        for sym, surf in pools.items():
            c = p = 0.0
            for (side, k), s in surf.items():
                b = next((x for x in s if x[0] == t), None)
                if not b:
                    continue
                _, cum, mk, _lo, _hi = b
                fresh = max(0, cum - prev[sym][side]); prev[sym][side] = cum
                notl = fresh * mk * 100
                if side == 'CALL':
                    c += notl
                else:
                    p += notl
            tot = c + p
            side = 'CALL' if c >= p else 'PUT'
            row[sym] = {'premium': tot, 'control_share': (max(c, p) / tot if tot > 0 else 0.5),
                        'control_side': (side if tot > 0 else None)}
        by_min[t] = row
    return by_min


def _hh(t):
    return datetime.fromtimestamp(t, tz=CST).strftime('%H:%M')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('symbol'); ap.add_argument('day'); ap.add_argument('side')
    ap.add_argument('--entry'); ap.add_argument('--exit', dest='exit_t')
    ap.add_argument('--exp'); ap.add_argument('--window', type=int, default=config.EVENT_SELECT_WINDOW)
    ap.add_argument('--incr', type=float, default=None)
    a = ap.parse_args()
    sym, day, side = a.symbol.upper(), a.day, a.side.upper()
    opp = 'PUT' if side == 'CALL' else 'CALL'
    incr = a.incr or INCR.get(sym, 2.5)

    # spot series for every name (target first) — the pool needs all 7.
    print(f"loading spot series for MAG7 ({day}) ...")
    spot_series = {s: stock_bars(s, day) for s in MAG7}
    tsla_spots = spot_series.get(sym) or []
    if not tsla_spots:
        print(f"no stock bars for {sym} on {day}."); return
    spot0 = tsla_spots[0][1]
    exps = [date.fromisoformat(a.exp)] if a.exp else candidate_expiries(sym, day)

    # probe candidate expiries (same-day 0DTE → that week's Friday → next Friday) until one has bars
    exp = dom_surf = opp_surf = None
    for e in exps:
        print(f"loading {sym} strike surface (ATM±{a.window} @ {incr}) both sides, exp {e} ...")
        ds = load_surface(sym, day, e, spot0, side, a.window, incr)
        if ds:
            exp, dom_surf = e, ds
            opp_surf = load_surface(sym, day, e, spot0, opp, a.window, incr)
            break
    if not dom_surf:
        print(f"no {side} option bars for {sym} on {day} for any probed expiry ({exps})."); return
    opp_surf = opp_surf or {}
    print("loading MAG7 fresh-premium pool ...")
    pool_by_min = _pool_premium(day, exp, spot_series)

    dom_min, dom_pm, dom_fresh, dom_marks = _series_by_minute(dom_surf)
    opp_min, opp_pm, opp_fresh, opp_marks = _series_by_minute(opp_surf)

    def spot_at(t):
        hit = None
        for s in tsla_spots:
            if s[0] <= t:
                hit = s[1]
            else:
                break
        return hit

    # ── per-minute reconstruction ─────────────────────────────────────────────────────────────
    print(f"\nREPLAY {sym} {side} campaign  {day}  exp {exp}  (dte {(exp - date.fromisoformat(day)).days})")
    hdr = (f"{'time':>5} {'freshC$':>9} {'freshP$':>9} {'ctrl':>5} {'shr':>4} {'atn':>5} {'rk':>3} "
           f"{'pool%':>6} {'sel':>7} {'selMk':>6} {'accept':>10} {'revState':>26} {'campSt':>12} {'conf':>5}")
    print(hdr); print('-' * len(hdr))

    prev_pool = prev_pool2 = None
    clus = reversal.new_cluster(sym, side)
    conf = None; entered = False; entry_t = None; entry_mk = None; entry_strike = None; entry_conf = None
    exit_t = None; exit_owner = None; exit_reason = None
    conf_state = 'PRE'
    peak_since_entry = mae_since_entry = None
    rows_out = []
    contra_events = []      # minutes where an exit fired while hold said strengthening

    entry_forced = a.entry
    exit_forced = a.exit_t

    for t in dom_min:
        hh = _hh(t)
        spot = spot_at(t) or spot0
        # fresh premium each side (sum over surface strikes at this minute)
        freshC = sum(v[4] * v[1] * 100 for v in dom_pm[t].values()) if side == 'CALL' \
            else sum(v[4] * v[1] * 100 for v in opp_pm.get(t, {}).values())
        freshP = sum(v[4] * v[1] * 100 for v in opp_pm.get(t, {}).values()) if side == 'CALL' \
            else sum(v[4] * v[1] * 100 for v in dom_pm[t].values())
        dom_prem = freshC if side == 'CALL' else freshP
        opp_prem = freshP if side == 'CALL' else freshC
        tot = dom_prem + opp_prem
        ctrl_share = (dom_prem / tot) if tot > 0 else 0.5
        ctrl_side = side if dom_prem >= opp_prem else opp

        # per-strike BarVolumeShock over the dominant side (P2) → dict keyed by strike
        di = _idx(dom_min, t) + 1
        shk = {}
        for k in dom_surf:
            mk = dom_pm[t].get(k, (None, None))[1]
            shk[k] = barshock.bar_shock(dom_fresh[k][:di], mk)
        # event-information contract selection (P4)
        side_strikes = [_synth_strike(k, dom_pm[t][k][1], dom_pm[t][k][2], dom_pm[t][k][3])
                        for k in dom_surf if k in dom_pm[t]]
        best = contract_select.select(side, side_strikes, spot, shk) if side_strikes else None
        sel_k = best['strike'] if best else None
        sel_mk = best['mark'] if best else None

        # premium acceptance on the selected contract (tuple marks)
        accept = 'n/a'
        if sel_k is not None:
            mv = [fv for fv in dom_fresh[sel_k][:di]]
            mh = [pt for pt in dom_marks[sel_k] if pt[0] <= t]
            accept = flow_response.premium_acceptance(mv, mh)['label']

        # opposite-side cross-strike evidence → ReversalCluster (P3)
        opp_shk = {}
        oi = _idx(opp_min, t) + 1
        for k in opp_surf:
            upto = opp_fresh[k][:oi]
            mk = opp_pm.get(t, {}).get(k, (None, None, None, None, None))[1]
            opp_shk[k] = barshock.bar_shock(upto, mk)
        opp_abnormal = any(s['significant'] for s in opp_shk.values())
        opp_cross = barshock.cluster_shock([s['shock'] for s in opp_shk.values()]) >= config.BARSHOCK_CLUSTER_MIN
        opp_control = (opp_prem / tot) if tot > 0 else 0.0
        opp_accept_ok = False
        if opp_surf:
            ok = next((k for k in opp_surf if opp_shk.get(k, {}).get('significant')), None)
            if ok is not None:
                mv = [fv for fv in opp_fresh[ok][:_idx(opp_min, t) + 1]]
                mh = [pt for pt in opp_marks[ok] if pt[0] <= t]
                opp_accept_ok = flow_response.premium_acceptance(mv, mh)['label'] == 'ABSORPTION'
        # incumbent progress fail: selected-contract premium making lower lows recently
        prog_fail = False
        if entered and best and peak_since_entry:
            prog_fail = sel_mk is not None and sel_mk < peak_since_entry * 0.9
        clus = reversal.update(clus, {
            'opp_abnormal': opp_abnormal, 'opp_control': opp_control,
            'opp_premium_accept': opp_accept_ok, 'cross_strike': opp_cross,
            'incumbent_progress_fail': prog_fail,
            'opp_strike': next((k for k in opp_surf if opp_shk.get(k, {}).get('significant')), None),
        }, t)

        # ── MAG7 attention board (Layer 1) ──
        pool = pool_by_min.get(t, {})
        cur = {s: {'premium': pool.get(s, {}).get('premium', 0.0),
                   'control_share': pool.get(s, {}).get('control_share'),
                   'control_side': pool.get(s, {}).get('control_side'),
                   'low_score': (best['low_score'] if (s == sym and best) else None)}
               for s in pool}
        board = attention.attention_board(
            cur, {s: v['premium'] for s, v in (prev_pool or {}).items()},
            {s: v['premium'] for s, v in (prev_pool2 or {}).items()},
            score_min=config.ATTENTION_SCORE_MIN)
        prev_pool2 = prev_pool; prev_pool = pool
        me = (board.get('by_symbol') or {}).get(sym, {})
        atn = me.get('attention_score'); rank = me.get('rank'); pshare = me.get('share')

        # ── entry ──
        if not entered:
            do_entry = (hh == entry_forced) if entry_forced else (
                rank == 1 and ctrl_side == side and dom_prem >= 200_000)
            if do_entry and best:
                entered = True; entry_t = t; entry_mk = sel_mk; entry_strike = sel_k
                conf = hold.initial_confidence(pshare or 0.0, ctrl_share, dom_prem)
                entry_conf = conf
                conf_state = 'ENTERED'
                peak_since_entry = mae_since_entry = sel_mk

        camp_strengthening = False
        # ── hold: advance CampaignConfidence each poll after entry ──
        if entered and exit_t is None:
            if sel_mk is not None:
                peak_since_entry = max(peak_since_entry or sel_mk, sel_mk)
                mae_since_entry = min(mae_since_entry or sel_mk, sel_mk)
            mv = [fv for fv in dom_fresh[sel_k or entry_strike][:di]]
            mh = [pt for pt in dom_marks[sel_k or entry_strike] if pt[0] <= t]
            smooth = hold.premium_smoothness(mh)
            hlq = hold.higher_low_quality(mh)
            velocity = (mv[-1] - mv[-2]) if len(mv) >= 2 else 0
            reacc = velocity > 0 and dom_prem >= 150_000
            f = {
                'control_ok': ctrl_share >= 0.55,
                'opp_strong': (clus['state'] in ('REVERSAL_CLUSTER_SUSTAINED', 'REVERSAL_ACTIVATED')),
                'dist_high': accept == 'REJECTION',
                'progressing': not prog_fail,
                'higher_low': hlq >= 0.5,
                'reaccelerating': reacc, 'active': dom_prem >= 300_000,
                'smoothness': smooth, 'higher_low_q': hlq, 'control': ctrl_share,
                'self_sust': 0.0, 'cont': 0.0, 'dist_prob': 1.0 if accept == 'REJECTION' else 0.0,
                'opp': opp_control, 'confidence': conf,
            }
            rotation_active = (rank is not None and rank > config.ATTENTION_EXIT_ROTATE_RANK)
            conf, cause = hold.confidence_step(conf, f, rotation_active)
            camp_strengthening = bool(reacc or f['active'])

            # ── exit ownership (deterministic precedence: reversal → hold) ──
            rev_out = reversal.outcome(clus, opp_qualifies=(opp_control >= 0.55 and opp_abnormal))
            if rev_out in ('EXIT_FLAT', 'EXIT_REVERSE'):
                exit_t = t; exit_owner = 'REVERSAL'; exit_reason = rev_out; conf_state = 'EXITED'
            elif conf < config.HOLD_EXIT_THRESHOLD:
                exit_t = t; exit_owner = 'HOLD_CONFIDENCE'
                exit_reason = hold.exit_reason_from(cause, f); conf_state = 'EXITED'
            else:
                conf_state = 'HOLD'
            if exit_t == t and camp_strengthening:
                contra_events.append((hh, exit_owner, exit_reason, round(conf, 3)))

        rows_out.append((t, sel_k, sel_mk))
        print(f"{hh:>5} {freshC:>9,.0f} {freshP:>9,.0f} {ctrl_side[:4]:>5} {ctrl_share:>4.2f} "
              f"{(atn if atn is not None else 0):>5.1f} {(rank or 0):>3d} {(pshare or 0)*100:>5.1f}% "
              f"{(sel_k if sel_k else 0):>7g} {(sel_mk or 0):>6.2f} {str(accept):>10} "
              f"{clus['state']:>26} {conf_state:>12} {(conf if conf is not None else 0):>5.2f}")
        if exit_t == t:
            break

    # ── diagnosis ────────────────────────────────────────────────────────────────────────────
    print("\n== diagnosis ==")
    if not entered:
        print("  never entered (no minute satisfied the entry condition)."); return
    # selected-contract premium path for MFE/MAE (use the entry strike throughout for a stable path)
    path = [(t, dom_pm[t].get(entry_strike, (None, None))[1]) for t in dom_min]
    path = [(t, mk) for t, mk in path if mk is not None]
    from_entry = [mk for t, mk in path if t >= entry_t]
    from_exit = [mk for t, mk in path if exit_t and t >= exit_t]
    print(f"  entry : {_hh(entry_t)}  strike {entry_strike:g}  mark {entry_mk:.2f}  "
          f"conf@entry {entry_conf:.2f}  (base {config.CONF_INIT} + incumbent-strength bonus)")
    if exit_t:
        exit_mk = dom_pm[exit_t].get(entry_strike, (None, None, None))[1] or entry_mk
        held = int((exit_t - entry_t) / 60)
        print(f"  EXIT  : {_hh(exit_t)}  after {held} min  owner={exit_owner}  reason={exit_reason}  "
              f"mark {exit_mk:.2f}  P&L {100*(exit_mk/entry_mk-1):+.0f}%")
    else:
        print("  no exit fired in the window (campaign held to the last bar).")
    if from_entry:
        pk, lo = max(from_entry), min(from_entry)
        print(f"  MFE/MAE from ENTRY : +{100*(pk/entry_mk-1):.0f}% / {100*(lo/entry_mk-1):+.0f}%  "
              f"(peak {pk:.2f}, trough {lo:.2f})")
    if from_exit and exit_t:
        exit_mk = dom_pm[exit_t].get(entry_strike, (None, None, None))[1] or entry_mk
        pk, lo = max(from_exit), min(from_exit)
        forfeit = 100 * (pk / exit_mk - 1)
        print(f"  MFE/MAE from EXIT  : +{100*(pk/exit_mk-1):.0f}% / {100*(lo/exit_mk-1):+.0f}%  "
              f"→ CONVEXITY FORFEITED by exiting early ≈ +{forfeit:.0f}% (peak after exit {pk:.2f})")
    print("\n  -- EXIT-while-STRENGTHENING contradiction check --")
    if contra_events:
        for hh, owner, reason, c in contra_events:
            print(f"    {hh}: {owner} requested exit ({reason}) at conf {c} WHILE the hold engine "
                  f"read the campaign as STRENGTHENING (reaccelerating / active). CONTRADICTION.")
        print("    → one authoritative campaign state is required; execution must read the same "
              "snapshot the lifecycle labeler does (spec §: deterministic ordering).")
    else:
        print("    none — no minute exited while simultaneously reading as strengthening.")


def _idx(minutes, t):
    """Index of minute t within the sorted minutes list (contract's elapsed-minute count)."""
    lo, hi = 0, len(minutes)
    while lo < hi:
        mid = (lo + hi) // 2
        if minutes[mid] < t:
            lo = mid + 1
        else:
            hi = mid
    return lo


if __name__ == '__main__':
    main()
