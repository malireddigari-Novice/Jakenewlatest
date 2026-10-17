"""Normalised raw events (flow handoff §3). Every event keeps the provider payload, a checksum, the
parser + condition-map versions and the NY session. Contract identity is the full OCC symbol."""
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime

import pytz

from tape import conditions, settings

NY = pytz.timezone('America/New_York')


def parse_occ(occ: str):
    """OCC symbol → (root, expiry, right 'C'/'P', strike). None if malformed."""
    try:
        tail, root = occ[-15:], occ[:-15]
        exp = date(2000 + int(tail[0:2]), int(tail[2:4]), int(tail[4:6]))
        right, strike = tail[6], int(tail[7:]) / 1000.0
        if right not in ('C', 'P') or not root:
            return None
        return root, exp, right, strike
    except Exception:
        return None


def ny_dt(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9, tz=pytz.utc).astimezone(NY)


def session_of(ns: int) -> str:
    return ny_dt(ns).date().isoformat()


def checksum(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:20]


def iso_to_ns(s: str) -> int:
    """RFC3339 with up to nanosecond precision → epoch ns (datetime keeps only µs, so parse the fraction)."""
    s = s.replace('Z', '+00:00')
    frac = ''
    if '.' in s:
        main, rest = s.split('.', 1)
        i = 0
        while i < len(rest) and rest[i].isdigit():
            i += 1
        frac, tz = rest[:i], rest[i:]
    else:
        main, tz = s[:19], s[19:]
    dt = datetime.fromisoformat(main + (tz or '+00:00'))
    return int(dt.timestamp()) * 1_000_000_000 + int((frac + '000000000')[:9])


def ns_to_iso(ns: int) -> str:
    return datetime.fromtimestamp(ns // 1_000_000_000, tz=pytz.utc).strftime('%Y-%m-%dT%H:%M:%S') + \
        f".{ns % 1_000_000_000:09d}Z"


@dataclass
class Trade:
    occ: str
    price: float
    size: int
    exchange: str
    cond: str
    event_ns: int
    recv_ns: int
    source: str = 'stream'                 # stream | backfill
    payload: dict = field(default_factory=dict)

    @property
    def key(self) -> str:                  # stream/backfill dedupe identity (the provider has no trade id)
        return f"{self.occ}|{self.event_ns}|{self.exchange}|{self.price}|{self.size}|{self.cond}"

    @property
    def slot(self) -> str:                 # same instant + venue + condition: another price/size = conflict
        return f"{self.occ}|{self.event_ns}|{self.exchange}|{self.cond}"

    @property
    def tags(self):
        return conditions.tags(self.cond)


@dataclass
class Quote:
    occ: str
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    event_ns: int
    recv_ns: int
    bid_x: str = ''
    ask_x: str = ''
    cond: str = ''


@dataclass
class Spot:
    symbol: str
    price: float
    event_ns: int
    recv_ns: int


def trade_from_stream(m: dict, recv_ns: int) -> Trade:
    return Trade(occ=m['S'], price=float(m['p']), size=int(m['s']), exchange=str(m.get('x') or ''),
                 cond=str(m.get('c') or ''), event_ns=int(m['t']), recv_ns=recv_ns, source='stream',
                 payload=dict(m))


def trade_from_rest(occ: str, r: dict, recv_ns: int) -> Trade:
    return Trade(occ=occ, price=float(r['p']), size=int(r['s']), exchange=str(r.get('x') or ''),
                 cond=str(r.get('c') or ''), event_ns=iso_to_ns(r['t']), recv_ns=recv_ns, source='backfill',
                 payload={'S': occ, **r})


def quote_from_stream(m: dict, recv_ns: int) -> Quote:
    return Quote(occ=m['S'], bid=float(m.get('bp') or 0), ask=float(m.get('ap') or 0),
                 bid_size=int(m.get('bs') or 0), ask_size=int(m.get('as') or 0), event_ns=int(m['t']),
                 recv_ns=recv_ns, bid_x=str(m.get('bx') or ''), ask_x=str(m.get('ax') or ''),
                 cond=str(m.get('c') or ''))


def spot_from_sip(m: dict, recv_ns: int) -> Spot:
    t = m['t']
    return Spot(symbol=m['S'], price=float(m['p']),
                event_ns=iso_to_ns(t) if isinstance(t, str) else int(t), recv_ns=recv_ns)


def provenance(event_ns: int) -> dict:
    return {'parser_version': settings.PARSER_VERSION, 'cond_map_version': conditions.COND_MAP_VERSION,
            'rule_version': settings.RULE_VERSION, 'session': session_of(event_ns)}
