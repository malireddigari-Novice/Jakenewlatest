"""
Private followed trades (flow handoff §9) — the opt-in watch list and the ONLY source of BUY/SELL fill
cards. The engine has no authenticated Discord bot, so /follow and /unfollow live here as a local CLI:
ownership is the OS user running it (or --owner), and nothing private is ever posted to a public channel.

  python follow.py add --legs "+1 NVDA261023C00212500" [--legs "-1 NVDA261023C00215000"] [--structure note]
                       [--stop 2.10] [--target 4.00] [--catalyst "NVDA earnings 11-19"]
  python follow.py fill WATCH_ID --action BUY --contract NVDA261023C00212500 --qty 1 --price 5.35 --verified
  python follow.py list
  python follow.py remove WATCH_ID

User fills and user risk rules are stored apart from market observations. Market prints on a watched
contract raise a private amber "watched activity" card and are never assigned to the user's account.
P/L is computed only when the watch has signed quantities AND a recorded fill.
"""
import argparse
import getpass
import hashlib
import json
import sys
from datetime import datetime

import notify
from tape import cards, events, settings, taxonomy
from tape.store import Store


def _legs(specs) -> list:
    out = []
    for s in specs:
        qty, occ = s.split()
        p = events.parse_occ(occ)
        if not p:
            raise SystemExit(f"bad OCC symbol: {occ}")
        out.append({'occ': occ, 'qty': int(qty), 'expiry': p[1].isoformat(), 'right': p[2], 'strike': p[3]})
    return out


def _owned(store, wid, owner):
    r = store.q("SELECT watch_id, owner, structure, legs, fill, rules FROM watches WHERE watch_id=?", (wid,))
    if not r:
        raise SystemExit(f"no watch {wid}")
    if r[0][1] != owner:
        raise SystemExit(f"watch {wid} belongs to another owner")
    return r[0]


def pnl(legs, fill, marks: dict):
    """Per-watch P/L — only with signed quantities AND a recorded fill price per leg; else None."""
    if not fill or not legs or any(l.get('qty') in (None, 0) for l in legs):
        return None
    prices = fill.get('leg_prices') or {}
    if any(l['occ'] not in prices or l['occ'] not in marks for l in legs):
        return None
    return round(sum((marks[l['occ']] - prices[l['occ']]) * l['qty'] * 100 for l in legs), 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=('add', 'fill', 'list', 'remove'))
    ap.add_argument('watch_id', nargs='?')
    ap.add_argument('--owner', default=getpass.getuser())
    ap.add_argument('--legs', action='append', default=[])
    ap.add_argument('--structure')
    ap.add_argument('--stop', type=float)
    ap.add_argument('--target', type=float)
    ap.add_argument('--catalyst')
    ap.add_argument('--action', choices=('BUY', 'SELL'))
    ap.add_argument('--contract')
    ap.add_argument('--qty', type=int)
    ap.add_argument('--price', type=float)
    ap.add_argument('--time')
    ap.add_argument('--verified', action='store_true')
    a = ap.parse_args()
    store = Store()

    if a.cmd == 'add':
        legs = _legs(a.legs)
        if not legs:
            raise SystemExit('--legs is required')
        geo = taxonomy.classify_known([{**l, 'expiry': l['expiry']} for l in legs])
        wid = hashlib.sha256(f"{a.owner}|{json.dumps(legs)}|{datetime.now().isoformat()}".encode()).hexdigest()[:10]
        rules = {k: v for k, v in (('stop', a.stop), ('target', a.target), ('catalyst', a.catalyst)) if v is not None}
        store.x("INSERT INTO watches VALUES (?,?,?,?,?,?,?,?,?,?)",
                (wid, a.owner, a.structure or geo['tag'], json.dumps(legs), events.iso_to_ns(
                    datetime.now(events.NY).isoformat()), None, 0, json.dumps(rules), 1, datetime.now().isoformat()))
        store.flush()
        print(f"watch {wid} ({a.structure or geo['tag']}) — private, owner {a.owner}")
    elif a.cmd == 'list':
        for wid, owner, st, legs, fill, ver, rules, active in store.q(
                "SELECT watch_id, owner, structure, legs, fill, fill_verified, rules, active FROM watches WHERE owner=?",
                (a.owner,)):
            print(wid, 'ACTIVE' if active else 'closed', st, legs, 'fill:' + (fill or '-'),
                  'verified' if ver else '', rules)
    elif a.cmd == 'remove':
        _owned(store, a.watch_id, a.owner)
        store.x("UPDATE watches SET active=0 WHERE watch_id=?", (a.watch_id,))
        store.flush()
        print(f"watch {a.watch_id} closed")
    elif a.cmd == 'fill':
        row = _owned(store, a.watch_id, a.owner)
        p = events.parse_occ(a.contract or '')
        if not (p and a.action and a.qty and a.price is not None):
            raise SystemExit('--action, --contract, --qty, --price are required')
        fill = {'action': a.action, 'contract': a.contract, 'qty': a.qty, 'price': a.price,
                'expiry': p[1].isoformat(), 'time': a.time or datetime.now(events.NY).isoformat(),
                'verified': bool(a.verified)}
        prev = json.loads(row[4]) if row[4] else {}
        fills = prev.get('fills', []) + [fill]
        leg_prices = dict(prev.get('leg_prices') or {})
        if a.action == 'BUY':
            leg_prices[a.contract] = a.price
        store.x("UPDATE watches SET fill=?, fill_verified=? WHERE watch_id=?",
                (json.dumps({'fills': fills, 'leg_prices': leg_prices}), int(a.verified), a.watch_id))
        store.flush()
        if a.verified and settings.PRIVATE_WEBHOOK:
            notify.register_webhook('tape:private', settings.PRIVATE_WEBHOOK)
            c = cards.fill_card({'watch_id': a.watch_id}, fill)
            notify.enqueue(c['payload'], signal_id=c['signal_id'], alias='tape:private')
            notify.flush()
        print(f"fill recorded on {a.watch_id}{' (verified — private fill card queued)' if a.verified else ''}")
    store.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
