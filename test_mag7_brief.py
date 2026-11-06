"""Checks for the Mag 7 adjustments brief (Oct 30 2026 paper session) on SYNTHETIC test data:

  1 overnight carry on any weekday      4 one call + one put entry per day
  2 legacy cards kept off Discord        5 conviction tiers (WEAK / BUILDING / CONFIRMED)
  3 only filled cards are published      6 exit hysteresis, minimum hold, trailing stop
  7 neutral member-facing wording        + reconciliation of campaigns left open by a stopped process

Run: python test_mag7_brief.py
"""
import os
import tempfile
from datetime import date, datetime

import pytz

os.environ['CF_MODE'] = 'SHADOW'
import config                                            # noqa: E402
import notify                                            # noqa: E402
from campaign_flow import calendar_ny as cal            # noqa: E402
from campaign_flow import cards                         # noqa: E402
from campaign_flow import conviction                    # noqa: E402
from campaign_flow import settings as S                 # noqa: E402
from campaign_flow import shock                         # noqa: E402
from campaign_flow import turnover                      # noqa: E402
from campaign_flow import value_gate                    # noqa: E402
from campaign_flow.executor import SimBroker            # noqa: E402
from campaign_flow.journal import Journal               # noqa: E402
from campaign_flow.model import contract, series_key, window_id   # noqa: E402
from campaign_flow.pipeline import Pipeline             # noqa: E402
from campaign_flow.policy import Router                 # noqa: E402

NY = pytz.timezone('America/New_York')
MON, TUE = date(2026, 10, 26), date(2026, 10, 27)
T0 = NY.localize(datetime(2026, 10, 26, 10, 0)).timestamp()
EXP = '2026-10-26'                                       # 0DTE on Monday
NEXT = '2026-10-28'
FAILS = []


def check(cond, msg):
    print(f"  {'ok ' if cond else 'FAIL'} {msg}")
    if not cond:
        FAILS.append(msg)


def W(strike, start, *, right='C', exp=EXP, t='AAPL', vol=200, base=50.0, near=None, ps=2.0, pe=2.2, spot=346.0):
    con = contract(t, right, strike, exp)
    k = list(series_key(con))
    refs = [{'series': k, 'ts': start - 3600 - i, 'price': 5.0, 'basis': 'TRADE'} for i in range(30)]
    w = {'contract': con, 'start': float(start), 'end': float(start + 60), 'volume': vol,
         'bins': [int(vol * 0.6), int(vol * 0.25), vol - int(vol * 0.6) - int(vol * 0.25)], 'prints': 5,
         'near_ask': near if near is not None else int(vol * 0.8), 'baseline': base, 'largest_print': None,
         'prem_start': ps, 'prem_end': pe, 'event_premium': 2.1, 'spot': spot, 'iv': None,
         'secs_to_last_trade': None, 'cum_volume': None, 'complex_status': 'UNAVAILABLE',
         'available_ts': float(start + 60)}
    w['value'] = value_gate.classify(con, 2.1, refs, w['start'], 'TRADE')
    w['id'] = window_id(w)
    return w


def items(ws, now):
    valid, _ = shock.validate_windows(ws, now)
    return [{'w': w, 'q': shock.qualify(w, now), 'res': turnover.resemblance(w, None, None)} for w in valid]


def cluster(t0, right='C', strikes=(345.0, 347.5), n=2, exp=EXP, **kw):
    return [W(k, t0 + i * 60, right=right, exp=exp, **kw) for i in range(n) for k in strikes]


def snap(ts, bull=False, bear=False, exps=(EXP,)):
    return {'ticker': 'AAPL', 'available_ts': ts,
            'coverage': {'expirations': list(exps), 'rights': {e: ['C', 'P'] for e in exps},
                         'strikes_complete': True, 'trade_quote_synced': True},
            'underlying': {'bullish': bull, 'bearish': bear, 'evidence': {'rule': 'TEST', 'value': 0.5 if bull else -0.5}}}


def choice(strike, ts, right='C', exp=EXP, bid=2.0, ask=2.1):
    return {'contract': contract('AAPL', right, strike, exp),
            'quote': {'bid': bid, 'ask': ask, 'bid_size': 10, 'ask_size': 10, 'ts': ts, 'feed': 'opra'},
            'day_volume': 1000}


