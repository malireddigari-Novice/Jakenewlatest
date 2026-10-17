"""
Tape-lane Discord cards (flow handoff §9). Short, one layout:

  title        ticker + contract (or ratioed legs)
  Observed     New York time · DTE · channel
  status line  plain English (description)
  Facts        two or three strongest observed facts: volume vs history / OI, quote + condition quality
  Read         ONE conditional interpretation with its best alternative
  Next check   the one check that could change the read
  Catalyst     at most one short conditional sentence (or "unverified/none")
  footer       stable signal id + version, and the research disclaimer

Blue = observation. Amber = working hypothesis, watched activity or a revision. Green BUY / red SELL
exist ONLY for a user-recorded, verified fill in the private followed-trades feed (`fill_card`) — the
bot never fabricates one from market data. No card mentions anyone (allowed_mentions is empty). Full
print/quote/OI evidence and every threshold stay in the tape DB under the signal id.
"""
import hashlib
import json

from analysis import catalyst as catalyst_mod
from analysis import channels
from tape import events, settings
from tape.side import BUY, SELL

BLUE, AMBER, GREEN, RED, GREY = 0x3498DB, 0xF1C40F, 0x2ECC71, 0xE74C3C, 0x95A5A6
FOOTER = "For research only. Not investment advice. Verify fills and manage your own risk."

_STATUS = {
    'NEW_OBSERVATION': 'Observation — unusual relative activity (research candidate, not a trade).',
    'WORKING_HYPOTHESIS': 'Working hypothesis — a conditional side thesis, not a verified position.',
    'THESIS_WEAKENED': 'Revision — the working hypothesis no longer meets its gate.',
    'INVALIDATED': 'Revision — a correction removed the evidence behind this observation.',
    'CONVEXITY_CONTEXT_CHANGED': 'Revision — a sibling leg suggests this print may belong to a package.',
    'OI_ANNOTATION': 'Revision — next-session open interest is in (aggregate, never who traded).',
    'DEGRADED': 'Degraded — feed coverage gap; this observation is context only.',
    'POSSIBLE_ROLL': 'Revision — POSSIBLE_ROLL (not a confirmed account migration).',
    'POSSIBLE_EXIT': 'Revision — POSSIBLE_EXIT research clue (quietness alone proves nothing).',
    'EXPIRED': 'Expired.',
}


def thesis_text(right: str, side: str) -> dict:
    """One conditional interpretation plus its alternatives — never BTO/STO/BTC/STC."""
    c = right == 'C'
    if side == BUY:
        read = (f"{'call' if c else 'put'} buying — opening long {'calls' if c else 'puts'} is ONE reading"
                + ('' if c else ' (or a hedge)'))
        alt = f"short {'calls' if c else 'puts'} being bought back to close, or one leg of a spread/hedge"
    else:
        read = f"{'call' if c else 'put'}-writing is a conditional opening thesis"
        alt = f"long {'calls' if c else 'puts'} sold to close, or a package/hedge leg"
    return {'read': read, 'alternative': alt}


