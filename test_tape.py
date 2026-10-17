"""
Tape-lane tests (flow handoff §11). Run: python test_tape.py

EVERY fixture here is SYNTHETIC. The CAPR / NET / HUM / NKE / CGON / APLD names are the handoff's
challenge-case labels attached to constructed data — none is a verified historical trade.
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
config.DISCORD_WEBHOOK_URL = ''
import notify
from analysis import oi_confirm
from tape import baseline, cards, conditions, events, oi as oi_mod, packages, settings, side, taxonomy
from tape.pipeline import Pipeline
from tape.runtime import Recorder, replay, state_digest
from tape.store import Store

FIXTURE = 'SYNTHETIC'
fails = 0


def ck(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        fails += 1


SESSION = date(2026, 10, 19)
T0 = events.iso_to_ns('2026-10-19T14:00:00Z')          # 10:00 ET
MS = 1_000_000
SEC = 1_000_000_000


def occ(root, yymmdd, right, strike):
    return f"{root}{yymmdd}{right}{int(round(strike * 1000)):08d}"


class Harness:
    """A temp store + pipeline + recorder; every event goes through the archive like the live collector."""

    def __init__(self, contracts, *, medians=None, oi=None, p95=None, catalyst_rows=None, session=SESSION):
        self.dir = tempfile.mkdtemp(prefix='tape_test_')
        self.db = os.path.join(self.dir, 'tape.db')
        self.store = Store(self.db, os.path.join(self.dir, 'raw'))
        self.session = session
        self.contracts = {}
        for o, extra in contracts.items():
            p = events.parse_occ(o)
            info = {'underlying': p[0], 'expiry': p[1].isoformat(), 'right': p[2], 'strike': p[3],
                    'multiplier': 100.0, 'adjusted': 0, **(extra or {})}
            self.contracts[o] = info
            self.store.x("INSERT OR REPLACE INTO contracts VALUES (?,?,?,?,?,?,?,?,?)",
                         (o, info['underlying'], info['underlying'], info['expiry'], info['right'], info['strike'],
                          100.0, 0, '2026-10-19T08:00:00-04:00'))
        asof = '2026-10-16'
        for o, v in (medians or {}).items():
            self.store.x("INSERT INTO baselines VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (o, 'series_median_volume', session.isoformat(), v, 20, asof, 'x', 'OK', 'ok', 'test'))
        for u, v in (p95 or {}).items():
            self.store.x("INSERT INTO baselines VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (u, 'name_premium_p%g' % settings.PREMIUM_PCTL, session.isoformat(), v, 20, asof, 'x', 'OK',
                          'ok', 'test'))
        for o, rows in (oi or {}).items():
            for d, v in rows:
                self.store.x("INSERT INTO oi_vintages VALUES (?,?,?,?)", (o, d, v, '2026-10-17T08:00:00-04:00'))
        self.cards = []
        self.pipe = Pipeline(self.store, session, baseline.Baselines(self.store, session), self.contracts,
                             emit=self.cards.append, catalyst_rows=catalyst_rows)
        self.rec = Recorder(self.store, self.pipe, session)

    def quote(self, o, t, bid, ask, bs=10, as_=10):
        q = events.Quote(o, bid, ask, bs, as_, t, t + MS)
        self.rec.record('quote', q, {'S': o, 'bp': bid, 'ap': ask, 't': t}, 'stream', t + MS)

    def trade(self, o, t, price, size, x='C', cond='I', source='stream', recv=None):
        tr = events.Trade(o, price, size, x, cond, t, recv or t + 2 * MS, source,
                          {'S': o, 'p': price, 's': size, 'x': x, 'c': cond, 't': t})
        self.rec.record('trade', tr, tr.payload, source, tr.recv_ns)
        return tr

    def spot(self, sym, t, px):
        self.rec.record('spot', events.Spot(sym, px, t, t + MS), {'S': sym, 'p': px, 't': t}, 'stream', t + MS)

    def status(self, event, t, **kw):
        self.rec.record('status', {'event': event, **kw}, None, 'collector', t)

    def obs(self, o):
        r = self.store.q("SELECT obs_id, version, dims, campaign_id FROM observations WHERE occ=?", (o,))
        return (r[0][0], r[0][1], json.loads(r[0][2]), r[0][3]) if r else None

    def done(self):
        self.pipe.finish()
        self.store.flush()

    def close(self):
        self.store.close()
        shutil.rmtree(self.dir, ignore_errors=True)


def text_of(card):
    return json.dumps(card['payload'])


# ─────────────────────────────────────────────────────────────────────────────
print("── condition map (pinned, reviewed) ──")
ck("I and S are the only side-eligible letters",
   [c for c in conditions.PROVIDER_TEXT if conditions.side_eligible(conditions.tags(c))] == ['I', 'S'])
ck("complex / auction / cross / floor / stock-tied / late / cancel never side-eligible",
   not any(conditions.side_eligible(conditions.tags(c)) for c in 'abcdefghijklmnopqrstuvABCDEFGHJ'))
ck("unknown letter → UNKNOWN tag", conditions.tags('Z') == frozenset({'UNKNOWN'}) and conditions.tags('') == frozenset({'UNKNOWN'}))
ck("drift detection flags changed / new letters",
   conditions.drift({'I': 'AUTO - x', 'S': 'CHANGED', 'w': 'NEW'}) == ['S', 'w'])

print("── quote-side reading ──")
O = occ('XYZ', '261023', 'C', 100)
qb = side.QuoteBook()
qb.add(O, T0, events.Quote(O, 1.00, 1.10, 5, 5, T0, T0))
def tr(price, t=T0 + 100 * MS, cond='I'):
    return events.Trade(O, price, 10, 'C', cond, t, t, 'stream', {})
ck("near ask → LIKELY_TAKER_BUY", side.classify(tr(1.09), qb.at(O, T0 + 100 * MS))['side'] == side.BUY)
ck("near bid → LIKELY_TAKER_SELL", side.classify(tr(1.01), qb.at(O, T0 + 100 * MS))['side'] == side.SELL)
ck("mid → UNKNOWN", side.classify(tr(1.05), qb.at(O, T0 + 100 * MS))['reason'] == 'mid_market')
ck("outside quote → UNKNOWN", side.classify(tr(1.20), qb.at(O, T0 + 100 * MS))['reason'] == 'outside_quote')
ck("stale quote (600ms) → UNKNOWN", side.classify(tr(1.09, T0 + 600 * MS), qb.at(O, T0 + 600 * MS))['reason'] == 'stale_quote')
qb.add(O, T0 + 200 * MS, events.Quote(O, 1.08, 1.09, 5, 5, T0 + 200 * MS, T0 + 200 * MS))
ck("a LATER quote is never used (print at +100ms reads the T0 quote)",
   qb.at(O, T0 + 100 * MS)[0] == T0 and side.classify(tr(1.09), qb.at(O, T0 + 100 * MS))['side'] == side.BUY)
qc = side.QuoteBook(); qc.add(O, T0, events.Quote(O, 1.10, 1.10, 5, 5, T0, T0))
ck("locked/crossed → UNKNOWN", side.classify(tr(1.10), qc.at(O, T0 + 100 * MS))['reason'] == 'crossed_or_locked')
qw = side.QuoteBook(); qw.add(O, T0, events.Quote(O, 1.00, 1.40, 5, 5, T0, T0))
ck("wide (>25%) → UNKNOWN", side.classify(tr(1.39), qw.at(O, T0 + 100 * MS))['reason'] == 'wide_quote')
ck("unknown condition → UNKNOWN", side.classify(tr(1.09, cond='Z'), qb.at(O, T0 + 100 * MS))['reason'].startswith('condition'))
ck("complex condition → UNKNOWN", side.classify(tr(1.09, cond='f'), qb.at(O, T0 + 100 * MS))['side'] == side.UNKNOWN)
ck("quote-coverage gap → UNKNOWN", side.classify(tr(1.09), qb.at(O, T0 + 100 * MS), quote_covered=False)['reason']
   == 'quote_coverage_gap')
sb = side.SpotBook()
ck("unknown spot → missing (options-only feed)", side.spot_at(sb, 'XYZ', T0)['spot'] is None)
sb.add('XYZ', T0 - 6 * SEC, 99.0)
ck("spot older than 5s → stale, missing", side.spot_at(sb, 'XYZ', T0)['reason'] == 'stale_spot')

print("── sweep / block mechanics ──")
sw = side.SweepDetector()
sw.add(events.Trade(O, 1.09, 150, 'C', 'S', T0, T0, 'stream', {}))
keys = sw.add(events.Trade(O, 1.09, 120, 'X', 'S', T0 + 60 * MS, T0, 'stream', {}))
ck("≥250 across 2 venues within 100ms → sweep candidate", len(keys) == 2)
sw2 = side.SweepDetector()
sw2.add(events.Trade(O, 1.09, 150, 'C', 'S', T0, T0, 'stream', {}))
ck("same contracts 150ms apart → no sweep", sw2.add(events.Trade(O, 1.09, 120, 'X', 'S', T0 + 150 * MS, T0, 'stream', {})) == [])

print("── baselines: point-in-time, missing ≠ zero ──")
sess = baseline.completed_sessions(SESSION, 20)
ck("20 completed sessions, all before the session", len(sess) == 20 and max(sess) < SESSION)
ck("same-day / future baseline rejected", baseline.validate_asof(SESSION, SESSION) == 'same_day_or_future')
ck("stale (>7 days) baseline rejected", baseline.validate_asof(date(2026, 10, 9), SESSION) == 'stale')
sm = baseline.series_median({d: 50 for d in sess[-5:]}, sess)
ck("newly listed series (5 sessions) → INSUFFICIENT, value None (not 0)", sm['status'] == 'INSUFFICIENT' and sm['value'] is None)
daily = {d: 100 for d in sess}
daily.pop(sess[3])
sm = baseline.series_median(daily, sess)
ck("a no-trade day after first observation counts as 0 volume", sm['n'] == 20 and sm['value'] == 100)
ck("quiet build: ≥100 over 5 sessions each <50", baseline.quiet_build({d: 30 for d in sess}, sess) is not None
   and baseline.quiet_build({d: 60 for d in sess}, sess) is None)
h = baseline.histogram([1000] * 95 + [100000] * 5)
p = baseline.pooled_percentile([h], 95)
ck("pooled p95 from histograms ≈ the 95th value (bucket upper edge)", 1000 <= p <= 1100)

print("── CAPR: mixed bid/ask put prints → no false long-put thesis ──")
P = occ('CAPR', '261023', 'P', 20)
H = Harness({P: None}, medians={P: 50}, oi={P: [('2026-10-16', 100)]}, p95={'CAPR': 50000})
H.spot('CAPR', T0, 21.0)
for i in range(8):
    t = T0 + i * 2 * SEC
    H.quote(P, t, 1.00, 1.10)
    H.trade(P, t + 50 * MS, 1.09 if i % 2 == 0 else 1.01, 200)
H.done()
oid, ver, d, _ = H.obs(P)
ck("UOA candidate (relative volume + OI)", d['rarity']['candidate'] and 'REL_VOLUME' in d['rarity']['screens'])
ck("no dominant side → NEUTRAL, never a long-put call", d['side_thesis']['state'] == 'NEUTRAL'
   and 'no_dominant_side' in d['leading_read_fail'])
ck("no card claims 'long put' / 'bought' / green", not any(('long put' in text_of(c).lower() and 'alternative' not in
   text_of(c).lower()) or 'bought to open' in text_of(c).lower() or c['payload']['embeds'][0]['color'] in
   (cards.GREEN, cards.RED) for c in H.cards))
H.close()

print("── put sell-side cluster → amber working hypothesis with alternatives ──")
H = Harness({P: None}, medians={P: 50}, oi={P: [('2026-10-16', 100)]}, p95={'CAPR': 50000})
for i in range(6):
    t = T0 + i * 2 * SEC
    H.quote(P, t, 1.00, 1.10)
    H.trade(P, t + 50 * MS, 1.01, 200)
H.done()
oid, ver, d, _ = H.obs(P)
th = d['side_thesis']
ck("gate passes → WORKING_HYPOTHESIS on the sell side", th['state'] == 'WORKING_HYPOTHESIS' and th['side'] == side.SELL)
ck("text: put-writing is a CONDITIONAL opening thesis + closing/package alternative",
   'conditional opening thesis' in th['read'] and 'sold to close' in th['alternative'])
wh_cards = [c for c in H.cards if c['kind'] == 'WORKING_HYPOTHESIS']
ck("posted amber, never green/red, with the research footer",
   wh_cards and wh_cards[-1]['payload']['embeds'][0]['color'] == cards.AMBER and cards.FOOTER in text_of(wh_cards[-1]))
ck("no PROBABLE / CONFIRMED / numeric probability on the card",
   not any(w in text_of(wh_cards[-1]) for w in ('PROBABLE', 'CONFIRMED', '80%', 'institutional')))
H.close()

print("── NET: earlier sell-side OI build + later lower ask-side buy → buyback ALTERNATIVE only ──")
C = occ('NET', '261106', 'C', 200)
H = Harness({C: None}, medians={C: 100}, p95={'NET': 50000},
            oi={C: [('2026-10-14', 1000), ('2026-10-15', 3000), ('2026-10-16', 2800)]})
for i in range(10):                                   # 2026-10-15 session: sell-side, VWAP ~3.00
    t = events.iso_to_ns('2026-10-15T15:00:00Z') + i * SEC
    H.store.x("INSERT INTO prints (key, occ, underlying, session, status, side, size, price, event_ns) VALUES "
              "(?,?,?,?,?,?,?,?,?)", (f"d1-{i}", C, 'NET', '2026-10-15', 'COUNTED',
                                      side.SELL if i < 8 else side.BUY, 300, 3.00, t))
for i in range(30):                                   # today: ask-side buys below 3.00
    t = T0 + i * SEC
    H.quote(C, t, 2.40, 2.50)
    H.trade(C, t + 50 * MS, 2.49, 300)
H.done()
oid, ver, d, _ = H.obs(C)
th = d['side_thesis']
ck("call buy-side working hypothesis", th.get('state') == 'WORKING_HYPOTHESIS' and th['side'] == side.BUY)
ck("buyback offered as an ALTERNATIVE (with new-longs/hedge caveat), not a BTC label",
   'buyback plausible' in (th.get('extra_alternative') or '') and 'new call longs or a hedge' in th['extra_alternative']
   and 'BTC' not in json.dumps(d))
H.close()

print("── HUM: 4:7 ratio from split fills (not 1:1) ──")
PU, CA = occ('HUM', '261120', 'P', 250), occ('HUM', '261120', 'C', 300)
H = Harness({PU: None, CA: None}, medians={PU: 100, CA: 100}, p95={'HUM': 1e6})
t = T0
for q in (1500, 1500, 1000):
    H.trade(PU, t, 3.0, q, x='C', cond='f'); t += 30 * MS
for q in (3000, 2500, 1500):
    H.trade(CA, t, 2.0, q, x='C', cond='f'); t += 30 * MS
H.spot('HUM', t + 5 * SEC, 270)                       # advances the watermark past the window
H.trade(occ('HUM', '261120', 'C', 310), t + 10 * SEC, 1.0, 1)
H.done()
pk = H.store.q("SELECT ratio, geometry, association, side_text, legs FROM packages WHERE status='CANDIDATE'")
ck("one package candidate, 4,000 puts vs 7,000 calls reduce to 4:7 (stored in leg order calls:puts = 7:4), not 1:1",
   len(pk) == 1 and sorted(map(int, pk[0][0].split(':'))) == [4, 7])
legs = json.loads(pk[0][4])
ck("split prints aggregated per series with constituent print ids kept",
   sorted(l['qty'] for l in legs) == [4000, 7000] and sum(len(l['print_keys']) for l in legs) == 6)
ck("complex tags + common venue but span > 10ms → near-time complex grade", pk[0][2] == 'C_NEAR_TIME_COMPLEX')
H.close()

print("── NKE: same-side vertical → debit/credit unresolved ──")
A1, A2 = occ('NKE', '261120', 'C', 80), occ('NKE', '261120', 'C', 85)
H = Harness({A1: None, A2: None}, medians={A1: 100, A2: 100}, p95={'NKE': 1e6})
H.quote(A1, T0, 2.00, 2.10); H.quote(A2, T0, 0.80, 0.90)
H.trade(A1, T0 + 50 * MS, 2.10, 500, x='C'); H.trade(A2, T0 + 52 * MS, 0.90, 500, x='C')
H.spot('NKE', T0 + 10 * SEC, 81)
H.done()
pk = H.store.q("SELECT ratio, geometry, side_text, conditional_cashflow, association FROM packages WHERE status='CANDIDATE'")
ck("vertical candidate 1:1, both legs at the ask", pk and pk[0][0] == '1:1' and pk[0][1] == 'VERTICAL_CANDIDATE')
ck("says 'spread candidate; debit/credit and initiator unresolved', no cashflow",
   pk[0][2] == 'spread candidate; debit/credit and initiator unresolved' and pk[0][3] is None)
ck("common venue within 10ms → B grade (descriptive, not a probability)", pk[0][4] == 'B_COMMON_VENUE_TIGHT')
H.close()

print("── CGON: conditional cashflow arithmetic; missing expiry ──")
legs = [{'occ': 'a', 'expiry': date(2026, 11, 20), 'right': 'C', 'strike': 10, 'qty': 1000, 'vwap': 1.5,
         'venues': ['C'], 'conds': ['I'], 'print_keys': ['k1'], 'prints': 1, 'start_ns': T0, 'end_ns': T0,
         'taker_side': side.BUY, 'complex_all': False, 'multiplier': 100},
        {'occ': 'b', 'expiry': date(2026, 11, 20), 'right': 'P', 'strike': 8, 'qty': 1000, 'vwap': 0.5,
         'venues': ['C'], 'conds': ['I'], 'print_keys': ['k2'], 'prints': 1, 'start_ns': T0, 'end_ns': T0,
         'taker_side': side.SELL, 'complex_all': False, 'multiplier': 100}]
ck("opposite-side legs → arithmetic 150,000 − 50,000 = 100,000 (conditional)", packages._cashflow(legs) == 100000.0)
legs[1]['expiry'] = None
ck("missing expiry → no arithmetic, geometry EXPIRY_UNKNOWN", packages._cashflow(legs) is None
   and taxonomy.geometry(legs) == 'EXPIRY_UNKNOWN_MULTI_LEG_CANDIDATE')
pkg = {'pkg_id': 'x', 'underlying': 'CGON', 'legs': [dict(legs[0]), dict(legs[1], expiry=date(2026, 11, 20))],
       'end_ns': T0, 'ratio': '1:1', 'geometry': 'STRANGLE_RISK_REVERSAL_OR_COLLAR_CANDIDATE',
       'side_text': 'x', 'association': 'D_TIME_SIZE_ONLY', 'conditional_cashflow': 100000.0}
ck("card shows the arithmetic ONLY as conditional on a verified linkage",
   'conditional on a verified linkage' in text_of(cards.package(pkg, rows=None) if False else cards.package(pkg)))

print("── APLD: catalyst published before the trade ──")
X = occ('APLD', '261023', 'C', 30)
rows = [{'symbol': 'APLD', 'event': 'earnings', 'event_time': '2026-10-22T16:05:00-04:00', 'timing': 'AMC',
         'source_url': 'https://example.invalid/ir', 'published_at': '2026-10-01T09:00:00-04:00',
         'observed_at': '2026-10-01T10:00:00-04:00', 'fixture': FIXTURE}]
H = Harness({X: None}, medians={X: 10}, oi={X: [('2026-10-16', 50)]}, p95={'APLD': 1000}, catalyst_rows=rows)
H.quote(X, T0, 1.0, 1.1)
H.trade(X, T0 + 50 * MS, 1.09, 300)
H.done()
d = H.obs(X)[2]
ck("event published before the print → VERIFIED, expiry after the event", d['event']['status'] == 'VERIFIED'
   and d['event']['mismatch'] is False)
H.close()
late = [dict(rows[0], published_at='2026-10-20T09:00:00-04:00')]
H = Harness({X: None}, medians={X: 10}, oi={X: [('2026-10-16', 50)]}, p95={'APLD': 1000}, catalyst_rows=late)
H.quote(X, T0, 1.0, 1.1); H.trade(X, T0 + 50 * MS, 1.09, 300); H.done()
ck("a post-print article cannot explain the earlier print", H.obs(X)[2]['event']['status'] == 'NONE_ON_FILE')
H.close()

print("── overlapping unrelated packages → segment or abstain; one print, one package ──")
legs_occ = [occ('OVR', '261120', r, k) for r, k in (('C', 10), ('C', 11), ('P', 9), ('P', 8), ('C', 12))]
H = Harness({o: None for o in legs_occ}, medians={o: 100 for o in legs_occ}, p95={'OVR': 1e6})
H.trade(legs_occ[0], T0, 1.0, 200, x='C'); H.trade(legs_occ[1], T0 + 2 * MS, 0.5, 200, x='C')
H.trade(legs_occ[2], T0 + 300 * MS, 1.0, 300, x='X'); H.trade(legs_occ[3], T0 + 302 * MS, 0.5, 300, x='X')
H.trade(legs_occ[4], T0 + 600 * MS, 0.3, 150, x='M')
H.spot('OVR', T0 + 10 * SEC, 10.0)
H.done()
pk = H.store.q("SELECT pkg_id, status, legs FROM packages")
ck("5 series in one window → segmented into venue/tight groups (not one 5-leg package)",
   all(len(json.loads(l)) <= 4 for _, _, l in pk) and any(s == 'CANDIDATE' for _, s, _ in pk))
assigned = H.store.q("SELECT print_key, COUNT(*) FROM package_prints GROUP BY print_key HAVING COUNT(*)>1")
ck("no print counted in two packages", not assigned)
H.close()

print("── corrections, duplicates (no trade id), late prints ──")
Y = occ('COR', '261023', 'C', 50)
H = Harness({Y: None}, medians={Y: 20}, oi={Y: [('2026-10-16', 10)]}, p95={'COR': 1e6})
H.quote(Y, T0, 1.0, 1.1)
H.trade(Y, T0 + 10 * MS, 1.09, 60)
H.trade(Y, T0 + 20 * MS, 1.09, 60)
H.trade(Y, T0 + 30 * MS, 1.09, 60, source='stream')
H.trade(Y, T0 + 10 * MS, 1.09, 60, source='backfill', recv=T0 + 5 * SEC)       # same print again
ck("stream + backfill copy of one print counted once", H.pipe.stats['duplicate'] == 1)
H.trade(Y, T0 + 10 * MS, 1.05, 70)            # same instant/venue/cond, other price/size: a DISTINCT fill
H.trade(Y, T0 + 30 * MS, 1.09, 60)            # an identical simultaneous fill (no trade id) — also distinct
ck("no trade id: simultaneous same-venue fills are distinct prints, all counted",
   H.pipe.stats['duplicate'] == 1 and H.obs(Y)[2]['side_mix']['captured'] == 310)
H.trade(Y, T0 + 30 * MS, 1.09, 60, source='backfill', recv=T0 + 6 * SEC)
H.trade(Y, T0 + 30 * MS, 1.09, 60, source='backfill', recv=T0 + 6 * SEC)
H.trade(Y, T0 + 30 * MS, 1.09, 60, source='backfill', recv=T0 + 6 * SEC)
ck("backfill dedupe matches multiplicity: 2 streamed copies absorb 2 backfill copies, the 3rd is new",
   H.pipe.stats['duplicate'] == 3 and H.obs(Y)[2]['side_mix']['captured'] == 370)
d0 = H.obs(Y)[2]
H.trade(Y, T0 + 40 * MS, 1.09, 60, cond='A')                                     # cancel one 60-lot
st = dict(H.store.q("SELECT status, COUNT(*) FROM prints WHERE occ=? GROUP BY status", (Y,)))
ck("cancel keeps BOTH records: original CANCELLED + CANCEL_RECORD", st.get('CANCELLED') == 1 and st.get('CANCEL_RECORD') == 1)
d1 = H.obs(Y)[2]
ck("corrected volume not double counted (370 → 310)", d0['side_mix']['captured'] == 370 and d1['side_mix']['captured'] == 310)
H.trade(Y, T0 + 50 * MS, 1.09, 5, cond='D')
r = H.store.q("SELECT late, side, side_reason FROM prints WHERE occ=? AND cond='D'", (Y,))[0]
ck("late-reported print: flagged late, side UNKNOWN", r[0] == 1 and r[1] == side.UNKNOWN)
H.close()

print("── earned screens are sticky; no downgrade flood ──")
Z = occ('STK', '261023', 'C', 50)
H = Harness({Z: None}, medians={Z: 1000}, oi={Z: [('2026-10-16', 10)]}, p95={'STK': 10000})
H.quote(Z, T0, 1.0, 1.1)
H.trade(Z, T0 + 10 * MS, 1.09, 300)                     # $32,700 ≥ 2×p95 → REL_PREMIUM + VOL_GT_OI
n_cards = len(H.cards)
for i in range(5):
    H.trade(Z, T0 + (20 + i) * MS, 1.09, 1)             # later small prints
d = H.obs(Z)[2]
ck("REL_PREMIUM earned once stays earned", 'REL_PREMIUM' in d['rarity']['screens'] and d['rarity']['candidate'])
ck("small later prints post nothing", len(H.cards) == n_cards)
H.close()

print("── DTE routing: 0DTE + cross-expiry one home ──")
Z0 = occ('RTE', '261019', 'C', 50)
Z30 = occ('RTE', '261120', 'C', 50)
for order in ((Z30, Z0), (Z0, Z30)):
    H = Harness({Z0: None, Z30: None}, medians={Z0: 100, Z30: 100}, p95={'RTE': 1e6})
    H.trade(order[0], T0, 1.0, 400, x='C', cond='f'); H.trade(order[1], T0 + 3 * MS, 2.0, 400, x='C', cond='f')
    H.spot('RTE', T0 + 10 * SEC, 50)
    H.done()
    pc = [c for c in H.cards if c['kind'] == 'PACKAGE']
    ck(f"calendar homes in zero_dte regardless of arrival order ({'far first' if order[0] == Z30 else 'near first'}), "
       f"all expiries shown", len(pc) == 1 and pc[0]['channel'] == 'zero_dte'
       and '2026-11-20' in text_of(pc[0]) and '2026-10-19' in text_of(pc[0]))
    H.close()

print("── unknown spot leaves the OTM screen MISSING ──")
W = occ('SPT', '261021', 'C', 60)
H = Harness({W: None}, medians={W: 10}, oi={W: [('2026-10-16', 10)]}, p95={'SPT': 1e6})
H.quote(W, T0, 1.0, 1.1); H.trade(W, T0 + 10 * MS, 1.09, 100); H.done()
d = H.obs(W)[2]
ck("no spot → SHORT_DATED_OTM not earned, input recorded missing",
   'SHORT_DATED_OTM' not in d['rarity']['screens'] and 'spot' in d['rarity']['missing'])
H.close()

print("── OI accounting ──")
H = Harness({Y: None})
H.store.x("INSERT INTO oi_vintages VALUES (?,?,?,?)", (Y, '2026-10-15', 1000, 'x'))
H.store.x("INSERT INTO oi_vintages VALUES (?,?,?,?)", (Y, '2026-10-16', 3000, 'x'))
H.store.x("INSERT INTO daily_volume VALUES (?,?,?,?,?)", (Y, '2026-10-16', 500, None, 'bars'))
ck("|ΔOI| > V → RECONCILE_REQUIRED", oi_mod.interval(H.store, Y, '2026-10-15', '2026-10-16')['label'] == 'RECONCILE_REQUIRED')
H.store.x("UPDATE daily_volume SET volume=4000 WHERE occ=?", (Y,))
iv = oi_mod.interval(H.store, Y, '2026-10-15', '2026-10-16')
ck("V=4000 Δ=2000 → OPENING_SUPPORTED with OO∈[2000,3000]", iv['label'] == 'OPENING_SUPPORTED'
   and iv['bounds']['oo_min'] == 2000 and iv['bounds']['oo_max'] == 3000)
H.store.x("INSERT INTO oi_vintages VALUES (?,?,?,?)", (Y, '2026-10-12', 900, 'x'))
ck("incomplete intervening volume → INCONCLUSIVE", oi_mod.interval(H.store, Y, '2026-10-12', '2026-10-15')['label']
   == 'INCONCLUSIVE')
H.close()

print("── possible roll (never an account migration) ──")
OLD, NEW = occ('ROL', '261023', 'C', 100), occ('ROL', '261120', 'C', 110)
H = Harness({OLD: None, NEW: None})
for o, a, b in ((OLD, 5000, 3000), (NEW, 100, 2100)):
    H.store.x("INSERT INTO oi_vintages VALUES (?,?,?,?)", (o, '2026-10-15', a, 'x'))
    H.store.x("INSERT INTO oi_vintages VALUES (?,?,?,?)", (o, '2026-10-16', b, 'x'))
for o, t in ((OLD, T0), (NEW, T0 + 30 * SEC)):
    H.store.x("INSERT INTO prints (key, occ, session, status, size, price, event_ns) VALUES (?,?,?,?,?,?,?)",
              (o + 'k', o, '2026-10-16', 'COUNTED', 2000, 1.0, t))
rolls = oi_mod.possible_rolls(H.store, 'ROL', '2026-10-16', {o: {**H.contracts[o]} for o in (OLD, NEW)})
ck("old OI down + new OI up, same vintage, nearby prints → POSSIBLE_ROLL ROLL_UP_AND_OUT",
   rolls and rolls[0]['label'] == 'POSSIBLE_ROLL' and rolls[0]['candidates'][0]['geometry'] == 'ROLL_UP_AND_OUT'
   and 'not a confirmed account migration' in rolls[0]['text'])
H.close()

print("── known-side taxonomy ──")
lc = {'expiry': date(2026, 11, 20), 'right': 'C', 'strike': 100}
ck("short call without verified stock is NOT covered", taxonomy.classify_known([{**lc, 'qty': -1}])['tag'] == 'SHORT_CALL')
ck("short call + verified 100 shares → COVERED_CALL",
   taxonomy.classify_known([{**lc, 'qty': -1}], stock_qty_verified=100)['tag'] == 'COVERED_CALL')
sp = taxonomy.classify_known([{**lc, 'right': 'P', 'qty': -1}])
ck("short put without collateral → SHORT_PUT with downside note", sp['tag'] == 'SHORT_PUT' and 'downside' in sp['note'])
ck("bull call debit vertical", taxonomy.classify_known([{**lc, 'qty': 1}, {**lc, 'strike': 110, 'qty': -1}])['tag']
   == 'BULL_CALL_DEBIT_VERTICAL')
ck("unequal-wing butterfly recognised", taxonomy.classify_known([{**lc, 'strike': 100, 'qty': 1},
   {**lc, 'strike': 105, 'qty': -2}, {**lc, 'strike': 115, 'qty': 1}])['tag'] == 'BROKEN_WING_BUTTERFLY')
ck("ROLL_UP is geometry (higher strike), not bullish", taxonomy.roll_label(lc, {**lc, 'strike': 110}) == 'ROLL_UP')

print("── forced 30-second disconnect: backfill + replay reach the same versioned state ──")
F1, F2 = occ('FDX', '261023', 'C', 250), occ('FDX', '261023', 'P', 240)
def run(disconnect):
    H = Harness({F1: None, F2: None}, medians={F1: 50, F2: 50}, oi={F1: [('2026-10-16', 50)], F2: [('2026-10-16', 50)]},
                p95={'FDX': 1e6})
    H.spot('FDX', T0, 245)
    for i in range(6):                                         # F2 trades only before the gap
        t = T0 + i * SEC
        H.quote(F2, t, 1.0, 1.1); H.trade(F2, t + 50 * MS, 1.01, 200)
    gap_a, gap_b = T0 + 10 * SEC, T0 + 40 * SEC
    if disconnect:
        H.status('feed_down', gap_a, reason='forced test disconnect')
        H.status('feed_up', gap_b)
        for i in range(6):                                     # F1 prints that happened IN the gap, via backfill
            t = gap_a + (i + 1) * 3 * SEC
            H.trade(F1, t, 2.09, 200, source='backfill', recv=gap_b + i * MS)
        H.status('backfill_done', gap_b + SEC, gap_start_ns=gap_a, gap_end_ns=gap_b, complete=True)
    else:
        for i in range(6):
            t = gap_a + (i + 1) * 3 * SEC
            H.quote(F1, t - 10 * MS, 2.0, 2.1); H.trade(F1, t, 2.09, 200)
    H.done()
    return H
live = run(True)
dig_live = state_digest(live.store, SESSION.isoformat())
rp = replay(SESSION.isoformat(), src_db=live.db, out_db=os.path.join(live.dir, 'replay.db'),
            archive_dir=os.path.join(live.dir, 'raw'))
dig_rep = state_digest(rp.store, SESSION.isoformat())
ck("replay of the archive reproduces the live versioned state exactly (non-trivial state)",
   dig_live == dig_rep and len(dig_live['observations']) == 2 and dig_live['prints'])
d_gap = live.obs(F1)[2]
ck("gap prints keep side UNKNOWN (quotes unrecoverable) and the contract is context only",
   d_gap['side_mix']['unknown'] == 1200 and d_gap['coverage']['context_only']
   and d_gap['side_thesis']['state'] == 'NEUTRAL')
clean = run(False)
ck("an unaffected contract reaches the same state as a no-disconnect run",
   live.obs(F2)[2]['side_thesis'] == clean.obs(F2)[2]['side_thesis']
   and live.obs(F2)[2]['rarity'] == clean.obs(F2)[2]['rarity'])
ck("without the gap the same F1 flow could form a thesis (so the gap DISABLED it, not the data)",
   clean.obs(F1)[2]['side_thesis']['state'] == 'WORKING_HYPOTHESIS')
ck("a degradation notice was published", any(c['kind'] == 'DEGRADATION' for c in live.cards))
inc = live.store.q("SELECT recovery FROM incidents WHERE kind='FEED_DISCONNECT'")
ck("incident records recovery status (trades backfilled, quotes missing)", inc and inc[0][0] == 'TRADES_BACKFILLED_QUOTES_MISSING')
rp.store.close(); live.close(); clean.close()

print("── campaigns ──")
K1, K2 = occ('CMP', '261023', 'C', 50), occ('CMP', '261023', 'C', 55)
H = Harness({K1: None, K2: None}, medians={K1: 10, K2: 10}, oi={K1: [('2026-10-16', 10)], K2: [('2026-10-16', 10)]},
            p95={'CMP': 1e6})
for o in (K1, K2):
    for i in range(4):
        t = T0 + i * SEC + (0 if o == K1 else 20 * SEC)
        H.quote(o, t, 1.0, 1.1); H.trade(o, t + 50 * MS, 1.09, 100)
H.done()
ck("same issuer/expiry/right/side observations share one durable campaign id with separate signal ids",
   H.obs(K1)[3] == H.obs(K2)[3] and H.obs(K1)[0] != H.obs(K2)[0])
K3 = occ('CMP', '261023', 'P', 45)
H.contracts[K3] = {'underlying': 'CMP', 'expiry': '2026-10-23', 'right': 'P', 'strike': 45.0, 'multiplier': 100, 'adjusted': 0}
H.store.x("INSERT INTO baselines VALUES (?,?,?,?,?,?,?,?,?,?)", (K3, 'series_median_volume', SESSION.isoformat(), 10, 20,
          '2026-10-16', 'x', 'OK', 'ok', 'test'))
H.pipe.base._cache.clear()
for i in range(4):
    t = T0 + 60 * SEC + i * SEC
    H.quote(K3, t, 1.0, 1.1); H.trade(K3, t + 50 * MS, 1.01, 100)
ck("an opposite-side campaign coexists; the earlier one is not auto-closed",
   H.obs(K3)[3] != H.obs(K1)[3] and H.store.q("SELECT COUNT(*) FROM campaigns WHERE state='OPEN'")[0][0] == 2)
H.close()

print("── private watches + fill cards ──")
import follow
H = Harness({K1: None})
H.store.x("INSERT INTO watches VALUES (?,?,?,?,?,?,?,?,?,?)", ('w1', 'alice', 'LONG_CALL', json.dumps([{'occ': K1, 'qty': 1}]),
          T0, None, 0, '{}', 1, 'x'))
try:
    follow._owned(H.store, 'w1', 'mallory'); ok = False
except SystemExit:
    ok = True
ck("another owner cannot touch a watch", ok)
H.pipe.watch_legs = {K1: ['w1']}
H.trade(K1, T0, 1.0, 5)
wc = [c for c in H.cards if c['kind'] == 'WATCHED_ACTIVITY']
ck("watched-contract print → PRIVATE amber card, explicitly not assigned to the user",
   wc and wc[0]['private'] and wc[0]['channel'] == 'private' and 'NOT assigned to your position' in text_of(wc[0]))
ck("no P/L without signed qty AND a recorded fill", follow.pnl([{'occ': K1, 'qty': 1}], None, {K1: 2.0}) is None
   and follow.pnl([{'occ': K1, 'qty': 1}], {'leg_prices': {K1: 1.5}}, {K1: 2.0}) == 50.0)
try:
    cards.fill_card({'watch_id': 'w1'}, {'action': 'BUY', 'contract': K1, 'qty': 1, 'price': 1, 'time': 't',
                                         'expiry': 'e', 'verified': False}); ok = False
except ValueError:
    ok = True
ck("an unverified fill can never produce a green/red card", ok)
fc = cards.fill_card({'watch_id': 'w1'}, {'action': 'SELL', 'contract': K1, 'qty': 1, 'price': 2, 'time': 't',
                                          'expiry': 'e', 'verified': True})
ck("verified user fill → red SELL in the private feed only", fc['payload']['embeds'][0]['color'] == cards.RED
   and fc['channel'] == 'private')
H.close()

print("── delivery: no mentions; per-channel 429 isolation ──")
tmp = tempfile.mkdtemp()
config.NOTIFY_OUTBOX_DB = os.path.join(tmp, 'ob.db')
notify.register_webhook('tape:zero_dte', 'https://discord.invalid/api/webhooks/1/a')
notify.register_webhook('tape:weekly', 'https://discord.invalid/api/webhooks/2/b')
calls = []
class R:
    def __init__(s, c, b): s.status_code, s._b, s.headers, s.text = c, b, {}, ''
    def json(s): return s._b
def fake(url, params=None, json=None, timeout=None):
    calls.append((url, json))
    return R(429, {'retry_after': 30}) if url.endswith('/a') else R(200, {'id': str(len(calls))})
notify.requests.post = fake
notify.enqueue({'content': '@everyone hi'}, signal_id='s1', alias='tape:zero_dte')
notify.enqueue({'content': 'b'}, signal_id='s2', alias='tape:weekly')
notify.flush()
ck("payloads suppress @everyone (allowed_mentions empty)", all(j['allowed_mentions'] == {'parse': []} for _, j in calls))
ck("a 429 on one channel does not block another channel", any(u.endswith('/b') for u, _ in calls))
import sqlite3
con = sqlite3.connect(config.NOTIFY_OUTBOX_DB)
st = dict(con.execute("SELECT alias, status FROM outbox").fetchall()); con.close()
ck("rate-limited card stays PENDING (not lost), other SENT", st == {'tape:zero_dte': 'PENDING', 'tape:weekly': 'SENT'})
ck("webhook tokens never stored", 'webhooks/1/a' not in open(config.NOTIFY_OUTBOX_DB, 'rb').read().decode('latin1'))
shutil.rmtree(tmp, ignore_errors=True)

print("── provenance ──")
H = Harness({Y: None}, medians={Y: 1})
H.trade(Y, T0, 1.0, 1)
H.store.flush()
r = H.store.q("SELECT parser_version, cond_map_version, rule_version, checksum FROM prints")[0]
ck("every print carries parser / condition-map / rule versions + payload checksum",
   r[0] == settings.PARSER_VERSION and r[1] == conditions.COND_MAP_VERSION and r[2] == settings.RULE_VERSION and r[3])
arch = list(H.store.read_archive(SESSION.isoformat()))
ck("raw archive holds the original message before derivation (seq order, checksum, raw payload)",
   arch and arch[-1]['kind'] == 'trade' and arch[-1]['payload']['raw']['c'] == 'I' and arch[-1]['checksum'])
H.close()

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