STRONG = {'tier': 'CONFIRMED', 'score': 92.0}
WEAKC = {'tier': 'WEAK', 'score': 30.0}


def cand(eid, ts, *, ticker='AAPL', direction='BULLISH', conv=STRONG, exp=EXP, **kw):
    right = 'C' if direction == 'BULLISH' else 'P'
    ws = cluster(ts - 200, right=right, exp=exp)
    return {'event_id': eid, 'ts': ts, 'ticker': ticker, 'direction': direction,
            'snapshot': snap(ts, bull=direction == 'BULLISH', bear=direction == 'BEARISH', exps=(exp,)),
            'items': items(ws, ts), 'choices': [choice(345.0, ts, right=right, exp=exp)],
            'route_score': 0.6, 'stock_price': 346.0, 'conviction': conv, **kw}


def jr():
    return Journal(tempfile.mktemp(suffix='.db'))


def q(t, bid=2.0):
    return {'bid': bid, 'ask': bid + 0.1, 'bid_size': 5, 'ts': t}


def held(R, eid, ts, direction='BULLISH', price=2.0, **kw):
    r = R.propose(cand(eid, ts, direction=direction, **kw))
    assert r['decision'] == 'PROPOSE', r.get('reasons')
    R.entry_fill({'event_id': eid + 'f', 'campaign_id': r['campaign_id'], 'qty': 2, 'price': price, 'ts': ts + 5})
    return r['campaign_id']


print('── 5 conviction tiers ──')
now = T0 + 600
hist = {'C': [150] * 30, 'P': [150] * 30}
strong = [W(k, T0 + i * 60, vol=600) for i in range(9) for k in (345.0, 347.5)]
cv = conviction.assess(items(strong, now), now, 346.0, hist)['C']
check(cv['tier'] == 'CONFIRMED' and cv['components']['persistence'] >= S.CONV_MIN_PERSIST
      and cv['premium_usd'] >= S.CONV_MIN_PREMIUM_USD,
      f"persistent, large, ask-side call flow across strikes → CONFIRMED (score {cv['score']})")
burst = [W(397.5, T0 + 540, vol=459, spot=398.0, t='TSLA')]
cb = conviction.assess(items(burst, now), now, 398.0, hist)['C']
check(cb['tier'] != 'CONFIRMED' and not cb['gates']['persistence'],
      f"one early 459-contract window (the 13:24 TSLA 397.5C case) is not CONFIRMED ({cb['tier']}, {cb['score']})")
thin = [W(k, T0 + i * 60, vol=60, base=50.0) for i in range(9) for k in (345.0, 347.5)]
ct = conviction.assess(items(thin, now), now, 346.0, hist)['C']
check(ct['tier'] == 'WEAK' and not ct['gates']['size'], f"steady flow at ~baseline size is WEAK ({ct['score']})")
both = strong + [W(k, T0 + i * 60, right='P', vol=900) for i in range(9) for k in (342.5, 345.0)]
cd = conviction.assess(items(both, now), now, 346.0, hist)['C']
check(cd['components']['dominance'] < S.CONV_MIN_DOMINANCE and cd['score'] < cv['score'],
      'heavier opposite-side premium lowers the call side (dominance)')
early = conviction.assess(items(strong, now), now, 346.0, {'C': [], 'P': []})['C']
check(early['components']['intraday'] is None and early['tier'] == 'CONFIRMED',
      'before 5 earlier windows exist the intraday comparison is not scored (the open is not penalized)')
far = [W(k, T0 + i * 60, vol=600) for i in range(9) for k in (380.0, 382.5)]
check(conviction.assess(items(far, now), now, 346.0, hist)['C']['contracts'] == 0,
      'strikes outside the near-the-money band are not counted')

print('── 5 entries need CONFIRMED ──')
R = Router(jr())
r = R.propose(cand('w1', T0 + 300, conv=WEAKC))
check(r['decision'] == 'WATCH' and 'CONVICTION_NOT_CONFIRMED:WEAK' in r['reasons'], 'a WEAK cluster is journaled, not proposed')
r = R.propose(cand('w2', T0 + 300, conv=None))
check(r['decision'] == 'WATCH' and 'CONVICTION_NOT_CONFIRMED:UNAVAILABLE' in r['reasons'], 'missing conviction fails closed')
r = R.propose(cand('w3', T0 + 300))
check(r['decision'] == 'PROPOSE' and r['conviction']['tier'] == 'CONFIRMED', 'CONFIRMED proposes and journals its inputs')

