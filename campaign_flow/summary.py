"""End-of-day counts for the ACTIVE campaign-flow policy, read from its own journal (not the legacy engine's
attrition counters, which describe a policy that no longer orders). Every number is bounded to one NY session.

    funnel   windows with volume → eligible shocks → accepted (premium rose) → candidate evaluations
             (unique clusters) → proposals → entry orders → fills → cards (journaled / published)
    reasons  invalid-window reasons, window-qualification reasons, WATCH reasons, contract-level reasons
    timing   QUOTE_TIMING rows (quotes that still led the decision time after the receipt-time fix)
"""
import json
from collections import Counter
from datetime import date

from campaign_flow import calendar_ny as cal

_GENERIC = 'NO_VERIFIED_ONE_SIDED_CONTROL'          # added to every non-certified WATCH; says nothing new


def session_summary(j, session: str) -> dict:
    b = cal.bounds(date.fromisoformat(session))
    lo, hi = (b[0] - 3600, b[1] + 3600) if b else (0, 0)

    def rows(kind):
        return [json.loads(r[0]) for r in j.con.execute(
            "SELECT body FROM log WHERE kind=? AND ts BETWEEN ? AND ? ORDER BY seq", (kind, lo, hi))]

    wins, bad = rows('WINDOW'), rows('WINDOW_REJECTED')
    watch, props = rows('CANDIDATE_WATCH'), rows('PROPOSAL')
    el = [w for w in wins if w['qual']['eligible']]
    uniq = {(r['ticker'], r['direction'],
             tuple(sorted(cl['members'][0] for k in ('C', 'P') for cl in r['assessment']['clusters'].get(k, []))))
            for r in watch + props}
    camps = [c for c in j.campaigns() if c['session'] == session]
    cids = {c['campaign_id'] for c in camps}
    orders = [o for o in j.orders() if o['campaign_id'] in cids]
    fills = [f for f in j.fills() if f['campaign_id'] in cids and f['accepted']]
    cards = [c for c in j.cards() if lo <= c['ts'] <= hi]
    return {
        'session': session,
        'windows': len(wins), 'invalid_windows': len(bad),
        'invalid_reasons': dict(Counter(r for x in bad for r in x['reasons']).most_common(4)),
        'eligible_shocks': len(el), 'accepted_shocks': sum(1 for w in el if w['qual']['accepted']),
        'qual_reasons': dict(Counter(r for w in wins for r in w['qual']['reasons']).most_common(5)),
        'evaluations': len(watch) + len(props), 'unique_candidates': len(uniq),
        'watch': len(watch), 'proposals': len(props),
        'watch_reasons': dict(Counter(r for w in watch for r in w['reasons'] if r != _GENERIC).most_common(5)),
        'contract_reasons': dict(Counter(r for w in watch for c in w.get('contract_journal') or []
                                         for r in c['reasons']).most_common(4)),
        'campaigns': dict(Counter(c['state'] for c in camps)),
        'entry_orders': sum(1 for o in orders if o['kind'] == 'ENTRY'),
        'exit_orders': sum(1 for o in orders if o['kind'] == 'EXIT'),
        'fills': dict(Counter(f"{f['kind']}/{f.get('source')}" for f in fills)),
        'cards': len(cards), 'cards_published': sum(1 for c in cards if c['published']),
        'quote_timing_rows': len(rows('QUOTE_TIMING')),
        'incidents': len(rows('INCIDENT')) + len(rows('RECONCILIATION_EXCEPTION')),
    }


def _kv(d: dict) -> str:
    return ', '.join(f"{k} {v}" for k, v in d.items()) or '—'


def summary_text(s: dict, mode: str, outbox: dict = None, polls: int = None) -> str:
    lines = [
        f"📊 Campaign-flow EOD {s['session']} [{mode}]" + (f" — {polls} polls" if polls is not None else ''),
        f"Windows {s['windows']} (invalid {s['invalid_windows']}: {_kv(s['invalid_reasons'])}) → eligible shocks "
        f"{s['eligible_shocks']} → accepted {s['accepted_shocks']}",
        f"Candidate evaluations {s['evaluations']} ({s['unique_candidates']} unique) → WATCH {s['watch']} → "
        f"PROPOSED {s['proposals']} → entry orders {s['entry_orders']} → fills {_kv(s['fills'])}",
        f"WATCH reasons: {_kv(s['watch_reasons'])}",
        f"Contract reasons: {_kv(s['contract_reasons'])}",
        f"Window qualification: {_kv(s['qual_reasons'])}",
        f"Campaigns: {_kv(s['campaigns'])} | cards {s['cards']} (published {s['cards_published']})"
        + (f" | outbox {_kv(outbox)}" if outbox else ''),
    ]
    if s['quote_timing_rows'] or s['incidents']:
        lines.append(f"Quote-timing rows {s['quote_timing_rows']} | incidents {s['incidents']}")
    return '\n'.join(lines)
