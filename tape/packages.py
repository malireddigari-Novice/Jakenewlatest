"""
Event-time package CANDIDATES on the public tape (flow handoff §5).

Real complex orders fill their legs in an EXACT small-integer ratio, so a candidate's GCD-reduced ratio
must have every part ≤ PKG_MAX_RATIO_PART; a busy one-second window whose per-series totals reduce to
668:667 is coincident unrelated flow, not a package (seen on real NVDA 2026-10-16 data).

Per underlying, prints are clustered in a bounded event-time window (PKG_WINDOW_MS from the first print,
≤ PKG_MAX_PRINTS). Split prints are aggregated per series; a package candidate needs 2–4 series of
≥ PKG_MIN_SERIES contracts each. Quantities are reduced by their GCD (4,000 puts vs 7,000 calls = 4:7).
A window with more qualifying series is segmented by venue + tight timing; if it still cannot be
separated it ABSTAINS (two unrelated orders must not be conflated). One print is assigned to at most one
package. Association is graded descriptively (no probability):

  A_COMPLEX_COMMON_VENUE_TIGHT  every leg complex-tagged, a common venue, span ≤ PKG_TIGHT_MS
  B_COMMON_VENUE_TIGHT          common venue and span ≤ PKG_TIGHT_MS
  C_NEAR_TIME_COMPLEX           every leg complex-tagged, within the window
  D_TIME_SIZE_ONLY              time and size only

net side, net cashflow, customer effect and any stock leg stay UNKNOWN. An arithmetic sum of leg
cashflows is computed only when every leg has a known taker side and expiry, and is CONDITIONAL on a
verified linkage — it is never an executed net debit/credit.
"""
import hashlib
from collections import defaultdict

from tape import settings, taxonomy
from tape.side import BUY, SELL

RULE = 'tape-pkg-v1'


def _leg_side(side_qty: dict, qty: int) -> str:
    for s in (BUY, SELL):
        if qty and side_qty.get(s, 0) / qty >= 0.60:
            return s
    return 'UNKNOWN'


def _legs(prints) -> list:
    by = defaultdict(list)
    for p in prints:
        by[p['occ']].append(p)
    legs = []
    for occ, ps in by.items():
        qty = sum(p['size'] for p in ps)
        sq = defaultdict(int)
        for p in ps:
            sq[p['side']] += p['size']
        legs.append({
            'occ': occ, 'expiry': ps[0]['expiry'], 'right': ps[0]['right'], 'strike': ps[0]['strike'],
            'qty': qty, 'vwap': round(sum(p['price'] * p['size'] for p in ps) / qty, 4) if qty else None,
            'venues': sorted({p['exchange'] for p in ps}), 'conds': sorted({p['cond'] for p in ps}),
            'print_keys': [p['key'] for p in ps], 'prints': len(ps),
            'start_ns': min(p['event_ns'] for p in ps), 'end_ns': max(p['event_ns'] for p in ps),
            'taker_side': _leg_side(sq, qty), 'complex_all': all('COMPLEX' in p['tags'] for p in ps),
            'multiplier': ps[0].get('multiplier') or 100,
        })
    return sorted(legs, key=lambda l: (str(l['expiry']), l['right'], l['strike']))


def _association(legs) -> str:
    span_ms = (max(l['end_ns'] for l in legs) - min(l['start_ns'] for l in legs)) / 1e6
    common = set(legs[0]['venues'])
    for l in legs[1:]:
        common &= set(l['venues'])
    tight = span_ms <= settings.PKG_TIGHT_MS
    complex_all = all(l['complex_all'] for l in legs)
    if complex_all and common and tight:
        return 'A_COMPLEX_COMMON_VENUE_TIGHT'
    if common and tight:
        return 'B_COMMON_VENUE_TIGHT'
    if complex_all:
        return 'C_NEAR_TIME_COMPLEX'
    return 'D_TIME_SIZE_ONLY'


def _side_text(legs, geometry) -> str:
    sides = {l['taker_side'] for l in legs}
    if 'UNKNOWN' in sides:
        return f"{geometry}: leg sides UNKNOWN — geometry only; net side, debit/credit and initiator unresolved"
    if len(sides) == 1:
        return "spread candidate; debit/credit and initiator unresolved"
    return (f"{geometry}: legs printed on opposite quote sides — IF linked, a conditional reading only; "
            f"debit/credit unverified without a linked fill")


def _cashflow(legs):
    """Σ (+ taker buy pays / − taker sell receives) × vwap × qty × multiplier — CONDITIONAL arithmetic."""
    if any(l['taker_side'] == 'UNKNOWN' or l['expiry'] is None for l in legs):
        return None
    if len({l['taker_side'] for l in legs}) == 1:
        return None                    # all legs on one side: no spread arithmetic is meaningful
    tot = 0.0
    for l in legs:
        sign = 1 if l['taker_side'] == BUY else -1
        tot += sign * l['vwap'] * l['qty'] * l['multiplier']
    return round(tot, 2)