def _hash(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _occ_label(d) -> str:
    return f"{d['underlying']} {d['expiry']} {d['strike']:g}{d['right']}"


def _observed(at_ns, dte) -> str:
    when = events.ny_dt(at_ns).strftime('%H:%M:%S ET') if at_ns else 'next session'
    return f"{when} · DTE {dte if dte is not None else 'UNKNOWN'} · `{channels.dte_bucket(dte)}`"


def _facts(d) -> str:
    r, b, m = d['rarity'], d['baseline'], d['side_mix']
    out = []
    if 'REL_VOLUME' in r['screens']:
        out.append(f"Volume **{m['captured']:,}** = **{r['screens']['REL_VOLUME']}×** its 20-session median "
                   f"({b['median']:g}, n={b['median_n']})")
    elif b['median'] is None:
        out.append(f"Volume {m['captured']:,} — series history UNKNOWN ({r['missing'].get('series_median', 'missing')})")
    if b['prior_oi'] is not None:
        out.append(f"vs prior OI **{b['prior_oi']:,}** (as of {b['oi_as_of']})")
    else:
        out.append("prior OI UNKNOWN")
    if 'REL_PREMIUM' in r['screens']:
        out.append(f"largest print premium {r['screens']['REL_PREMIUM']}× the name's p95")
    q = d.get('executability') or {}
    qline = (f"quote {q['bid']}×{q['ask']} ({q['age_ms']:.0f}ms old)" if q.get('bid') is not None else "quote UNKNOWN")
    side = (f"taker side: buy {100*m['buy_share']:.0f}% / sell {100*m['sell_share']:.0f}% / "
            f"UNKNOWN {100*m['unknown_share']:.0f}% over {m['prints']} prints")
    return ' · '.join(out[:2]) + f"\n{side}\n{qline}"


def _read(d) -> str:
    t = d['side_thesis']
    if t.get('state') == 'WORKING_HYPOTHESIS':
        s = f"**If** this is a real position: {t['read']}. Alternative: {t['alternative']}."
        if t.get('extra_alternative'):
            s += f"\n{t['extra_alternative']}"
        return s
    if d['linkage']:
        return "Neutral — the print overlaps a package candidate; its outright meaning is unresolved."
    return "Neutral observation — who opened or closed is not visible on the public tape."


def _next(d) -> str:
    fails = d.get('leading_read_fail') or []
    revs = [r['kind'] for r in d.get('revisions') or []]
    if revs and revs[-1] == 'INVALIDATED':
        return "whether new prints re-earn the screens (the corrected data no longer qualifies)"
    if d['coverage']['context_only']:
        return "whether coverage is restored (gap prints keep side UNKNOWN)"
    if d['side_thesis'].get('state') == 'WORKING_HYPOTHESIS':
        if d['urgency']['dte'] == 0:
            return "whether the side mix holds over the next prints (0DTE: no next-session OI before expiry)"
        return "next session's OI change vs full-session volume (≥50% would support aggregate opening)"
    order = [('prior_oi_missing', 'the next dated OI vintage (prior OI missing)'),
             ('suspected_package', 'whether the package linkage resolves (sibling-leg OI next session)'),
             ('no_dominant_side', 'whether one taker side reaches 60% of captured volume'),
             ('too_much_unknown_side', 'whether classified prints bring UNKNOWN side under 25%'),
             ('volume_not_3x_oi', 'whether session volume exceeds 3× prior OI'),
             ('too_few_contracts', 'whether ordinary electronic volume reaches 500 contracts'),
             ('too_few_ordinary_prints', 'more ordinary electronic prints (auction/complex prints keep side open)')]
    for k, txt in order:
        if k in fails:
            return txt
    return "the next print"


def observation(obs: dict, kind: str, at_ns: int) -> dict:
    d = obs['dims']
    amber = kind != 'NEW_OBSERVATION' or d['side_thesis'].get('state') == 'WORKING_HYPOTHESIS'
    fields = [
        {'name': 'Observed', 'value': _observed(at_ns, d['urgency']['dte']), 'inline': False},
        {'name': 'Facts', 'value': _facts(d)[:1000], 'inline': False},
        {'name': 'Read', 'value': _read(d)[:1000], 'inline': False},
        {'name': 'Next check', 'value': _next(d), 'inline': False},
        {'name': 'Catalyst', 'value': d['event']['sentence'], 'inline': False},
    ]
    if d.get('oi_annotation') and kind == 'OI_ANNOTATION':
        a = d['oi_annotation']
        fields.insert(2, {'name': 'OI (aggregate)', 'value': (
            f"**{a['label']}** — ΔOI {a.get('delta')} vs full-session volume {a.get('volume')}; "
            f"opening contracts between {a['bounds']['oo_min']:,} and {a['bounds']['oo_max']:,}. "
            f"Never identifies the earlier trader." if a.get('bounds') else a['label']), 'inline': False})
    if d['coverage']['context_only']:
        fields.insert(1, {'name': '⚠ Coverage', 'value': f"context only — {d['coverage']['reason']}", 'inline': False})
    payload = {'embeds': [{
        'title': f"{'🟡' if amber else '🔵'} {_occ_label(d)}",
        'description': _STATUS.get(kind, kind),
        'color': AMBER if amber else BLUE,
        'fields': fields,
        'footer': {'text': f"signal {obs['obs_id']} v{obs['version']} · {FOOTER}"},
    }]}
    return {'signal_id': obs['obs_id'], 'version': obs['version'], 'kind': kind,
            'channel': d['urgency']['channel'], 'payload': payload, 'evidence_hash': _hash(d), 'at_ns': at_ns}


def package(pkg: dict, catalyst_rows=None) -> dict:
    legs = pkg['legs']
    at = events.ny_dt(pkg['end_ns'])
    home = channels.home_bucket([l['expiry'] for l in legs if l['expiry']], at)
    earliest = min((l['expiry'] for l in legs if l['expiry']), default=None)
    dte = channels.dte_ny(earliest, at) if earliest else None
    leg_lines = '\n'.join(f"`{l['qty']:>6,}` {l['expiry']} {l['strike']:g}{l['right']} @ VWAP {l['vwap']} "
                          f"· {'/'.join(l['venues'])} · cond {''.join(l['conds'])} · taker {l['taker_side']}"
                          for l in legs)
    cash = (f"\nIF linked, listed-leg arithmetic = ${pkg['conditional_cashflow']:,.0f} (conditional on a verified "
            f"linkage — not an executed net debit/credit)" if pkg['conditional_cashflow'] is not None else '')
    cat = catalyst_mod.assess(pkg['underlying'], at, earliest, rows=catalyst_rows)['sentence']
    payload = {'embeds': [{
        'title': f"🔵 {pkg['underlying']} package candidate {pkg['ratio']} — {pkg['geometry']}",
        'description': f"{pkg['side_text']}.",
        'color': BLUE,
        'fields': [
            {'name': 'Observed', 'value': _observed(pkg['end_ns'], dte) + f" (all expiries shown)", 'inline': False},
            {'name': 'Legs', 'value': leg_lines[:1000], 'inline': False},
            {'name': 'Association', 'value': f"{pkg['association']} — descriptive grade, not a probability or a "
                                             f"proven parent order{cash}", 'inline': False},
            {'name': 'Next check', 'value': 'next-session OI on each leg (a far leg is not presumed to survive the front '
                                            'leg without reconciliation)', 'inline': False},
            {'name': 'Catalyst', 'value': cat, 'inline': False},
        ],
        'footer': {'text': f"package {pkg['pkg_id']} v1 · {FOOTER}"},
    }]}
    return {'signal_id': pkg['pkg_id'], 'version': 1, 'kind': 'PACKAGE', 'channel': home,
            'payload': payload, 'evidence_hash': _hash(pkg), 'at_ns': pkg['end_ns']}


def degradation(session, p: dict, recv_ns: int) -> dict:
    payload = {'embeds': [{
        'title': '🔵 Feed degraded — tape lane',
        'description': (f"Options feed disconnected ({p.get('reason') or 'unknown'}). Prints in the gap are "
                        f"backfilled where possible but quotes cannot be, so their side stays UNKNOWN and affected "
                        f"contracts are context only."),
        'color': GREY, 'footer': {'text': FOOTER}}]}
    sid = f"feed|{session}|{recv_ns}"
    return {'signal_id': sid, 'version': 1, 'kind': 'DEGRADATION', 'channel': 'zero_dte', 'payload': payload,
            'evidence_hash': _hash(p), 'at_ns': recv_ns}


def watched_activity(watch_id: str, rec: dict) -> dict:
    payload = {'embeds': [{
        'title': f"🟡 Watched contract activity — {rec['occ']}",
        'description': (f"{rec['size']:,} @ {rec['price']} ({rec['exchange']}, cond {rec['cond']}, taker "
                        f"{rec['side']}). Market activity only — it is NOT assigned to your position."),
        'color': AMBER, 'footer': {'text': f"watch {watch_id} · {FOOTER}"}}]}
    return {'signal_id': f"watch|{watch_id}|{rec['key']}", 'version': 1, 'kind': 'WATCHED_ACTIVITY',
            'channel': 'private', 'payload': payload, 'evidence_hash': _hash(rec), 'at_ns': rec['event_ns']}


def fill_card(watch: dict, fill: dict) -> dict:
    """GREEN BUY / RED SELL — only for a fill the user recorded and marked verified."""
    if not fill.get('verified'):
        raise ValueError('fill cards require a user-verified fill')
    buy = fill['action'] == 'BUY'
    payload = {'embeds': [{
        'title': f"{'🟢 BUY' if buy else '🔴 SELL'} {fill['contract']} × {fill['qty']}",
        'description': (f"User-recorded fill @ **{fill['price']}** at {fill['time']} (expiry {fill['expiry']}). "
                        f"Recorded by its owner; not generated from market data."),
        'color': GREEN if buy else RED, 'footer': {'text': f"watch {watch['watch_id']} · {FOOTER}"}}]}
    return {'signal_id': f"fill|{watch['watch_id']}|{fill['time']}", 'version': 1, 'kind': 'USER_FILL',
            'channel': 'private', 'payload': payload, 'evidence_hash': _hash(fill), 'at_ns': 0}
