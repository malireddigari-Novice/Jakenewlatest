"""Acceptance checks for the campaign-flow policy (Logic for Jake.txt §20, items 1-38) plus pipeline
end-to-end checks. All data below is SYNTHETIC test data; tickers/prices are constructed, not market history."""
import os
import sys
import tempfile
from datetime import date, datetime

import pytz

os.environ.setdefault('CF_MODE', 'SHADOW')
from campaign_flow import board as boardmod
from campaign_flow import calendar_ny as cal
from campaign_flow import cards
from campaign_flow import clusters
from campaign_flow import diagnostics
from campaign_flow import oi_ref
from campaign_flow import settings as S
from campaign_flow import shock
from campaign_flow import turnover
from campaign_flow import value_gate
from campaign_flow.journal import Journal
from campaign_flow.model import contract, series_key, window_id
from campaign_flow.policy import Router

NY = pytz.timezone('America/New_York')
D = date(2026, 10, 19)                                   # Monday, a regular session
T0 = NY.localize(datetime(2026, 10, 19, 10, 0)).timestamp()
EXP = '2026-10-23'
FAILS = []


def check(n, cond, msg=''):
    print(f"  {'ok ' if cond else 'FAIL'} [{n}] {msg}")
    if not cond:
        FAILS.append((n, msg))