print('── 4 one call and one put entry per day ──')
R = Router(jr())
a = R.propose(cand('c1', T0 + 300, ticker='TSLA'))
b = R.propose(cand('c2', T0 + 400, ticker='NVDA'))
p = R.propose(cand('p1', T0 + 500, ticker='MSFT', direction='BEARISH'))
p2 = R.propose(cand('p2', T0 + 600, ticker='AMZN', direction='BEARISH'))
check(a['decision'] == 'PROPOSE' and b['decision'] == 'WATCH' and 'DAILY_CALL_PUT_ENTRY_CAP' in b['reasons'],
      'second call of the day (another ticker) is capped (scope ALL)')
check(p['decision'] == 'PROPOSE' and p2['decision'] == 'WATCH', 'one put allowed alongside the call; a second put is capped')
R.cancel_confirmed({'event_id': 'cx', 'campaign_id': a['campaign_id'], 'ts': T0 + 450})
b2 = R.propose(cand('c3', T0 + 700, ticker='NVDA'))
check(b2['decision'] == 'PROPOSE', 'a proposal cancelled unfilled releases the call slot (nothing was posted)')
nxt = NY.localize(datetime(2026, 10, 27, 10, 0)).timestamp()
check(R.propose(cand('c4', nxt, ticker='META', exp='2026-10-28'))['decision'] == 'PROPOSE', 'the cap resets next session')
S.ENTRY_CAP_SCOPE = 'TICKER'
R = Router(jr())
R.propose(cand('t1', T0 + 300, ticker='TSLA'))
check(R.propose(cand('t2', T0 + 400, ticker='NVDA'))['decision'] == 'PROPOSE'
      and 'DAILY_CALL_PUT_ENTRY_CAP' in R.propose(cand('t3', T0 + 500, ticker='TSLA'))['reasons'],
      'scope TICKER: one call per name per day')
S.ENTRY_CAP_SCOPE = 'ALL'
R = Router(jr())
cid = held(R, 's1', T0 + 300)
R.manage({'event_id': 's1x', 'ts': T0 + 400, 'campaign_id': cid, 'quote': q(T0 + 399)})
R.exit_fill({'event_id': 's1xf', 'campaign_id': cid, 'qty': 2, 'price': 1.0, 'ts': T0 + 410})
check('DAILY_CALL_PUT_ENTRY_CAP' in R.propose(cand('s2', T0 + 900))['reasons'],
      'a stop-out does not reopen the call slot')

print('── 6 exits: hysteresis, minimum hold, trailing stop ──')
R = Router(jr())
fill = T0 + 300
cid = held(R, 'h', fill - 5)
opp = cluster(fill + 100, right='P', strikes=(342.5, 345.0))
t1 = fill + 100 + 120 + 10


def mg(eid, ts, conv_p, extra_items=(), bid=2.5):
    return R.manage({'event_id': eid, 'ts': ts, 'campaign_id': cid, 'quote': q(ts - 1, bid=bid),
                     'snapshot': snap(ts, bear=True), 'items': items(list(opp) + list(extra_items), ts),
                     'conviction': {'C': {'tier': 'WEAK', 'score': 20.0}, 'P': conv_p}})


m = mg('e1', t1, {'tier': 'WEAK', 'score': 35.0})
check(m['decision'] == 'HOLD' and any(x.startswith('ROTATION_BELOW_EXIT_CONVICTION:WEAK') for x in m['logs']),
      'a verified but WEAK opposite cluster does not exit the winner (the 13:22 TSLA 400P case)')
m = mg('e2', t1 + 1, {'tier': 'CONFIRMED', 'score': S.CONV_CONFIRMED_SCORE + 1})
check(m['decision'] == 'HOLD' and any('ROTATION_BELOW_EXIT_CONVICTION:CONFIRMED' in x for x in m['logs']),
      'hysteresis: CONFIRMED at the entry bar is not enough to exit')
