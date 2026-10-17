"""Flow-handoff alignment tests: coverage gaps, DTE channels, verified catalysts, package ratios,
retired labels, baseline seeding, card layout, ledger provenance. Run: python test_handoff_alignment.py"""
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
config.DISCORD_WEBHOOK_URL = ''
import notify
from analysis import catalyst, channels, coverage, decision_ledger, hypotheses, mass, packages, reversal
from data.market_utils import CST

fails = 0
def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1

def at(y, m, d, hh, mm, ss=0):
    return CST.localize(datetime(y, m, d, hh, mm, ss))

print("── coverage: a feed gap disables inference until windows refill ──")
cv = coverage.CoverageTracker(gap_s=30, recovery_s=180)
ck("never ingested → NO_DATA", cv.state('AAPL', 1000) == 'NO_DATA')
ck("first ingest of the session is not a gap", cv.ok('AAPL', 1000) is None and cv.state('AAPL', 1000) == 'HEALTHY')
ck("5s cadence stays HEALTHY", cv.ok('AAPL', 1005) is None and cv.state('AAPL', 1005) == 'HEALTHY')
ck("inside an open gap → DEGRADED", cv.state('AAPL', 1040) == 'DEGRADED')
inc = cv.ok('AAPL', 1035 + 30)                          # forced 60s outage closes
ck("closing a 60s gap is an incident", inc and inc['gap_s'] == 60)
for t in range(1070, 1065 + 180, 5):                    # continuous 5s polls after the gap
    cv.ok('AAPL', t)
ck("still DEGRADED during recovery", cv.state('AAPL', 1065 + 179) == 'DEGRADED')
cv.ok('AAPL', 1065 + 180)
ck("HEALTHY once the recovery window has elapsed", cv.state('AAPL', 1065 + 180) == 'HEALTHY')
ck("other tickers unaffected", cv.ok('MSFT', 1000) is None and cv.state('MSFT', 1001) == 'HEALTHY')

print("── DTE channels (NY calendar days) ──")
now = at(2026, 10, 16, 10, 0)
ck("0 → zero_dte", channels.dte_bucket(channels.dte_ny(date(2026, 10, 16), now)) == 'zero_dte')
ck("7 → weekly", channels.dte_bucket(7) == 'weekly' and channels.dte_bucket(1) == 'weekly')
ck("8/30 → short_term", channels.dte_bucket(8) == 'short_term' and channels.dte_bucket(30) == 'short_term')
ck("31/99 → swing", channels.dte_bucket(31) == 'swing' and channels.dte_bucket(99) == 'swing')
ck("100 → long_dated", channels.dte_bucket(100) == 'long_dated')
ck("missing / expired → UNKNOWN", channels.dte_bucket(None) == 'UNKNOWN' and channels.dte_bucket(-1) == 'UNKNOWN')
ck("calendar homes at its earliest LIVE expiry regardless of order",
   channels.home_bucket(['2026-12-18', '2026-10-16'], now) == 'zero_dte'
   and channels.home_bucket(['2026-10-15', '2026-11-13'], now) == 'short_term')
ck("stamp carries schema + ruleset + NY session",
   channels.stamp(now) == {'schema_version': channels.SCHEMA_VERSION,
                           'ruleset_version': channels.RULESET_VERSION, 'ny_session': '2026-10-16'})

print("── verified catalysts (point-in-time) ──")
ok_row = {'symbol': 'NVDA', 'event': 'earnings', 'event_time': '2026-11-19T16:05:00-05:00', 'timing': 'AMC',
          'source_url': 'https://example.invalid/ir', 'published_at': '2026-10-01T09:00:00-04:00',
          'observed_at': '2026-10-02T08:00:00-05:00'}
