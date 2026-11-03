"""§15 Compact Discord cards: ENTRY_PROPOSED / ENTRY_FILLED / EXIT_PROPOSED / EXIT_FILLED.

Only FILLED cards are member-facing (CF_PUBLISH_PROPOSED, default off): a proposal is journaled and, if it
never fills, nothing is posted. Wording is neutral and descriptive ("Model opened a simulated position"), never
an instruction: no "Planned contracts", no "Exit plan", no trade-call titles (Mag 7 brief, items 3 and 7).

A filled card shows the "Simulated fill" and "Contracts". The EXIT_FILLED return (exit fill / weighted average
actual entry fill - 1, signed, one decimal, fees excluded) is shown only with CF_CARD_SHOW_RETURN, labelled as a
simulated paper result; otherwise it stays in the journal. The campaign id is internal (CF_CARD_SHOW_CAMPAIGN_ID).
A campaign held past a session close is labelled "Carried overnight". Scores, OI zones, percentiles, windows,
gates and diagnostics stay in the journal, never on the card.
Untrusted identity/reason fields are validated: no line breaks, '@', backticks, '<' or '>'; length limits.
"""
from datetime import date

from campaign_flow import calendar_ny as cal
from campaign_flow import settings as S

GREEN, RED = 0x2ECC71, 0xE74C3C
FOOTER = 'Education only · Paper simulation · Options can lose 100% · Not investment advice.'
LABELS = ('ENTRY_PROPOSED', 'ENTRY_FILLED', 'EXIT_PROPOSED', 'EXIT_FILLED')
_BAD = ('\n', '\r', '@', '`', '<', '>')

REASON_TEXT = {
    'FAVORABLE_REGULAR_SESSION_OPEN_GAP_SELL_ALL': 'Favorable open gap',
    'ADVERSE_OPEN_GAP_CARRY_REVIEW': 'Open review after overnight carry: adverse gap',
    'OVERNIGHT_OPEN_REVIEW_NO_CONTINUATION': 'Open review after overnight carry: no continuation',
    'PLANNED_OR_EXPIRY_EXIT_DEADLINE': 'Planned/expiry deadline',
    'PRECOMMITTED_UNDERLYING_INVALIDATION': 'Precommitted underlying invalidation',
    'PRECOMMITTED_PREMIUM_RISK_LIMIT': 'Precommitted premium risk limit',
    'TRAILING_STOP_FROM_PEAK': 'Trailing stop from peak',
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
            out.append('Confirmed opposite put flow' if direction == 'BULLISH' else 'Confirmed opposite call flow')
        elif REASON_TEXT.get(r):
            out.append(REASON_TEXT[r])
    return '; '.join(out) or 'Recorded exit'


def carried_from(campaign: dict, ts: float):
    """The entry session (a date) when this campaign has been held past at least one session close."""
    first = campaign.get('first_entry_ts')
    if first is None:
        return None
    d0 = cal.ny_day(first)
    return d0 if cal.ny_day(ts) > d0 else None


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
    if not filled:
        title = 'Model proposed a simulated ' + ('position (not filled)' if entry else 'close (not filled)')
    elif entry:
        title = 'Model opened a simulated position'
    else:
        title = 'Model reduced a simulated position' if partial_remaining else 'Model closed a simulated position'
    lines = [f"{ctext} · {exp}"]
    if filled:
        ret = ''
        if label == 'EXIT_FILLED':
            if not avg_entry or float(avg_entry) <= 0:
                raise CardError('EXIT_FILLED requires the weighted average actual entry fill')
            if S.CARD_SHOW_RETURN:
                r = (float(price) / float(avg_entry) - 1) * 100
                ret = f" · Simulated option return {r:+.1f}% (paper fills, fees excluded)"
        lines.append(f"Simulated fill ${float(price):.2f} · Contracts {int(qty)}{ret}")
    else:
        lines.append(f"Indicative quote ${float(price):.2f} · Contracts {int(qty)}" if price is not None
                     else f"Contracts {int(qty)}")
    if partial_remaining:
        lines.append(f"Partial: {int(qty)} closed, {int(partial_remaining)} still held")
    if entry and campaign.get('horizon') == 'OVERNIGHT':
        lines.append('Overnight position (may be carried past the close; gap risk)')
    if not entry:
        d0 = carried_from(campaign, ts)
        if d0:
            lines.append(f"Carried overnight from {d0.strftime('%a %b')} {d0.day}")
        lines.append('Reason: ' + _clean('reason', reason_text(reasons, campaign['direction']), 160))
    t = cal.ny_dt(ts)
    stamp = f"{t.strftime('%H:%M')} ET"
    if S.CARD_SHOW_CAMPAIGN_ID:
        stamp = f"Campaign {cid[:8]}... · {stamp}"
    lines.append(stamp)
    embed = {'title': title, 'description': '\n'.join(lines), 'color': GREEN if entry else RED,
             'footer': {'text': FOOTER}, 'timestamp': t.isoformat()}
    return {'embeds': [embed], 'allowed_mentions': {'parse': []}}


def text(card: dict) -> str:
    e = card['embeds'][0]
    return '\n'.join([e['title'], e['description'], e['footer']['text']])