m = mg('e3', t1 + 2, {'tier': 'CONFIRMED', 'score': 95.0})
check(m['decision'] == 'HOLD' and 'ROTATION_WITHIN_MIN_HOLD' in m['logs'], 'within the minimum hold even strong flow waits')
late = fill + S.MIN_HOLD_S + 30
opp = cluster(late - 200, right='P', strikes=(342.5, 345.0))
m = mg('e4', late, {'tier': 'CONFIRMED', 'score': 95.0})
check(m['decision'] == 'EXIT_REQUEST' and m['reasons'] == ['CONFIRMED_OPPOSITE_CLUSTER_ROTATION'],
      'strong confirmed opposite flow after the minimum hold rotates')
R = Router(jr())
cid = held(R, 'tr', T0 + 300, price=2.0)
for i, b in enumerate((3.0, 4.4, 3.2)):
    m = R.manage({'event_id': f'tr{i}', 'ts': T0 + 400 + i, 'campaign_id': cid, 'quote': q(T0 + 399 + i, bid=b)})
check(m['decision'] == 'HOLD', 'after peaking at +120%, a pull back to +60% holds (the 10-30 395C dip)')
m = R.manage({'event_id': 'tr9', 'ts': T0 + 500, 'campaign_id': cid, 'quote': q(T0 + 499, bid=2.9)})
check(m['decision'] == 'EXIT_REQUEST' and m['reasons'] == ['TRAILING_STOP_FROM_PEAK'],
      'giving back 60% of the peak gain exits on the trailing stop')
R = Router(jr())
cid = held(R, 'tn', T0 + 300, price=2.0)
check(all(R.manage({'event_id': f'tn{i}', 'ts': T0 + 400 + i, 'campaign_id': cid, 'quote': q(T0 + 399 + i, bid=b)})
          ['decision'] == 'HOLD' for i, b in enumerate((3.8, 2.1))), 'the trailing stop is not armed below +100%')

print('── 1 overnight carry ──')
R = Router(jr())
ts = NY.localize(datetime(2026, 10, 26, 14, 0)).timestamp()
r = R.propose(cand('o1', ts, exp=NEXT, horizon='OVERNIGHT'))
c = R.j.campaign(r['campaign_id'])
check(r['decision'] == 'PROPOSE' and cal.ny_day(c['planned_end']) == TUE,
      'a Monday OVERNIGHT proposal in the next expiration plans its end for Tuesday')
r2 = R.propose(cand('o2', ts + 60, exp=NEXT, horizon='OVERNIGHT', direction='BEARISH'))
check(r2['decision'] == 'WATCH' and 'OVERNIGHT_PREMIUM_CAP' in r2['reasons'],
      f'carried premium is capped at ${S.OVERNIGHT_MAX_PREMIUM:.0f} across positions')
r3 = R.propose(cand('o3', ts + 60, exp=EXP, horizon='OVERNIGHT', direction='BEARISH'))
check(r3['decision'] == 'WATCH' and 'NO_SUITABLE_CONTRACT' in r3['reasons'],
      'a 0DTE contract can never be chosen for an overnight carry (never held into expiration by accident)')
R.entry_fill({'event_id': 'o1f', 'campaign_id': r['campaign_id'], 'qty': 2, 'price': 2.0, 'ts': ts + 5})
o_tue = cal.bounds(TUE)[0]
fc = cards.text(cards.render('ENTRY_FILLED', c, ts=ts + 5, price=2.0, qty=2))
check('Overnight position' in fc, 'the entry card says the position may be carried overnight')
for wd in (date(2026, 10, 26), date(2026, 10, 28), date(2026, 10, 30)):
    pe = cal.planned_end('OVERNIGHT', NY.localize(datetime.combine(wd, datetime.min.time())).timestamp() + 14 * 3600)
    check(cal.ny_day(pe) == cal.next_trading_day(wd), f"{wd:%a}: an overnight plan ends on the next session ({cal.ny_day(pe):%a})")


def mgo(R, cid, eid, ts, *, op, bid=1.9, own=None):
    return R.manage({'event_id': eid, 'ts': ts, 'campaign_id': cid, 'quote': q(ts - 1, bid=bid),
                     'prior_close': 346.0, 'open_price': op, 'open_time': o_tue,
                     'conviction': {'C': own or {'tier': 'WEAK', 'score': 10.0}, 'P': {'tier': 'WEAK', 'score': 0}}})