def build(underlying, session, prints) -> dict | None:
    legs = [l for l in _legs(prints) if l['qty'] >= settings.PKG_MIN_SERIES]
    if not 2 <= len(legs) <= 4:
        return None
    keys = sorted(k for l in legs for k in l['print_keys'])
    ratio = taxonomy.reduced_ratio(l['qty'] for l in legs)
    if max(int(x) for x in ratio.split(':')) > settings.PKG_MAX_RATIO_PART:
        return None                    # not an exact small-integer ratio → coincident unrelated flow
    geom = taxonomy.geometry(legs)
    return {
        'pkg_id': hashlib.sha256((underlying + '|' + '|'.join(keys)).encode()).hexdigest()[:16],
        'underlying': underlying, 'session': session,
        'start_ns': min(l['start_ns'] for l in legs), 'end_ns': max(l['end_ns'] for l in legs),
        'legs': legs, 'ratio': ratio, 'geometry': geom,
        'association': _association(legs), 'side_text': _side_text(legs, geom),
        'conditional_cashflow': _cashflow(legs), 'net_side': 'UNKNOWN', 'net_cashflow': 'UNKNOWN',
        'customer_effect': 'UNKNOWN', 'stock_leg': 'UNKNOWN', 'competing': [], 'status': 'CANDIDATE',
        'rule_version': RULE,
    }


def _segment(prints) -> list:
    """Split one crowded window into venue-and-tight-time groups."""
    groups = []
    for p in sorted(prints, key=lambda p: p['event_ns']):
        for g in groups:
            if p['exchange'] == g[-1]['exchange'] and p['event_ns'] - g[0]['event_ns'] <= settings.PKG_TIGHT_MS * 1e6:
                g.append(p)
                break
        else:
            groups.append([p])
    return groups


def group_window(underlying, session, prints) -> list:
    """All package records for one closed window: CANDIDATEs and ABSTAIN records (never silent)."""
    qualifying = [l for l in _legs(prints) if l['qty'] >= settings.PKG_MIN_SERIES]
    if len(qualifying) < 2:
        return []
    if len(qualifying) <= 4:
        pkg = build(underlying, session, prints)
        if pkg and len(qualifying) >= 3:
            # every 2-series subset is a possible competing grouping — preserved, not chosen.
            occs = [l['occ'] for l in pkg['legs']]
            pkg['competing'] = [[a, b] for i, a in enumerate(occs) for b in occs[i + 1:]]
        return [pkg] if pkg else []
    out, used = [], set()
    for g in _segment(prints):
        pkg = build(underlying, session, g)
        if pkg and not (used & set(k for l in pkg['legs'] for k in l['print_keys'])):
            used |= {k for l in pkg['legs'] for k in l['print_keys']}
            out.append(pkg)
    if not out:
        keys = sorted(p['key'] for p in prints)
        out.append({'pkg_id': hashlib.sha256(('ABSTAIN|' + '|'.join(keys)).encode()).hexdigest()[:16],
                    'underlying': underlying, 'session': session,
                    'start_ns': min(p['event_ns'] for p in prints), 'end_ns': max(p['event_ns'] for p in prints),
                    'legs': qualifying, 'ratio': None, 'geometry': None, 'association': None,
                    'side_text': f'{len(qualifying)} qualifying series in one window — unrelated orders may be '
                                 f'conflated; ABSTAINED', 'conditional_cashflow': None, 'net_side': 'UNKNOWN',
                    'net_cashflow': 'UNKNOWN', 'customer_effect': 'UNKNOWN', 'stock_leg': 'UNKNOWN',
                    'competing': [], 'status': 'ABSTAIN_CONFLATED', 'rule_version': RULE})
    return out


class Grouper:
    """Streaming event-time windows per underlying. `add()` returns windows closed by the watermark."""

    def __init__(self) -> None:
        self._open = defaultdict(list)       # underlying -> [print dicts] of the current window
        self._closed_until = defaultdict(int)

    def add(self, p: dict, watermark_ns: int) -> list:
        u = p['underlying']
        if p['event_ns'] < self._closed_until[u]:
            p['late_for_package'] = True     # its window already closed — never regrouped
            return self.flush(watermark_ns)
        win = self._open[u]
        if win and (p['event_ns'] - win[0]['event_ns'] > settings.PKG_WINDOW_MS * 1e6
                    or len(win) >= settings.PKG_MAX_PRINTS):
            closed = self._close(u)
            self._open[u].append(p)
            return closed + self.flush(watermark_ns)
        win.append(p)
        return self.flush(watermark_ns)

    def _close(self, u) -> list:
        win = self._open[u]
        self._open[u] = []
        if not win:
            return []
        self._closed_until[u] = win[0]['event_ns'] + int(settings.PKG_WINDOW_MS * 1e6)
        return [(u, win[0]['session'], win)]

    def flush(self, watermark_ns: int, force: bool = False) -> list:
        """Close every window whose end + lateness slack is behind the watermark (or all, when forced)."""
        out = []
        slack = (settings.PKG_WINDOW_MS + settings.PKG_LATENESS_MS) * 1e6
        for u in list(self._open):
            win = self._open[u]
            if win and (force or watermark_ns - win[0]['event_ns'] > slack):
                out.extend(self._close(u))
        return out