ck("no calendar → says so", catalyst.assess('NVDA', now, None, rows=None)['status'] in ('NO_CALENDAR', 'NONE_ON_FILE'))
a = catalyst.assess('NVDA', now, date(2026, 11, 20), rows=[ok_row])
ck("published before the signal + future event → VERIFIED", a['status'] == 'VERIFIED' and a['mismatch'] is False)
a = catalyst.assess('NVDA', now, date(2026, 10, 16), rows=[ok_row])
ck("expiry before the event → EVENT_MISMATCH", a['mismatch'] is True and 'mismatch' in a['sentence'])
a = catalyst.assess('NVDA', now, date(2026, 11, 19), rows=[ok_row])
ck("expiry on an AMC event day → mismatch (expires before release)", a['mismatch'] is True)
late = {**ok_row, 'published_at': '2026-10-20T09:00:00-04:00'}
ck("source published AFTER the print cannot explain it",
   catalyst.assess('NVDA', now, None, rows=[late])['status'] == 'NONE_ON_FILE')
past = {**ok_row, 'event_time': '2026-10-15T16:05:00-04:00'}
ck("past event ignored", catalyst.assess('NVDA', now, None, rows=[past])['status'] == 'NONE_ON_FILE')
nosrc = {k: v for k, v in ok_row.items() if k != 'source_url'}
a = catalyst.assess('NVDA', now, None, rows=[nosrc])
ck("missing source → UNVERIFIED, said on the card", a['status'] == 'UNVERIFIED' and 'unverified' in a['sentence'])
ck("market-wide '*' event applies to every name",
   catalyst.assess('AAPL', now, None, rows=[{**ok_row, 'symbol': '*', 'event': 'CPI'}])['status'] == 'VERIFIED')

print("── package candidates ──")
ck("4,000 vs 7,000 is 4:7, not 1:1", packages.leg_ratio(4000, 7000) == '4:7')
ck("split-fill noise rounds to the lot (2,010 vs 1,000 → 2:1)", packages.leg_ratio(2010, 1000) == '2:1')
pk = packages.resolve(335, 'CALL', {(335, 'CALL'): 10000, (340, 'CALL'): 10000}, 336)
ck("vertical candidate: ratio 1:1, association TIME_SIZE_ONLY, net side/cashflow UNKNOWN",
   pk['label'] == 'VERTICAL_LIKELY' and pk['ratio'] == '1:1' and pk['association'] == 'TIME_SIZE_ONLY'
   and pk['net_side'] == 'UNKNOWN' and pk['net_cashflow'] == 'UNKNOWN' and pk['partner']['strike'] == 340)
ck("sub-100 legs never form a package", packages.resolve(335, 'CALL', {(335, 'CALL'): 90, (340, 'CALL'): 90}, 336)['label']
   == 'OUTRIGHT_LIKELY' and config.PKG_MIN_LEG_CONTRACTS >= 100)

print("── retired labels ──")
ck("CONFIRMED/VERIFIED labels map to bounded names",
   channels.current_label('OPPOSITE_SIDE_CAMPAIGN_CONFIRMED') == 'OPPOSITE_SIDE_CAMPAIGN_SUSTAINED'
   and channels.current_label('VERIFIED_DISTRIBUTION') == 'SUSTAINED_DISTRIBUTION'
   and channels.current_label('NEW_POSITION_CONFIRMED') == 'OPENING_SUPPORTED'
   and channels.current_label('ROTATION') == 'ROTATION')
legacy = {'state': 'REVERSAL_CLUSTER_CONFIRMED', 'events': 3, 'confirm_evals': 2, 'strikes': [1], 'first_ts': None}
try:
    out = reversal.update(legacy, {'opp_event': False}, None)
    ck("a legacy REVERSAL_CLUSTER_CONFIRMED state is read as SUSTAINED", out['state'] in
       ('REVERSAL_CLUSTER_SUSTAINED', 'REVERSAL_ACTIVATED'))
except TypeError:
    ck("a legacy REVERSAL_CLUSTER_CONFIRMED state is read as SUSTAINED (signature)", False)
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'notify.py'), encoding='utf-8').read()
ck("no card text claims institutional / verified selling",
   'Institutional' not in src and 'Verified distribution' not in src)