m = mgo(R, r['campaign_id'], 'og1', o_tue + 5, op=341.0)
check(m['decision'] == 'EXIT_REQUEST' and m['reasons'][0] == 'ADVERSE_OPEN_GAP_CARRY_REVIEW',
      'an adverse open gap >= 1% exits a carried call at the open')
R2 = Router(jr())
r = R2.propose(cand('o4', ts, exp=NEXT, horizon='OVERNIGHT'))
R2.entry_fill({'event_id': 'o4f', 'campaign_id': r['campaign_id'], 'qty': 2, 'price': 2.0, 'ts': ts + 5})
check(mgo(R2, r['campaign_id'], 'oh', o_tue + 60, op=345.9)['decision'] == 'HOLD', 'flat open (-0.03%): held until the review')
m = mgo(R2, r['campaign_id'], 'or', o_tue + S.OVERNIGHT_REVIEW_S + 1, op=345.9)
check(m['decision'] == 'EXIT_REQUEST' and m['reasons'] == ['OVERNIGHT_OPEN_REVIEW_NO_CONTINUATION'],
      'open review: not in profit and own side WEAK → closed')
R3 = Router(jr())
r = R3.propose(cand('o5', ts, exp=NEXT, horizon='OVERNIGHT'))
R3.entry_fill({'event_id': 'o5f', 'campaign_id': r['campaign_id'], 'qty': 2, 'price': 2.0, 'ts': ts + 5})
m = mgo(R3, r['campaign_id'], 'or2', o_tue + S.OVERNIGHT_REVIEW_S + 1, op=345.9, own={'tier': 'BUILDING', 'score': 50})
check(m['decision'] == 'HOLD' and R3.j.campaign(r['campaign_id'])['open_review_done'],
      'open review: own side BUILDING → carried position kept (review recorded once)')
x = cards.text(cards.render('EXIT_FILLED', R3.j.campaign(r['campaign_id']), ts=o_tue + 2000, price=2.4, qty=2,
                            avg_entry=2.0, reasons=['PLANNED_OR_EXPIRY_EXIT_DEADLINE']))
check('Carried overnight from Mon Oct 26' in x, 'the next-session exit card is labelled "Carried overnight"')

print('── 1 horizon choice in the pipeline ──')
j = jr()
P = Pipeline(j, SimBroker())
P.session = '2026-10-26'
noon = NY.localize(datetime(2026, 10, 26, 13, 0)).timestamp()
j.put_opening({'ticker': 'AAPL', 'session': '2026-10-26', 'price': 346.0, 'open_ts': cal.bounds(MON)[0],
               'available_ts': cal.bounds(MON)[0] + 60, 'source': 'test'})
P._snapshot['AAPL'] = snap(noon, exps=(EXP, NEXT))
P._range['AAPL'] = [347.5, 345.0]
cl_today, cl_next = {'expiry': EXP, 'strikes': [345.0]}, {'expiry': NEXT, 'strikes': [345.0]}
check(P._horizon('AAPL', noon, [cl_next]) == ('OVERNIGHT', [cl_next]),
      'Monday 13:00, consolidated day, flow in the next expiration → OVERNIGHT')
check(P._horizon('AAPL', noon, [cl_today, cl_next]) == (S.DEFAULT_HORIZON, [cl_today]),
      'same-day flow keeps trading intraday in the 0DTE contract')
check(P._horizon('AAPL', noon - 3 * 3600, [cl_next]) == (None, []), 'before the overnight window: not traded')
P._range['AAPL'] = [356.0, 340.0]
check(P._horizon('AAPL', noon, [cl_next]) == (None, []) and
      'OVERNIGHT_DAY_NOT_CONSOLIDATED' in j.logs('OVERNIGHT_NOT_TAKEN')[-1]['reasons'],
      'a trending (non-consolidated) day does not carry')
P._snapshot['AAPL'] = snap(noon, exps=(NEXT,))
check(P._horizon('AAPL', noon, [cl_next]) == (S.DEFAULT_HORIZON, [cl_next]),
      'Tue/Thu (nearest expiration is tomorrow): unchanged intraday behaviour')