def refs_for(con, band, start, n=30):
    k = list(series_key(con))
    if band == 'LOW':
        px = [5.0] * n
    elif band == 'MIDDLE':
        px = [1.0] * (n // 2) + [5.0] * (n - n // 2)
    elif band == 'HIGH':
        px = [1.0] * n
    else:
        px = [5.0] * 5
    return [{'series': k, 'ts': start - 3600 - i, 'price': p, 'basis': 'TRADE'} for i, p in enumerate(px)]


def W(strike, start, *, right='C', exp=EXP, t='AAPL', vol=200, bins=None, prints=5, near=None, base=50.0,
      ps=2.0, pe=2.2, spot=None, cum=None, largest=None, band='LOW', cs='UNAVAILABLE', dur=60, iv=None):
    con = contract(t, right, strike, exp)
    w = {'contract': con, 'start': float(start), 'end': float(start + dur), 'volume': vol,
         'bins': bins if bins is not None else [int(vol * 0.6), int(vol * 0.25), vol - int(vol * 0.6) - int(vol * 0.25)],
         'prints': prints, 'near_ask': near if near is not None else int(vol * 0.8), 'baseline': base,
         'largest_print': largest, 'prem_start': ps, 'prem_end': pe, 'event_premium': 2.1,
         'spot': spot if spot is not None else float(strike), 'iv': iv, 'secs_to_last_trade': None,
         'cum_volume': cum, 'complex_status': cs, 'available_ts': float(start + dur)}
    w['value'] = value_gate.classify(con, 2.1, refs_for(con, band, start), w['start'], 'TRADE')
    w['id'] = window_id(w)
    return w


def items(ws, now, mem=None, coh=None):
    valid, _ = shock.validate_windows(ws, now)
    return [{'w': w, 'q': shock.qualify(w, now), 'res': turnover.resemblance(w, (mem or {}).get(w['id']), coh)}
            for w in valid]


def snap(t='AAPL', ts=None, bull=False, bear=False, exps=(EXP,), complete=True, synced=True, evidence=True):
    return {'ticker': t, 'available_ts': ts,
            'coverage': {'expirations': list(exps), 'rights': {e: ['C', 'P'] for e in exps},
                         'strikes_complete': complete, 'trade_quote_synced': synced},
            'underlying': {'bullish': bull, 'bearish': bear,
                           'evidence': ({'rule': 'TEST_RULE', 'value': 0.5 if bull else -0.5} if evidence else {})}}


def choice(strike, ts, right='C', exp=EXP, bid=2.0, ask=2.1, t='AAPL', vol=1000):
    return {'contract': contract(t, right, strike, exp),
            'quote': {'bid': bid, 'ask': ask, 'bid_size': 10, 'ask_size': 10, 'ts': ts, 'feed': 'opra'},
            'day_volume': vol}


def jr():
    return Journal(tempfile.mktemp(suffix='.db'))


def call_cluster(t0, strikes=(345.0, 347.5), n=2, spot=346.0, right='C', **kw):
    out = []
    for i in range(n):
        for k in strikes:
            out.append(W(k, t0 + i * 60, right=right, spot=spot, **kw))
    return out


def cand(eid, ts, ws, *, direction='BULLISH', bull=True, bear=False, rs=0.40, **kw):
    right = 'C' if direction == 'BULLISH' else 'P'
    return {'event_id': eid, 'ts': ts, 'ticker': 'AAPL', 'direction': direction,
            'snapshot': snap(ts=ts, bull=bull, bear=bear), 'items': items(ws, ts),
            'choices': [choice(345.0, ts, right=right), choice(347.5, ts, right=right, bid=2.0, ask=2.2)],
            'route_score': rs, 'attention_score': 80, 'stock_price': 346.0, **kw}


print('── §3 value gate ──')
con = contract('AAPL', 'C', 345, EXP)
other = contract('AAPL', 'C', 340, EXP)
refs = [{'series': list(series_key(other)), 'ts': T0 - 100 - i, 'price': 9.0, 'basis': 'TRADE'} for i in range(40)]
refs += [{'series': list(series_key(con)), 'ts': T0 + 10 + i, 'price': 9.0, 'basis': 'TRADE'} for i in range(40)]
v = value_gate.classify(con, 2.9, refs, T0, 'TRADE')
check(1, v['n'] == 0 and v['band'] == 'UNRESOLVED' and v['excluded']['OTHER_SERIES'] == 40
      and v['excluded']['NOT_BEFORE_WINDOW'] == 40, '340C history and future marks are never applied to 345C')
own = [{'series': list(series_key(con)), 'ts': T0 - 10 - i, 'price': p, 'basis': 'TRADE'}
       for i, p in enumerate([2.9] * 2 + [3.0] * 18 + [2.0] * 2)]
v = value_gate.classify(con, 2.9, own, T0, 'TRADE')
check(1, v['n'] == 22 and abs(v['pct'] - (2 + 1) / 22) < 1e-6 and v['band'] == 'LOW' and v['latest_ts'] == T0 - 10,
      f"empirical percentile = (below + half equal)/n = {v['pct']:.4f}, provenance kept")
for band, want in (('MIDDLE', 'PREMIUM_OUTSIDE_LOW_VALUE_BAND'), ('HIGH', 'HIGH_VALUE_FLOW_SELL_OR_CLOSE_POSSIBLE'),
                   ('FEW', 'EXACT_CONTRACT_VALUE_HISTORY_MISSING')):
    w = W(345, T0, band=band)
    q = shock.qualify(w, T0 + 60)
    check(2, not q['eligible'] and want in q['reasons'], f"{band} value → no buy attention ({want})")
ws = [W(k, T0 + i * 60, spot=346, band='MIDDLE') for i in range(3) for k in (345.0, 347.5)]
r = Router(jr()).propose(cand('c-mid', T0 + 200, ws))
check(2, r['decision'] == 'WATCH' and 'NO_VERIFIED_CLUSTER' in r['reasons'], 'middle-band flow can never form an entry')

print('── §4 shock qualification ──')
w = W(345, T0, bins=[40, 40, 40, 40, 40])
q = shock.qualify(w, T0 + 60)
check(19, not q['eligible'] and 'PERSISTENT_OR_DIFFUSE_BACKGROUND_EXCLUDED' in q['reasons'],
      'flat 20/20/20/20/20 shape is background even at large volume')
w2 = W(345, T0, bins=[40, 40, 40, 40, 40], largest=80)
check(4, shock.qualify(w2, T0 + 60)['concentration'] == 'B_LARGEST_PRINT', 'largest print >= 35% qualifies (rule B)')
w3 = W(345, T0, bins=None)
w3['bins'] = None
check(4, 'MISSING_EVENT_SHAPE_EXCLUDED' in shock.qualify(w3, T0 + 60)['reasons'], 'missing shape evidence is excluded')
w4 = W(345, T0, ps=2.2, pe=2.2)
q4 = shock.qualify(w4, T0 + 60)
check(32, q4['eligible'] and not q4['accepted'] and 'FLOW_WITHOUT_PREMIUM_ACCEPTANCE_WATCH' in q4['logs'],
      'flat premium: attention but no accepted control')
w5 = W(345, T0, near=100)
check(16, 'NEAR_ASK_BELOW_MIN' in shock.qualify(w5, T0 + 60)['reasons'], 'non-aggressive (near-ask < 60%) flow is not a shock')
w6 = W(345, T0, cs='MIXED')
check(28, 'KNOWN_COMPLEX_LEG_CONTAMINATION' in shock.qualify(w6, T0 + 60)['reasons'],
      'known complex legs exclude the whole window')
check(28, 'COMPLEX_LEG_STATUS_UNAVAILABLE' in shock.qualify(W(345, T0), T0 + 60)['logs'],
      'unavailable complex classification stays eligible and is logged')
mixed = [W(k, T0 + i * 60, spot=346, cs='MIXED') for i in range(3) for k in (345.0, 347.5)]
a = clusters.assess(snap(ts=T0 + 200, bull=True), items(mixed, T0 + 200), T0 + 200)
check(28, a['state'] == 'WATCH', 'complex-leg windows cannot create directional control')

print('── §2 window validation ──')
a1 = W(345, T0, vol=200, cum=1000)
a2 = W(345, T0 + 30, vol=200, cum=1200)                      # overlaps a1
valid, rej = shock.validate_windows([a1, a2], T0 + 200)
check(20, len(valid) == 1 and rej and 'OVERLAPPING_WINDOW' in rej[0][1], 'an overlapping window cannot reuse the same prints')
dup = dict(a1)
valid, rej = shock.validate_windows([a1, dup], T0 + 200)
check(20, len(valid) == 1 and 'DUPLICATE_WINDOW' in rej[0][1], 'duplicate windows rejected')
b1 = W(345, T0, vol=200, cum=1000)
b2 = W(345, T0 + 60, vol=200, cum=1100)                     # contiguous, cum advanced only 100
valid, rej = shock.validate_windows([b1, b2], T0 + 200)
check(20, len(valid) == 1 and 'CUMULATIVE_VOLUME_INCONSISTENT' in rej[0][1], 'cumulative volume must advance with incremental volume')
fut = W(345, T0 + 300)
valid, rej = shock.validate_windows([fut], T0 + 100)
check(17, not valid and 'FUTURE_WINDOW' in rej[0][1], 'future windows are rejected')
bad = W(345, T0, vol=200, bins=[100, 50, 10])
valid, rej = shock.validate_windows([bad], T0 + 100)
check(20, not valid and 'BINS_DO_NOT_SUM_TO_WINDOW_VOLUME' in rej[0][1], 'bins must sum to the window volume')

print('── §5 clusters ──')
now = T0 + 200
one = [W(345, T0 + i * 60, spot=346) for i in range(2)]
check(15, not clusters.find(items(one, now), 'C', now), 'one strike in two windows is not a cluster')
three = [W(345, T0 + i * 60, spot=346) for i in range(3)]
cl = clusters.find(items(three, now), 'C', now)
check(15, len(cl) == 1 and cl[0]['kind'] == 'SAME_STRIKE', 'one strike needs three distinct completed windows')
single = [W(345, T0, spot=346)]
a = clusters.assess(snap(ts=now, bull=True), items(single, now), now)
b = boardmod.build([(it['w'], it['q'], it['res']) for it in items(single, now)], now, {'AAPL': a['state']})
check(23, b['rows']['AAPL']['ticker_raw'] > 0 and a['state'] == 'WATCH', 'a single shock ranks but stays WATCH')
pair = call_cluster(T0, n=2)
a = clusters.assess(snap(ts=now, bull=True), items(pair, now), now)
check(13, a['state'] == 'BULLISH_CONTROL' and a['clusters']['C'][0]['kind'] == 'PAIR', 'local pair in two windows = control')
far = [W(k, T0 + i * 60, spot=346) for i in range(2) for k in (345.0, 360.0)]       # 15/346 = 4.3% apart
check(21, not clusters.find(items(far, now), 'C', now), 'disjoint strike neighbourhoods cannot form a pair')
cross = [W(345.0, T0 + i * 60, spot=346, exp=EXP if i % 2 else '2026-10-30') for i in range(3)]
check(21, not clusters.find(items(cross, now), 'C', now), 'different expirations are never pooled')
check(17, clusters.assess(snap(ts=now, bull=False), items(pair, now), now)['state'] == 'WATCH',
      'no independent bullish underlying confirmation → WATCH')
check(17, 'UNDERLYING_CONFIRMATION_EVIDENCE_MISSING' in
      clusters.assess(snap(ts=now, bull=True, evidence=False), items(pair, now), now)['reasons'],
      'a bare boolean without upstream evidence is not confirmation')
both = pair + call_cluster(T0, strikes=(340.0, 342.5), right='P', n=2)
check(16, clusters.assess(snap(ts=now, bull=True, bear=True), items(both, now), now)['state'] == 'CONTESTED',
      'both sides clustering = CONTESTED')
for kw, why in (({'complete': False}, 'INCOMPLETE_STRIKE_COVERAGE'),
                ({'synced': False}, 'INCOMPLETE_TRADE_QUOTE_OR_EXPIRY_COVERAGE'),
                ({'exps': ('2026-10-30',)}, 'INCOMPLETE_TRADE_QUOTE_OR_EXPIRY_COVERAGE')):
    a = clusters.assess(snap(ts=now, bull=True, **kw), items(pair, now), now)
    check(22, a['state'] == 'WATCH' and why in a['reasons'], f'fails closed: {why}')
a = clusters.assess(snap(ts=now - 120, bull=True), items(pair, now), now)
check(16, a['state'] == 'WATCH' and 'STALE_FLOW_SNAPSHOT' in a['reasons'], 'stale snapshot cannot certify')
check(18, not clusters.find(items(pair, T0 + 120 + 400), 'C', T0 + 120 + 400), 'a cluster older than 300 s is inactive')

print('── §6/§7 board and turnover ──')
mem = {'prev_volume': 10000, 'oi_current': 10000, 'oi_earlier': 0, 'available_ts': T0 - 3600}
w1 = W(345, T0, vol=10000, cum=10000, bins=[8000, 1000, 1000])
w2 = W(345, T0 + 60, vol=1000, cum=11000, bins=[800, 100, 100])
r1, r2 = turnover.resemblance(w1, mem), turnover.resemblance(w2, mem)
check(24, r1['resemblance'] == 1.0 and 'PRIOR_SESSION_POSITION_TURNOVER_POSSIBLE' in r1['labels'],
      'previous 10k volume / 10k OI build → first 10k window full resemblance')
check(25, r2['resemblance'] == 0.0, 'the next 1,000 contracts are beyond the match budget')
w3 = W(345, T0, vol=2000, cum=11000, bins=[1200, 500, 300])
check(25, turnover.resemblance(w3, mem)['resemblance'] == 0.5, 'only the overlapping part of a window is allocated')
half = dict(mem, oi_earlier=None)
check(24, turnover.resemblance(w1, half)['resemblance'] == 0.5, 'without the earlier OI: half-strength evidence')
late = dict(mem, available_ts=T0 + 30)
check(31, turnover.resemblance(w1, late)['resemblance'] == 0.0, 'history unavailable at the window cannot be applied')
check(31, 'OPEN_CLOSE_UNRESOLVED' in r1['labels'] and r1['historical'] <= 1, 'resemblance is labelled unresolved, not a closing probability')
z = W(345, T0 + 120, exp='2026-10-19', vol=500, cum=1500, bins=[300, 100, 100])
coh = {'window_id': 'x', 'volume': 1000, 'anchor_cum': 1000, 'end': T0 + 60, 'session': '2026-10-19'}
rz = turnover.resemblance(z, None, coh)
check(30, rz['intraday'] == 0.5 and 'INTRADAY_POSITION_TURNOVER_POSSIBLE' in rz['labels'],
      '0DTE matches an earlier same-day cohort at half weight, no intraday OI asserted')
check(30, turnover.resemblance(z, None, None)['resemblance'] == 0.0, 'missing cohort leaves scoring unchanged')
ev = []
for t, vol, rs in (('AAPL', 400, 0.9), ('MSFT', 300, 0.0)):
    w = W(345, T0, t=t, vol=vol, base=50, bins=[int(vol * .6), int(vol * .25), vol - int(vol * .6) - int(vol * .25)])
    ev.append((w, shock.qualify(w, T0 + 60), {'resemblance': rs, 'labels': ['OPEN_CLOSE_UNRESOLVED'] if rs else []}))
b = boardmod.build(ev, T0 + 60)
check(29, b['rows']['AAPL']['rank_raw'] == 1 and b['rows']['AAPL']['rank_discounted'] == 2
      and not b['scenario_leader_agrees'] and 'LEADER_SCENARIO_DISAGREEMENT' in b['labels'],
      'raw and discounted ranks both exposed; leader disagreement labelled')
put = W(340, T0, t='MSFT', right='P', vol=250, base=50, bins=[150, 60, 40])
mc = W(345, T0, t='MSFT', vol=300, base=50, bins=[180, 75, 45])
b2 = boardmod.build([(put, shock.qualify(put, T0 + 60), {'resemblance': 0.0}),
                     (mc, shock.qualify(mc, T0 + 60), {'resemblance': 0.95})], T0 + 60)
check(29, 'SIDE_SCENARIO_DISAGREEMENT' in b2['rows']['MSFT']['labels'], 'side disagreement between scenarios is labelled')
sc = boardmod.event_scores(W(345, T0, vol=400, base=50, bins=[240, 100, 60]),
                           shock.qualify(W(345, T0, vol=400, base=50, bins=[240, 100, 60]), T0 + 60), T0 + 60, 0.0)
check(29, sc['raw'] == round(100 * (0.55 * 1.0 + 0.30 * 0.6 + 0.15 * 1.0), 2), f"raw event score formula ({sc['raw']})")
check(19, boardmod.build([(W(345, T0, bins=[40] * 5), shock.qualify(W(345, T0, bins=[40] * 5), T0 + 60), None)],
                         T0 + 60)['rows'] == {}, 'diffuse background does not rank')

print('── §8 entry routing ──')
j = jr()
R = Router(j)
ts = T0 + 200
r = R.propose(cand('e1', ts, call_cluster(T0), rs=0.40))
check(13, r['decision'] == 'PROPOSE' and 'VERIFIED_CLUSTER_BELOW_SCORE_BOUNDARY' in r['logs'],
      'verified cluster proposes below the old 0.550 route score (logged, not vetoed)')
r2 = R.propose(cand('e-rank', ts, [W(345, T0, spot=346)], rs=0.99))
check(13, r2['decision'] == 'WATCH', 'a high score / rank alone never authorizes entry')
check(38, R.propose(cand('e1', ts, call_cluster(T0)))['duplicate'], 'duplicate candidate returns its prior result')
check(8, r['contract']['strike'] == 345.0 and r['qty'] == 2, 'tighter relative spread chosen; planned qty within budget')
c = j.campaign(r['campaign_id'])
check(8, c['reservation'] == 2 * 2.1 * 100 and abs(R.used_capacity() - 420.0) < 1e-6, 'ask x qty x 100 reserved')
r3 = R.propose(cand('e2', ts + 1, call_cluster(T0)))
r4 = R.propose(cand('e3', ts + 2, call_cluster(T0)))
check(36, r3['decision'] == 'PROPOSE' and r4['decision'] == 'WATCH' and 'DAILY_ENTRY_PROPOSAL_CAP' in r4['reasons'],
      'two entry proposals per ticker per NY day (cancelled ones count)')
ch_stale = cand('e-st', ts, call_cluster(T0))
ch_stale['choices'] = [choice(345.0, ts - 31)]
j2 = jr()
rr = Router(j2).propose(ch_stale)
check(8, rr['decision'] == 'WATCH' and 'QUOTE_STALE' in rr['contract_journal'][0]['reasons'], 'stale quote journaled per choice')
ch_exp = cand('e-ex', ts, call_cluster(T0), horizon='SWING')
ch_exp['choices'] = [choice(345.0, ts, exp='2026-10-21'), choice(345.0, ts, exp='2026-11-20')]
rr = Router(jr()).propose(ch_exp)
check(8, rr['decision'] == 'PROPOSE' and rr['contract']['expiry'] == '2026-11-20', 'SWING needs expiry beyond planned end + buffer')
ch_util = cand('e-ut', ts, call_cluster(T0))
ch_util['choices'] = [dict(choice(345.0, ts), utility=1.0), choice(347.5, ts, ask=2.2)]
rr = Router(jr()).propose(ch_util)
check(8, rr['ranking'] == 'SPREAD', 'partial utility coverage does not outrank by utility')
jb = jr()
RB = Router(jb)
big = cand('e-big', ts, call_cluster(T0))
big['choices'] = [choice(345.0, ts, bid=11.0, ask=11.5)]
rb = RB.propose(big)
check(8, rb['decision'] == 'PROPOSE' and rb['qty'] == 1, 'planned quantity limited by the $2,000 reference budget')
over = cand('e-over', ts, call_cluster(T0))
over['choices'] = [choice(345.0, ts, bid=9.0, ask=9.5)]
check(8, 'NONPOSITIVE_PLANNED_QUANTITY' in RB.propose(over)['reasons'], 'no capacity → WATCH, never an oversized order')
mt = cand('e-match', ts, call_cluster(T0))
for it in mt['items']:
    it['res'] = {'resemblance': 0.9, 'labels': ['OPEN_CLOSE_UNRESOLVED']}
check(26, Router(jr()).propose(mt)['decision'] == 'PROPOSE', 'matched turnover does not veto verified same-side entry')

print('── §14 fills and lifecycle ──')
j = jr()
R = Router(j)
r = R.propose(cand('L1', ts, call_cluster(T0)))
cid = r['campaign_id']
check(33, j.campaign(cid)['state'] == 'PROPOSED' and j.campaign(cid)['held_qty'] == 0, 'PROPOSED holds nothing')
f1 = R.entry_fill({'event_id': 'f1', 'campaign_id': cid, 'qty': 1, 'price': 2.10, 'ts': ts + 5})
c = j.campaign(cid)
check(33, f1['accepted'] and c['state'] == 'ACTIVE' and c['held_qty'] == 1 and c['outstanding_entry_qty'] == 1
      and c['avg_entry'] == 2.10, 'partial entry fill keeps the outstanding remainder')
f2 = R.entry_fill({'event_id': 'f2', 'campaign_id': cid, 'qty': 1, 'price': 2.30, 'ts': ts + 9})
c = j.campaign(cid)
check(33, abs(c['avg_entry'] - 2.20) < 1e-9 and 'FILL_ABOVE_PROPOSAL_ASK' in f2['notes'],
      'weighted actual average fill; a fill above the ask is recorded, not hidden')
check(38, R.entry_fill({'event_id': 'f2', 'campaign_id': cid, 'qty': 1, 'price': 2.30, 'ts': ts + 9})['duplicate']
      and j.campaign(cid)['held_qty'] == 2, 'duplicate fill event is not applied twice')
bad = R.entry_fill({'event_id': 'f3', 'campaign_id': cid, 'qty': 1, 'price': 2.3, 'ts': ts + 10})
check(33, not bad['accepted'] and 'QTY_EXCEEDS_OUTSTANDING' in bad['reasons'], 'fill beyond outstanding → reconciliation exception')
x = R.exit_fill({'event_id': 'x1', 'campaign_id': cid, 'qty': 3, 'price': 2.5, 'ts': ts + 20})
check(33, not x['accepted'] and 'QTY_EXCEEDS_HELD' in x['reasons'], 'exit fill cannot exceed held quantity')
x = R.exit_fill({'event_id': 'x2', 'campaign_id': cid, 'qty': 2, 'price': 2.75, 'ts': ts + 30})
check(33, x['state'] == 'CLOSED' and x['realized'] == round((2.75 - 2.2) * 100 * 2, 2), 'realized dollars from actual fills')
j = jr()
R = Router(j)
cid = R.propose(cand('L2', ts, call_cluster(T0)))['campaign_id']
R.entry_fill({'event_id': 'g1', 'campaign_id': cid, 'qty': 1, 'price': 2.1, 'ts': ts + 5})
R.exit_fill({'event_id': 'g2', 'campaign_id': cid, 'qty': 1, 'price': 2.4, 'ts': ts + 10})
check(34, j.campaign(cid)['state'] == 'ENTRY_PENDING', 'held 0 with an entry remainder → ENTRY_PENDING, not CLOSED')
R.entry_fill({'event_id': 'g3', 'campaign_id': cid, 'qty': 1, 'price': 2.2, 'ts': ts + 15})
check(34, j.campaign(cid)['state'] == 'ACTIVE' and j.campaign(cid)['held_qty'] == 1, 'a late remainder fill restores held state')
R.exit_fill({'event_id': 'g4', 'campaign_id': cid, 'qty': 1, 'price': 2.4, 'ts': ts + 20})
check(34, j.campaign(cid)['state'] == 'CLOSED', 'CLOSED only with nothing held and nothing outstanding')
cid2 = R.propose(cand('L3', ts, call_cluster(T0)))['campaign_id']
R.cancel_confirmed({'event_id': 'cx', 'campaign_id': cid2, 'ts': ts + 60})
check(36, j.campaign(cid2)['state'] == 'CANCELLED' and j.proposals('AAPL', '2026-10-19') == 2,
      'a cancelled proposal still counts toward the daily cap')
late = R.entry_fill({'event_id': 'late', 'campaign_id': cid2, 'qty': 1, 'price': 2.1, 'ts': ts + 90})
check(34, not late['accepted'] and len(j.logs('RECONCILIATION_EXCEPTION')) >= 1,
      'a broker fill outside the expected window is a logged reconciliation exception, never ignored')

print('── §11-13 management ──')


def held(j, R, eid='H', fill_ts=None, qty=2, price=2.0, **kw):
    cid = R.propose(cand(eid, ts, call_cluster(T0), **kw))['campaign_id']
    R.entry_fill({'event_id': eid + 'f', 'campaign_id': cid, 'qty': qty, 'price': price, 'ts': fill_ts or ts + 5})
    return cid


def q(t, bid=2.0, size=5):
    return {'bid': bid, 'ask': bid + 0.1, 'bid_size': size, 'ts': t}


j = jr()
R = Router(j)
cid = held(j, R)
m = R.manage({'event_id': 'm1', 'ts': ts + 60, 'campaign_id': cid, 'quote': q(ts + 59, bid=1.0),
              'stock_price': 340.0, 'snapshot': snap(ts=ts + 60, bull=False, bear=True), 'items': []})
check(11, m['decision'] == 'HOLD', 'a -50% premium dip, lower low and adverse spot alone do not exit')
check(12, all(R.manage({'event_id': f'm-{g}', 'ts': ts + 70 + g, 'campaign_id': cid,
                        'quote': q(ts + 69 + g, bid=2.0 * (1 + g / 100)), 'snapshot': snap(ts=ts + 70 + g, bull=True),
                        'items': []})['decision'] == 'HOLD' for g in (60, 150)),
      'no automatic half sale / target at +60% or +150% and no trailing exit')
c = j.campaign(cid)
check(12, c['marks']['peak_bid'] == 5.0 and c['marks']['min_bid'] == 1.0, 'favorable/adverse executable-bid path recorded')
deadline = cal.planned_end('INTRADAY', ts)
m = R.manage({'event_id': 'm-dl', 'ts': deadline, 'campaign_id': cid, 'quote': q(deadline - 1)})
check(37, m['decision'] == 'EXIT_REQUEST' and m['reasons'] == ['PLANNED_OR_EXPIRY_EXIT_DEADLINE'],
      'planned deadline exit works without any reversal')
check(36, cal.expiry_deadline('2026-11-27') == NY.localize(datetime(2026, 11, 27, 12, 30)).timestamp(),
      'expiration cutoff moves earlier on an early-close day (Black Friday 13:00 close)')
os.environ['CF_PREMIUM_LOSS_LIMIT'] = '0.5'
import importlib
importlib.reload(S)
j = jr()
R = Router(j)
cid = held(j, R, 'risk')
check(37, j.campaign(cid)['risk_plan']['premium_loss_limit'] == 0.5, 'risk limit precommitted at proposal')
m = R.manage({'event_id': 'mr', 'ts': ts + 60, 'campaign_id': cid, 'quote': q(ts + 59, bid=0.99)})
check(37, m['decision'] == 'EXIT_REQUEST' and 'PRECOMMITTED_PREMIUM_RISK_LIMIT' in m['reasons'],
      'precommitted premium limit uses a fresh bid vs actual average fill')
del os.environ['CF_PREMIUM_LOSS_LIMIT']
importlib.reload(S)
j = jr()
R = Router(j)
cid = held(j, R, 'nolimit')
check(37, j.campaign(cid)['risk_plan']['premium_loss_limit'] is None and
      R.manage({'event_id': 'mn', 'ts': ts + 60, 'campaign_id': cid, 'quote': q(ts + 59, bid=0.05)})['decision'] == 'HOLD',
      'no default -18% stop: without a precommitted limit the paid premium stays at risk')
# favorable overnight gap
j = jr()
R = Router(j)
cid = held(j, R, 'gap', horizon='OVERNIGHT')
o1 = cal.bounds(date(2026, 10, 20))[0]
m = R.manage({'event_id': 'g', 'ts': o1 + 2, 'campaign_id': cid, 'quote': q(o1 + 1, bid=2.6), 'prior_close': 346.0,
              'open_price': 347.0, 'open_time': o1})
check(36, m['decision'] == 'EXIT_REQUEST' and m['reasons'][0] == 'FAVORABLE_REGULAR_SESSION_OPEN_GAP_SELL_ALL',
      'favorable underlying gap up requests sale of all remaining calls')
m = R.manage({'event_id': 'g2', 'ts': o1 + 3, 'campaign_id': cid, 'quote': {'bid': 0, 'bid_size': 0, 'ts': o1 + 3}})
check(35, m['decision'] == 'EXIT_PENDING_EXECUTABLE_QUOTE' and j.campaign(cid)['exit_pending']['primary']
      == 'FAVORABLE_REGULAR_SESSION_OPEN_GAP_SELL_ALL', 'the gap exit intent persists through an unusable quote')
j = jr()
R = Router(j)
cid = held(j, R, 'flat', horizon='OVERNIGHT')
m = R.manage({'event_id': 'f', 'ts': o1 + 2, 'campaign_id': cid, 'quote': q(o1 + 1), 'prior_close': 346.0,
              'open_price': 346.0, 'open_time': o1})
check(36, m['decision'] == 'HOLD', 'a flat open is not a favorable gap')

print('── §12.4 rotation ──')
j = jr()
R = Router(j)
fill_t = T0 + 200
cid = held(j, R, 'rot', fill_ts=fill_t)
pre = call_cluster(T0 - 400, strikes=(340.0, 342.5), right='P', n=2)                  # BEFORE entry
m = R.manage({'event_id': 'r0', 'ts': fill_t + 10, 'campaign_id': cid, 'quote': q(fill_t + 9),
              'snapshot': snap(ts=fill_t + 10, bear=True), 'items': items(pre, fill_t + 10)})
check(18, m['decision'] == 'HOLD', 'pre-entry opposite flow cannot rotate the campaign')
post = call_cluster(fill_t + 20, strikes=(340.0, 342.5), right='P', n=2)
now = fill_t + 20 + 120 + 10
m = R.manage({'event_id': 'r1', 'ts': now, 'campaign_id': cid, 'quote': q(now - 1),
              'snapshot': snap(ts=now, bull=True, bear=True), 'items': items(pre + post + call_cluster(fill_t + 20), now)})
check(16, m['decision'] == 'HOLD' and 'CONTESTED_BOTH_SIDES_CLUSTERING' in m['logs'], 'contested flow is not a rotation')
m = R.manage({'event_id': 'r1b', 'ts': now, 'campaign_id': cid, 'quote': q(now - 1),
              'snapshot': snap(ts=now, bear=False), 'items': items(post, now)})
check(17, m['decision'] == 'HOLD', 'opposite cluster without bearish underlying confirmation does not rotate')
amb = items(post, now)
for it in amb:
    it['res'] = {'resemblance': 0.6, 'labels': ['OPEN_CLOSE_UNRESOLVED']}
m = R.manage({'event_id': 'r2', 'ts': now, 'campaign_id': cid, 'quote': q(now - 1),
              'snapshot': snap(ts=now, bear=True), 'items': amb})
check(27, m['decision'] == 'HOLD' and 'ROTATION_AWAITING_INDEPENDENT_FOLLOWTHROUGH' in m['logs'],
      'ambiguous (turnover-matched) opposite cluster waits for follow-through')
later = [W(340.0, fill_t + 20 + 120, right='P', spot=346), W(342.5, fill_t + 20 + 120, right='P', spot=346)]
now2 = fill_t + 20 + 180 + 5
it2 = amb + items(later, now2)
m = R.manage({'event_id': 'r3', 'ts': now2, 'campaign_id': cid, 'quote': q(now2 - 1, bid=2.4),
              'snapshot': snap(ts=now2, bear=True), 'items': it2})
check(14, m['decision'] == 'EXIT_REQUEST' and 'CONFIRMED_OPPOSITE_CLUSTER_ROTATION' in m['reasons'],
      'independent unmatched follow-through → full exit request')
rp = R.propose({**cand('opp-early', now2 + 1, post + later, direction='BEARISH', bull=False, bear=True),
                'source_campaign_id': cid})
check(14, rp['decision'] == 'WATCH' and 'ROTATION_SOURCE_NOT_FULLY_CLOSED' in rp['reasons'],
      'opposite entry waits until the source campaign is fully CLOSED')
m = R.manage({'event_id': 'r4', 'ts': now2 + 5, 'campaign_id': cid, 'quote': {'bid': 2.4, 'bid_size': 2, 'ts': now2 - 60}})
check(35, m['decision'] == 'EXIT_PENDING_EXECUTABLE_QUOTE', 'stale quote → exit stays pending')
R.exit_fill({'event_id': 'rx1', 'campaign_id': cid, 'qty': 1, 'price': 2.4, 'ts': now2 + 10})
m = R.manage({'event_id': 'r5', 'ts': now2 + 12, 'campaign_id': cid, 'quote': q(now2 + 11, bid=2.3)})
check(35, m['decision'] == 'EXIT_REQUEST' and m['qty'] == 1 and j.campaign(cid)['exit_pending']['rotation_direction'] == 'BEARISH',
      'rotation exit stays pending through a partial fill for the remaining contract')
R.exit_fill({'event_id': 'rx2', 'campaign_id': cid, 'qty': 1, 'price': 2.3, 'ts': now2 + 14})
src = j.campaign(cid)
rp = R.propose({**cand('opp', now2 + 20, post + later, direction='BEARISH', bull=False, bear=True),
                'source_campaign_id': cid})
check(14, src['state'] == 'CLOSED' and rp['decision'] == 'PROPOSE' and rp['campaign_id'] != cid
      and j.campaign(rp['campaign_id'])['source_campaign_id'] == cid,
      'after a confirmed full exit the opposite entry is a separate campaign referencing the source')

print('── §9/§10 OI reference ──')
cut = cal.oi_cutoff(D)
op = cal.bounds(D)[0]
check(10, cut == NY.localize(datetime(2026, 10, 19, 9, 20)).timestamp(), 'cutoff = actual regular open - 10 min')
rows = ([{'expiry': '2026-10-19', 'right': 'C', 'strike': k, 'oi': oi} for k, oi in
         ((210, 5000), (212.5, 800), (215, 9000), (217.5, 1200), (220, 100400), (222.5, 3000), (225, 7000), (230, 50000))] +
        [{'expiry': '2026-10-19', 'right': 'P', 'strike': k, 'oi': oi} for k, oi in
         ((205, 9000), (207.5, 1000), (210, 15000), (212.5, 15900), (215, 27300), (217.5, 400), (220, 71700))] +
        [{'expiry': '2026-10-23', 'right': 'C', 'strike': 220, 'oi': 999999}])
chain = {'ticker': 'NVDA', 'session': '2026-10-19', 'rows': rows, 'published_ts': cut - 3600, 'available_ts': cut - 3000,
         'source_id': 'test', 'complete': True, 'both_sides': True}
late_chain = dict(chain, published_ts=cut + 60, available_ts=cut + 60,
                  rows=[dict(r, oi=1) for r in rows])
f = oi_ref.freeze([chain, late_chain], 'NVDA', D, cut + 300)
check(10, f['expiry'] == '2026-10-19' and f['rows'][0]['oi'] != 1, 'delayed invocation still freezes only what was published by the cutoff')
check(8, f['expiry'] == '2026-10-19', 'nearest listed (0DTE) expiry frozen, never the larger-OI later expiry')
miss = oi_ref.freeze([chain], 'NVDA', D, op + 5)
check(9, miss['missing'] and miss['reason'] == 'MISSED_OPEN_OI_CONTEXT_MISSING', 'a job that misses the open keeps OI missing')
j = jr()
j.put_freeze(miss)
again = j.put_freeze(oi_ref.freeze([chain], 'NVDA', D, cut + 10))
check(9, again['missing'], 'missing premarket OI cannot be backfilled intraday (write-once per session)')
nxt = oi_ref.freeze([dict(chain, session='2026-10-20', published_ts=cal.oi_cutoff(date(2026, 10, 20)) - 60)],
                    'NVDA', date(2026, 10, 20), cal.oi_cutoff(date(2026, 10, 20)) + 5)
check(8, not nxt['missing'], 'the reference refreshes on the next actual trading session')
opening = {'ticker': 'NVDA', 'session': '2026-10-19', 'price': 216.0, 'open_ts': op, 'available_ts': op + 2, 'source': 'test'}
lv = oi_ref.levels(f, opening, as_of_ts=op + 10)
check(6, [x['strike'] for x in lv['put_support']] == [215.0, 212.5, 210.0] and 220.0 not in
      [x['strike'] for x in lv['put_support']], 'put support only at/below the fixed open; 220P excluded despite 71.7k OI')
check(6, [x['strike'] for x in lv['call_resistance']] == [220.0, 230.0, 225.0], 'call nodes: top-3 OI within the 6 nearest at/above the open')
check(4, oi_ref.levels(f, opening, as_of_ts=op + 1)['reason'] == 'OPENING_PRICE_NOT_YET_KNOWN',
      'levels are not exposed before the opening price was known')
check(6, oi_ref.pin_open(opening, dict(opening, price=210.0))['price'] == 216.0, 'opening price pinned immutably')
cl = {'expiry': '2026-10-19', 'right': 'P', 'strikes': [217.5], 'first_start': op + 600, 'member_ends': [op + 660]}
zn = oi_ref.zone(f, cl)
check(5, zn['zone'] and zn['zone'][0]['lower'] == 216.25 and zn['zone'][0]['upper'] == 218.75,
      'a cluster at a strike outside the displayed top three still builds a backend zone')
crd = cards.text(cards.render('ENTRY_PROPOSED', {'campaign_id': 'abc12345xyz', 'direction': 'BEARISH',
                                                'contract': contract('NVDA', 'P', 217.5, '2026-10-19')},
                              ts=op + 700, price=1.2, qty=2))
check(5, 'zone' not in crd.lower() and 'OI' not in crd, 'zones stay off the public card')
check(7, oi_ref.zone(dict(f, published_ts=op + 900), cl)['reason'] == 'OI_NOT_PUBLISHED_BEFORE_CLUSTER',
      'OI published after a cluster cannot be applied retrospectively')
check(10, oi_ref.zone(f, dict(cl, expiry='2026-10-23'))['reason'] == 'CLUSTER_NOT_IN_FROZEN_EXPIRATION',
      'a farther-expiry cluster gets no nearest-expiry zone')
check(4, f['rows'] and all(r['expiry'] == '2026-10-19' for r in f['rows']) and f['published_ts'] == cut - 3600,
      'frozen rows keep session, publication time and call/put side')

print('── §15 cards ──')
camp = {'campaign_id': '8f3a1b2c9d', 'direction': 'BULLISH', 'contract': contract('AAPL', 'C', 345, '2026-10-16')}
t_card = NY.localize(datetime(2026, 10, 16, 10, 2)).timestamp()
p = cards.text(cards.render('ENTRY_PROPOSED', camp, ts=t_card, price=2.90, qty=2))
check(3, 'PROPOSED · awaiting fill' in p and 'Indicative quote $2.90' in p and 'Planned contracts 2' in p
      and '10:02 ET' in p and p.endswith(cards.FOOTER), 'proposal card: indicative quote, planned contracts, NY time')
x = cards.text(cards.render('EXIT_FILLED', camp, ts=t_card + 420, price=2.54, qty=2, avg_entry=2.90,
                            reasons=['CONFIRMED_OPPOSITE_CLUSTER_ROTATION']))
check(3, 'Actual fill $2.54' in x and 'Option return -12.4% (fills)' in x and 'Confirmed opposite put cluster' in x,
      'exit card: actual fill and fill-based return')
try:
    cards.render('EXIT_FILLED', camp, ts=t_card, price=2.54, qty=2)
    ok = False
except cards.CardError:
    ok = True
check(3, ok, 'EXIT_FILLED without an actual average entry basis is refused')
try:
    cards.render('ENTRY_PROPOSED', dict(camp, campaign_id='x @everyone'), ts=t_card, price=1, qty=1)
    ok = False
except cards.CardError:
    ok = True
check(3, ok and cards.render('ENTRY_FILLED', camp, ts=t_card, price=1, qty=1)['allowed_mentions'] == {'parse': []},
      'mention injection refused; automatic mention parsing disabled')
px = cards.text(cards.render('EXIT_FILLED', camp, ts=t_card, price=2.5, qty=1, avg_entry=2.0, partial_remaining=1,
                             reasons=['PLANNED_OR_EXPIRY_EXIT_DEADLINE']))
check(3, 'Partial execution: 1 executed, 1 still open' in px, 'partial execution states the executed quantity')

print('── §11 diagnostics ──')
bars = [{'end': T0 + i * 60, 'volume': v, 'close': c} for i, (v, c) in enumerate([(0, 1.0), (10, 1.2), (30, 1.1), (60, 1.4)])]
dg = diagnostics.bar_diagnostics(bars, T0 + 1000)
check(11, dg['value_percentile'] == 1.0 and dg['top3_share'] == 1.0 and dg['active_frac'] == 0.75,
      'range-location diagnostic (legacy name value_percentile) is not the §3 gate')
check(11, not diagnostics.bar_diagnostics(bars, T0 + 30)['valid'], 'future bars invalid')

print('── restart / idempotency ──')
path = tempfile.mktemp(suffix='.db')
j = Journal(path)
R = Router(j)
cid = held(j, R, 'rs')
R.manage({'event_id': 'rsx', 'ts': deadline, 'campaign_id': cid, 'quote': {'bid': 0, 'bid_size': 0, 'ts': deadline}})
j.close()
j = Journal(path)
c = j.campaign(cid)
check(38, c['exit_pending']['primary'] == 'PLANNED_OR_EXPIRY_EXIT_DEADLINE' and c['held_qty'] == 2
      and j.proposals('AAPL', '2026-10-19') == 1, 'restart preserves campaigns, pending exits and proposal counts')
import sqlite3
con = sqlite3.connect(path)
con.execute("UPDATE meta SET v='other' WHERE k='schema_version'")
con.commit()
con.close()
try:
    Journal(path)
    ok = False
except RuntimeError:
    ok = True
check(38, ok, 'an incompatible journal schema is refused, never silently reused')

print()
print(f"{len(FAILS)} failure(s)" if FAILS else "ALL CAMPAIGN-FLOW CHECKS PASSED")
sys.exit(1 if FAILS else 0)