print("── baseline seeding: missing history is UNSEEDED, not 'normal' ──")
tm = mass.TickerMass()
row = {'ticker_mass': 1000.0, 'call_mass': 600.0, 'put_mass': 400.0}
r1 = tm.update(row)
ck("first sample: z=0 but baseline UNSEEDED", r1['mass_z'] == 0.0 and r1['baseline_quality'] == 'UNSEEDED')
for _ in range(config.MASS_BASELINE_MIN_SAMPLES):
    r = tm.update(row)
ck("after enough samples → SEEDED", r['baseline_quality'] == 'SEEDED' and r['baseline_n'] > config.MASS_BASELINE_MIN_SAMPLES)

print("── hypotheses carry an alternative ──")
hy = {'probs': {'FRESH_DIRECTIONAL': 0.4, 'CLOSING_PROFITABLE': 0.25, 'HEDGE': 0.1, 'UNKNOWN': 0.25}}
ck("best alternative is the strongest NON-directional reading",
   hypotheses.best_alternative(hy) == ('CLOSING_PROFITABLE', 0.25) and hypotheses.best_alternative(None) is None)

print("── cards ──")
sent = []
notify._post = lambda embed, signal_id=None: sent.append(embed)
notify.near_miss_card(sym='NVDA', side='PUT', strike=180.0, route='R', score=0.52, threshold=0.55,
                      shortfall=0.03, value_state='EARLY', qual_control=0.7, dist_prob=0.2, archetype='A',
                      info_rank=1, acceptance='ABSORPTION', top_drag='x', now=now, expiry=date(2026, 10, 16),
                      alternative=('HEDGE', 0.2), next_check='whether response improves',
                      catalyst='Catalyst: none on file.')
e = sent[-1]
fv = {f['name']: f['value'] for f in e['fields']}
ck("near-miss: amber, research footer", e['color'] == notify._AMBER and notify.RESEARCH_FOOTER in e['footer']['text'])
ck("near-miss: NY time + DTE channel", 'ET · DTE 0 · `zero_dte`' in fv['Observed'])
ck("near-miss: conditional interpretation with its best alternative",
   'Working hypothesis' in fv['Interpretation'] and 'hedge' in fv['Interpretation'])
ck("near-miss: one next check + catalyst line", fv['Next check'] and fv['Catalyst'].startswith('Catalyst'))
board = {'total_premium': 1, 'ranked': [], 'by_symbol': {}}
notify.entry_card(board, symbol='NVDA', side='CALL', strike=185.0, expiry='2026-10-16', qty=1, price=1.0,
                  row={'share': 0.4, 'attention_score': 60, 'rank': 1, 'control_dominance': 0.7}, spot=184.0,
                  mode='ROUTE', now=now, alternative=('CLOSING_PROFITABLE', 0.2), catalyst=None)
e = sent[-1]
ck("entry (own paper order): states the alternative, no 'controls it' ownership claim",
   'Best alternative' in e['description'] and 'control it' not in e['description'])
ck("entry: missing calendar shown explicitly",
   any(f['name'] == 'Catalyst' and 'no verified calendar' in f['value'] for f in e['fields']))
notify.coverage_card({'symbol': 'AAPL', 'gap_s': 60.0, 'gap_start': 1.0}, recovery_s=180, now=now)
ck("coverage notice is blue and context-only", sent[-1]['color'] == notify._BLUE and 'context only' in sent[-1]['description'])

print("── ledger provenance ──")
rec = decision_ledger.build_record(now=now, ticker='NVDA', side='CALL', metric={'baseline_quality': 'UNSEEDED',
                                   'baseline_n': 1}, cand={'package': pk}, decision='REJECT', owner='t',
                                   provenance={**channels.stamp(now), 'dte': 0, 'dte_bucket': 'zero_dte',
                                               'coverage': 'DEGRADED', 'catalyst_status': 'NO_CALENDAR'})
ck("ledger record carries version, session, DTE channel, coverage, baseline quality, package ratio",
   rec['schema_version'] == channels.SCHEMA_VERSION and rec['ny_session'] == '2026-10-16'
   and rec['dte_bucket'] == 'zero_dte' and rec['coverage'] == 'DEGRADED'
   and rec['baseline_quality'] == 'UNSEEDED' and rec['package_ratio'] == '1:1')

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