print('── reconciliation of campaigns left open by a stopped process ──')
S.MAX_ENTRIES_PER_RIGHT_DAY = 0                          # several same-day campaigns in one scenario
R = Router(jr())
cid = held(R, 'orph', T0 + 300)
pr = R.propose(cand('orph2', T0 + 400, direction='BEARISH', ticker='NVDA'))
ov = R.propose(cand('ov', NY.localize(datetime(2026, 10, 26, 14, 0)).timestamp(), exp=NEXT, horizon='OVERNIGHT',
                    ticker='MSFT'))
R.entry_fill({'event_id': 'ovf', 'campaign_id': ov['campaign_id'], 'qty': 2, 'price': 2.0,
              'ts': NY.localize(datetime(2026, 10, 26, 14, 0, 5)).timestamp()})
done = R.reconcile_prior_sessions('2026-10-27', o_tue - 600)
c, p_, o_ = R.j.campaign(cid), R.j.campaign(pr['campaign_id']), R.j.campaign(ov['campaign_id'])
check(c['state'] == 'CLOSED' and c['unmanaged_expiry']['held_qty'] == 2, 'an expired 0DTE position is closed in the journal')
check(p_['state'] == 'CANCELLED', "yesterday's unfilled proposal is cancelled (releases its reservation)")
check(o_['state'] == 'ACTIVE' and ov['campaign_id'] not in done, 'a live overnight carry is left to management')
check(R.used_capacity() == 2 * 2.0 * 100, 'capacity counts only the live carried position')
S.MAX_ENTRIES_PER_RIGHT_DAY = 1

print('── 2/3/7 Discord output ──')
sent = []
real_enqueue = notify.enqueue
notify.enqueue = lambda payload, **kw: sent.append(payload) or None
config.LEGACY_DISCORD_ENABLED = False
notify.exit_card({'symbol': 'AMZN', 'side': 'PUT', 'strike': 230, 'qty': 1, 'entry_price': 2.77,
                  'opened_at': datetime.now().isoformat()}, price=1.59, reason='STOP_LOSS', pnl=-0.43,
                 mode='SHADOW', board={}, now=datetime.now())
check(sent == [], 'legacy engine cards (old "Jakenew Attention Engine" format) are not posted')
notify.enqueue = real_enqueue
j = jr()
P = Pipeline(j, SimBroker(), publish=lambda payload, cid: sent.append(payload))
S.MODE, S.DISCORD_ENABLED = 'PAPER', True
camp = {'campaign_id': 'abc123def456', 'ticker': 'AMZN', 'direction': 'BULLISH', 'horizon': 'INTRADAY',
        'contract': contract('AMZN', 'C', 240, '2026-10-30'), 'first_entry_ts': None}
j.put_campaign({**camp, 'state': 'PROPOSED', 'session': '2026-10-30', 'held_qty': 0, 'outstanding_entry_qty': 1,
                'entry_filled_qty': 0, 'proposal_ask': 2.33, 'avg_entry': None, 'reservation': 233})
t930 = NY.localize(datetime(2026, 10, 30, 9, 51)).timestamp()
P._card('ENTRY_PROPOSED', camp['campaign_id'], t930, price=2.33, qty=1, card_id='x:EP')
P._card('ENTRY_FILLED', camp['campaign_id'], t930 + 30, price=2.26, qty=1, card_id='x:EF', source='ALPACA_PAPER')
S.MODE, S.DISCORD_ENABLED = 'SHADOW', False
check(len(sent) == 1 and 'Simulated fill $2.26' in sent[0]['embeds'][0]['description'],
      'AMZN 240C: one member card, showing the $2.26 fill (the $2.33 proposal stays in the journal)')
check([c['published'] for c in j.cards()] == [False, True], 'the proposal is journaled unpublished')
e = sent[0]['embeds'][0]
check(e['title'] == 'Model opened a simulated position' and 'Campaign' not in e['description']
      and e['footer']['text'].startswith('Education only'), 'neutral title, no campaign id, "Education only" footer')

print('── 3 partial fills are journaled, never published ──')
from campaign_flow import executor  # noqa: E402
real_sync = executor.sync


