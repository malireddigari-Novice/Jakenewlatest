"""§15 Compact public Discord cards: ENTRY_PROPOSED / ENTRY_FILLED / EXIT_PROPOSED / EXIT_FILLED.

Green for entry, red for exit. A proposed card shows an "Indicative quote" and "Planned contracts"; a filled
card shows the "Actual fill" and "Contracts". An EXIT_FILLED return is computed only from actual fills:
(exit fill / weighted average actual entry fill - 1) * 100, signed, one decimal, "(fills)", fees excluded.
Scores, OI zones, percentiles, windows, gates and diagnostics stay in the journal, never on the card.
Untrusted identity/reason fields are validated: no line breaks, '@', backticks, '<' or '>'; length limits.
"""
from datetime import date

from campaign_flow import calendar_ny as cal

GREEN, RED = 0x2ECC71, 0xE74C3C
FOOTER = 'Paper simulation · Options can lose 100% · Not investment advice.'
LABELS = ('ENTRY_PROPOSED', 'ENTRY_FILLED', 'EXIT_PROPOSED', 'EXIT_FILLED')
_BAD = ('\n', '\r', '@', '`', '<', '>')

REASON_TEXT = {
    'FAVORABLE_REGULAR_SESSION_OPEN_GAP_SELL_ALL': 'Favorable open gap',
    'PLANNED_OR_EXPIRY_EXIT_DEADLINE': 'Planned/expiry deadline',
    'PRECOMMITTED_UNDERLYING_INVALIDATION': 'Precommitted underlying invalidation',
    'PRECOMMITTED_PREMIUM_RISK_LIMIT': 'Precommitted premium risk limit',
    'CONFIRMED_OPPOSITE_CLUSTER_ROTATION': None,          # filled per direction below
    'EXPIRATION_ZERO_VALUE': 'Expired worthless (zero-value record)',
}


class CardError(ValueError):
    pass


def _clean(name, v, limit) -> str:
    s = str(v)
    if len(s) > limit:
        raise CardError(f'{name} longer than {limit}')
    if any(ch in s for ch in _BAD):
        raise CardError(f'{name} contains a forbidden character')
    return s


def contract_text(c: dict) -> tuple:
    k = float(c['strike'])
    ks = f"{k:g}" if k != int(k) else f"{int(k)}"
    d = date.fromisoformat(str(c['expiry']))
    return f"{c['ticker']} {ks}{c['right']}", f"{d.strftime('%b')} {d.day}"


def reason_text(reasons, direction: str) -> str:
    out = []
    for r in reasons or []:
        if r == 'CONFIRMED_OPPOSITE_CLUSTER_ROTATION':
            out.append('Confirmed opposite put cluster' if direction == 'BULLISH' else 'Confirmed opposite call cluster')
        elif REASON_TEXT.get(r):
            out.append(REASON_TEXT[r])
    return '; '.join(out) or 'Recorded exit'


def render(label: str, campaign: dict, *, ts: float, price=None, qty=None, reasons=None,
           avg_entry=None, partial_remaining=None) -> dict:
    if label not in LABELS:
        raise CardError(f'unknown label {label}')
    ctext, exp = contract_text(campaign['contract'])
    cid = _clean('campaign_id', campaign['campaign_id'], 80)
    _clean('contract', ctext, 80)
    entry = label.startswith('ENTRY')
    filled = label.endswith('FILLED')
    if qty is None or int(qty) <= 0:
        raise CardError('quantity required')
    if filled and (price is None or float(price) < 0):
        raise CardError('actual fill price required')
    if filled and float(price) == 0 and not (label == 'EXIT_FILLED' and 'EXPIRATION_ZERO_VALUE' in (reasons or [])):
        raise CardError('a zero price is only an explicit expiration/write-off record')
    lines = []
    kind = 'ENTRY' if entry else 'EXIT'
    status = 'FILLED' if filled else 'PROPOSED · awaiting fill'
    title = f"{'GREEN' if entry else 'RED'} {kind} · {status}"
    lines.append(f"{ctext} · {exp}")
    if filled:
        ret = ''
        if label == 'EXIT_FILLED':
            if not avg_entry or float(avg_entry) <= 0:
                raise CardError('EXIT_FILLED requires the weighted average actual entry fill')
            r = (float(price) / float(avg_entry) - 1) * 100
            ret = f" · Option return {r:+.1f}% (fills)"
        lines.append(f"Actual fill ${float(price):.2f} · Contracts {int(qty)}{ret}")
    else:
        lines.append(f"Indicative quote ${float(price):.2f} · Planned contracts {int(qty)}" if price is not None
                     else f"Planned contracts {int(qty)}")
    if partial_remaining:
        lines.append(f"Partial execution: {int(qty)} executed, {int(partial_remaining)} still open")
    if not entry:
        lines.append('Reason: ' + _clean('reason', reason_text(reasons, campaign['direction']), 160))
    t = cal.ny_dt(ts)
    lines.append(f"Campaign {cid[:8]}... · {t.strftime('%H:%M')} ET")
    embed = {'title': title, 'description': '\n'.join(lines), 'color': GREEN if entry else RED,
             'footer': {'text': FOOTER}, 'timestamp': t.isoformat()}
    return {'embeds': [embed], 'allowed_mentions': {'parse': []}}


def text(card: dict) -> str:
    e = card['embeds'][0]
    return '\n'.join([e['title'], e['description'], e['footer']['text']])