def scripted():
    """Fresh pipeline that records published card embeds; fills arrive via feed()."""
    out = []
    p = Pipeline(jr(), SimBroker(), publish=lambda payload, cid: out.append(payload['embeds'][0]))
    return p, out


def feed(p, ts, *evs):
    executor.sync = lambda pipe, t: list(evs)
    S.MODE, S.DISCORD_ENABLED = 'PAPER', True
    try:
        p._sync_orders(ts)
    finally:
        executor.sync = real_sync
        S.MODE, S.DISCORD_ENABLED = 'SHADOW', False


def fill(eid, cid, kind, qty, price, ts):
    return {'event_id': eid, 'campaign_id': cid, 'kind': kind, 'qty': qty, 'price': price, 'ts': ts,
            'source': 'ALPACA_PAPER'}


# A: entry fills 1 + rest, exit fills 1 + rest → exactly one Opened and one Closed card, both combined
P, out = scripted()
r = P.router.propose(cand('pf1', T0 + 300))
cid = r['campaign_id']
n = P.j.campaign(cid)['outstanding_entry_qty']
check(n >= 2, f'scenario needs a multi-contract entry (planned {n})')
feed(P, T0 + 305, fill('pe1', cid, 'ENTRY', 1, 2.00, T0 + 305))
check(out == [], 'first partial entry fill: no member card')
feed(P, T0 + 310, fill('pe2', cid, 'ENTRY', n - 1, 2.20, T0 + 310))
avg = (2.00 + 2.20 * (n - 1)) / n
check(len(out) == 1 and out[0]['title'] == 'Model opened a simulated position'
      and f'Contracts {n}' in out[0]['description'] and f'${avg:.2f}' in out[0]['description'],
      f'entry complete: one Opened card for all {n} contracts at the weighted ${avg:.2f}')
feed(P, T0 + 400, fill('px1', cid, 'EXIT', 1, 3.00, T0 + 400))
check(len(out) == 1, 'first partial exit fill: no "Reduced" card')
feed(P, T0 + 410, fill('px2', cid, 'EXIT', n - 1, 2.00, T0 + 410))
xavg = (3.00 + 2.00 * (n - 1)) / n
check(len(out) == 2 and out[1]['title'] == 'Model closed a simulated position'
      and f'Contracts {n}' in out[1]['description'] and f'${xavg:.2f}' in out[1]['description']
      and 'Partial' not in out[1]['description'],
      f'position flat: one Closed card for all {n} contracts at the weighted ${xavg:.2f}')
cs = P.j.cards(cid)
check(sum(c['published'] for c in cs) == 2 and len(cs) == 6,
      'the four partial-fill cards stay in the journal unpublished (2 published of 6)')

# B: entry part-fills, the remainder is cancelled → one Opened card for what was bought
P, out = scripted()
cid = P.router.propose(cand('pf2', T0 + 300))['campaign_id']
feed(P, T0 + 305, fill('pe3', cid, 'ENTRY', 1, 2.05, T0 + 305))
feed(P, T0 + 320, {'event_id': 'pe3:cancel', 'campaign_id': cid, 'kind': 'CANCEL', 'ts': T0 + 320})
check(len(out) == 1 and 'Contracts 1' in out[0]['description'] and '$2.05' in out[0]['description'],
      'entry remainder cancelled: one Opened card for the 1 contract actually bought')

# C: whole-order fills publish exactly as before
P, out = scripted()
cid = P.router.propose(cand('pf3', T0 + 300))['campaign_id']
n = P.j.campaign(cid)['outstanding_entry_qty']
feed(P, T0 + 305, fill('pe4', cid, 'ENTRY', n, 2.10, T0 + 305))
feed(P, T0 + 400, fill('px4', cid, 'EXIT', n, 2.60, T0 + 400))
check([o['title'] for o in out] == ['Model opened a simulated position', 'Model closed a simulated position']
      and all(c['published'] for c in P.j.cards(cid)), 'whole fills: one Opened and one Closed card, unchanged')

print()
if FAILS:
    print(f"{len(FAILS)} MAG 7 BRIEF CHECK(S) FAILED")
    raise SystemExit(1)
print('ALL MAG 7 BRIEF CHECKS PASSED (synthetic test data)')
