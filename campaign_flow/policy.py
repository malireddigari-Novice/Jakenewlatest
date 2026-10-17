"""§8/§11-14 Campaign router: entry proposals, management, exits, fills and lifecycle.

Four separate decisions: observe flow (shock/board), qualify the buy hypothesis (value band + clusters),
propose an entry (this module) and manage each FILLED campaign (this module). A score never authorizes an
entry; a proposal is never an execution; a usable quote never establishes a fill.

Campaign states: PROPOSED (reserved, nothing held) → ACTIVE (held > 0) → ENTRY_PENDING (held 0 but an entry
remainder is outstanding) → CLOSED (held 0, nothing outstanding) | CANCELLED (unfilled proposal cancelled).

Every operation takes a stable event_id and runs once (journal.once); repeats return the recorded result.
"""
import math

from campaign_flow import calendar_ny as cal
from campaign_flow import clusters
from campaign_flow import contracts
from campaign_flow import settings as S
from campaign_flow.model import direction_right, opposite, stable_id

OPEN_STATES = ('PROPOSED', 'ACTIVE', 'ENTRY_PENDING')


def quote_usable_for_exit(q: dict, now_ts: float) -> bool:
    if not q or q.get('ts') is None or float(q['ts']) > now_ts:
        return False
    return (now_ts - float(q['ts']) <= S.EXIT_QUOTE_MAX_AGE_S and (q.get('bid') or 0) > 0
            and (q.get('bid_size') or 0) >= 1)


class Router:

    def __init__(self, journal) -> None:
        self.j = journal

    # ── capacity ──────────────────────────────────────────────────────────────
    def used_capacity(self) -> float:
        used = 0.0
        for c in self.j.campaigns(OPEN_STATES):
            m = c['contract'].get('multiplier') or 100
            used += c['outstanding_entry_qty'] * c['proposal_ask'] * m
            used += c['held_qty'] * (c['avg_entry'] or c['proposal_ask']) * m
        return round(used, 2)

    # ── §8 entry ──────────────────────────────────────────────────────────────
    def propose(self, cand: dict) -> dict:
        """cand: event_id, ts, ticker, direction, snapshot, items, choices, route_score, attention_score,
        stock_price, upstream_vetoes, evidence_times, horizon, planned_end, qty, source_campaign_id."""
        return self.j.once(cand['event_id'], 'CANDIDATE', cand['ts'], lambda: self._propose(cand))

    def _propose(self, cand: dict) -> dict:
        ts, t, direction = float(cand['ts']), cand['ticker'], cand['direction']
        session = cal.ny_day(ts).isoformat()
        reasons, logs = [], []
        if any(float(x) > ts for x in (cand.get('evidence_times') or [])):
            reasons.append('FUTURE_EVIDENCE')
        reasons += [f'UPSTREAM_VETO:{v}' for v in cand.get('upstream_vetoes') or []]
        a = clusters.assess(cand['snapshot'], cand['items'], ts)
        want = clusters.BULL if direction == 'BULLISH' else clusters.BEAR
        if a['state'] != want:
            reasons += a['reasons'] or ['NO_VERIFIED_ONE_SIDED_CONTROL']
            if 'NO_VERIFIED_ONE_SIDED_CONTROL' not in reasons:
                reasons.append('NO_VERIFIED_ONE_SIDED_CONTROL')
        horizon = cand.get('horizon') or S.DEFAULT_HORIZON
        if horizon not in ('INTRADAY', 'OVERNIGHT', 'SWING'):
            reasons.append('INVALID_HORIZON')
            horizon = 'INTRADAY'
        planned_end = float(cand.get('planned_end') or cal.planned_end(horizon, ts))
        if planned_end <= ts:
            reasons.append('PLANNED_END_NOT_IN_FUTURE')
        sel = contracts.select(cand.get('choices'), direction, horizon, planned_end, ts)
        best = sel['best']
        if best is None:
            reasons.append('NO_SUITABLE_CONTRACT')
        src = cand.get('source_campaign_id')
        if src:
            s = self.j.campaign(src)
            if not s or s['state'] != 'CLOSED':
                reasons.append('ROTATION_SOURCE_NOT_FULLY_CLOSED')
            elif s.get('closed_rotation_direction') != direction:
                reasons.append('ROTATION_DIRECTION_MISMATCH')
        elif any(c['ticker'] == t and c['direction'] == opposite(direction) for c in self.j.campaigns(OPEN_STATES)):
            # integration decision: while an opposite campaign is open, the only way to the other side is the
            # rotation path (full exit confirmed first, §13) — an ordinary proposal cannot bypass it.
            reasons.append('OPPOSITE_CAMPAIGN_OPEN_ROTATION_PATH_ONLY')
        if self.j.proposals(t, session) >= S.MAX_PROPOSALS_PER_TICKER_DAY:
            reasons.append('DAILY_ENTRY_PROPOSAL_CAP')
        qty = 0
        if best is not None:
            ask = float(best['quote']['ask'])
            m = best['contract'].get('multiplier') or 100
            room = S.BUDGET - self.used_capacity()
            qty = int(cand.get('qty') or min(S.MAX_QTY, math.floor(room / (ask * m)) if ask > 0 else 0))
            if qty <= 0:
                reasons.append('NONPOSITIVE_PLANNED_QUANTITY')
            elif qty * ask * m > room + 1e-9:
                reasons.append('INSUFFICIENT_RESERVED_PREMIUM_CAPACITY')
        rs = cand.get('route_score')
        if rs is not None and rs < S.OLD_ROUTE_BOUNDARY:
            logs.append('VERIFIED_CLUSTER_BELOW_SCORE_BOUNDARY')
        record = {'event_id': cand['event_id'], 'ts': ts, 'ticker': t, 'direction': direction,
                  'state': a['state'], 'assessment': _brief(a), 'contract_journal': sel['journal'],
                  'ranking': sel['ranking'], 'route_score': rs, 'attention_score': cand.get('attention_score'),
                  'old_boundary': S.OLD_ROUTE_BOUNDARY, 'logs': logs}
        if reasons:
            record.update(decision='WATCH', reasons=sorted(set(reasons), key=reasons.index))
            self.j.log(ts, 'CANDIDATE_WATCH', record, ticker=t, ref=cand['event_id'])
            return record
        m = best['contract'].get('multiplier') or 100
        stock = cand.get('stock_price')
        level = None
        if S.UNDERLYING_INVALIDATION_PCT and stock:
            level = stock * (1 - S.UNDERLYING_INVALIDATION_PCT) if direction == 'BULLISH' \
                else stock * (1 + S.UNDERLYING_INVALIDATION_PCT)
        cid = stable_id('campaign', cand['event_id'])
        camp = {'campaign_id': cid, 'ticker': t, 'direction': direction, 'right': direction_right(direction),
                'contract': best['contract'], 'horizon': horizon, 'planned_end': planned_end,
                'risk_plan': {'underlying_level': level, 'premium_loss_limit': S.PREMIUM_LOSS_LIMIT,
                              'precommitted_ts': ts},
                'state': 'PROPOSED', 'session': session, 'proposal_ts': ts, 'proposal_event': cand['event_id'],
                'proposal_ask': float(best['quote']['ask']), 'proposal_quote': best['quote'],
                'planned_qty': qty, 'outstanding_entry_qty': qty, 'held_qty': 0, 'entry_filled_qty': 0,
                'entry_cost': 0.0, 'avg_entry': None, 'first_entry_ts': None, 'exit_filled_qty': 0,
                'realized': 0.0, 'exit_pending': None, 'source_campaign_id': src, 'entry_spot': stock,
                'clusters': a['clusters'], 'cluster_ids': cand.get('cluster_ids') or [], 'marks': {}, 'reservation': round(qty * best['quote']['ask'] * m, 2)}
        self.j.put_campaign(camp)
        self.j.bump_proposals(t, session)
        record.update(decision='PROPOSE', campaign_id=cid, contract=best['contract'], qty=qty,
                      indicative_ask=camp['proposal_ask'], planned_end=planned_end, horizon=horizon)
        self.j.log(ts, 'PROPOSAL', record, ticker=t, ref=cid)
        return record

    # ── §14 fills and cancellations ─────────────────────────────────────────────
    def entry_fill(self, f: dict) -> dict:
        return self.j.once(f['event_id'], 'ENTRY_FILL', f['ts'], lambda: self._entry_fill(f))

    def _entry_fill(self, f):
        c = self.j.campaign(f['campaign_id'])
        f = {**f, 'kind': 'ENTRY'}
        why = []
        if not c:
            why.append('UNKNOWN_CAMPAIGN')
        else:
            if c['state'] not in OPEN_STATES:
                why.append(f'CAMPAIGN_{c["state"]}')
            if not (0 < int(f['qty']) <= c['outstanding_entry_qty']):
                why.append('QTY_EXCEEDS_OUTSTANDING')
            if not (float(f['price']) > 0):
                why.append('INVALID_PRICE')
            ts = float(f['ts'])
            if ts < c['proposal_ts'] or cal.ny_day(ts).isoformat() != c['session'] or ts >= c['planned_end']:
                why.append('OUTSIDE_PROPOSAL_WINDOW')
        if why:
            self.j.put_fill(f, accepted=False)
            self.j.log(f['ts'], 'RECONCILIATION_EXCEPTION', {'fill': f, 'reasons': why},
                       ticker=(c or {}).get('ticker'), ref=f['campaign_id'])
            return {'accepted': False, 'reasons': why}
        q, px = int(f['qty']), float(f['price'])
        c['held_qty'] += q
        c['outstanding_entry_qty'] -= q
        c['entry_filled_qty'] += q
        c['entry_cost'] += q * px
        c['avg_entry'] = c['entry_cost'] / c['entry_filled_qty']
        c['first_entry_ts'] = min(c['first_entry_ts'] or float(f['ts']), float(f['ts']))
        c['state'] = 'ACTIVE'
        notes = ['FILL_ABOVE_PROPOSAL_ASK'] if px > c['proposal_ask'] else []
        self.j.put_campaign(c)
        self.j.put_fill(f, accepted=True)
        self.j.log(f['ts'], 'ENTRY_FILL', {'fill': f, 'notes': notes, 'held': c['held_qty'],
                                          'outstanding': c['outstanding_entry_qty'], 'avg_entry': c['avg_entry']},
                   ticker=c['ticker'], ref=c['campaign_id'])
        return {'accepted': True, 'state': c['state'], 'held': c['held_qty'],
                'outstanding': c['outstanding_entry_qty'], 'avg_entry': c['avg_entry'], 'notes': notes}

    def exit_fill(self, f: dict) -> dict:
        return self.j.once(f['event_id'], 'EXIT_FILL', f['ts'], lambda: self._exit_fill(f))

    def _exit_fill(self, f):
        c = self.j.campaign(f['campaign_id'])
        f = {**f, 'kind': 'EXIT'}
        why = []
        if not c:
            why.append('UNKNOWN_CAMPAIGN')
        else:
            if not (0 < int(f['qty']) <= c['held_qty']):
                why.append('QTY_EXCEEDS_HELD')
            if c['first_entry_ts'] is None or float(f['ts']) < c['first_entry_ts']:
                why.append('EXIT_PREDATES_ENTRY')
            if float(f['price']) < 0 or (float(f['price']) == 0 and not f.get('zero_value_record')):
                why.append('INVALID_PRICE')
        if why:
            self.j.put_fill(f, accepted=False)
            self.j.log(f['ts'], 'RECONCILIATION_EXCEPTION', {'fill': f, 'reasons': why},
                       ticker=(c or {}).get('ticker'), ref=f['campaign_id'])
            return {'accepted': False, 'reasons': why}
        q, px = int(f['qty']), float(f['price'])
        m = c['contract'].get('multiplier') or 100
        c['held_qty'] -= q
        c['exit_filled_qty'] += q
        c['realized'] = round(c['realized'] + (px - c['avg_entry']) * m * q, 2)
        if c['held_qty'] == 0:
            if c['outstanding_entry_qty'] > 0:
                c['state'] = 'ENTRY_PENDING'
            else:
                self._close(c, float(f['ts']))
        self.j.put_campaign(c)
        self.j.put_fill(f, accepted=True)
        self.j.log(f['ts'], 'EXIT_FILL', {'fill': f, 'held': c['held_qty'], 'state': c['state'],
                                         'realized': c['realized']}, ticker=c['ticker'], ref=c['campaign_id'])
        return {'accepted': True, 'state': c['state'], 'held': c['held_qty'], 'realized': c['realized']}

    def _close(self, c, ts):
        c['state'] = 'CLOSED'
        c['closed_ts'] = ts
        ep = c.get('exit_pending') or {}
        c['closed_rotation_direction'] = ep.get('rotation_direction')

    def cancel_confirmed(self, ev: dict) -> dict:
        """Broker confirmed the unfilled entry remainder is cancelled: release its reservation."""
        def run():
            c = self.j.campaign(ev['campaign_id'])
            if not c or c['state'] not in OPEN_STATES:
                return {'applied': False, 'reason': 'NOT_OPEN'}
            released = c['outstanding_entry_qty']
            c['outstanding_entry_qty'] = 0
            if c['entry_filled_qty'] == 0:
                c['state'] = 'CANCELLED'
            elif c['held_qty'] == 0:
                self._close(c, float(ev['ts']))
            self.j.put_campaign(c)
            self.j.log(ev['ts'], 'ENTRY_REMAINDER_CANCELLED', {'released_qty': released, 'state': c['state']},
                       ticker=c['ticker'], ref=c['campaign_id'])
            return {'applied': True, 'state': c['state'], 'released_qty': released}
        return self.j.once(ev['event_id'], 'CANCEL_CONFIRMED', ev['ts'], run)

    # ── §11-13 management ──────────────────────────────────────────────────────
    def manage(self, obs: dict) -> dict:
        """obs: event_id, ts, campaign_id, quote {bid, ask, bid_size, ts}, stock_price, structural_break
        {bullish, bearish, evidence}, snapshot + items (full flow), prior_close, open_price, open_time."""
        return self.j.once(obs['event_id'], 'MANAGE', obs['ts'], lambda: self._manage(obs))

    def _manage(self, obs):
        ts = float(obs['ts'])
        c = self.j.campaign(obs['campaign_id'])
        if not c or c['state'] not in ('ACTIVE', 'ENTRY_PENDING') or c['held_qty'] <= 0:
            return {'decision': 'NO_HELD_POSITION', 'reasons': []}
        q = obs.get('quote') or {}
        self._marks(c, q, ts)
        logs = []
        if c.get('exit_pending'):
            reasons = c['exit_pending']['reasons']
        else:
            reasons = self._triggers(c, obs, ts, logs)
            if reasons:
                rot = 'CONFIRMED_OPPOSITE_CLUSTER_ROTATION' in reasons
                c['exit_pending'] = {'reasons': reasons, 'primary': reasons[0], 'requested_ts': ts,
                                     'event_id': obs['event_id'],
                                     'rotation_direction': opposite(c['direction']) if rot else None}
                self.j.log(ts, 'EXIT_DECISION', {'campaign_id': c['campaign_id'], 'reasons': reasons,
                                                 'logs': logs, 'held': c['held_qty']},
                           ticker=c['ticker'], ref=c['campaign_id'])
        self.j.put_campaign(c)
        if not reasons:
            if logs:
                self.j.log(ts, 'HOLD', {'campaign_id': c['campaign_id'], 'logs': logs},
                           ticker=c['ticker'], ref=c['campaign_id'])
            return {'decision': 'HOLD', 'reasons': [], 'logs': logs}
        if quote_usable_for_exit(q, ts):
            return {'decision': 'EXIT_REQUEST', 'reasons': reasons, 'qty': c['held_qty'],
                    'reference_bid': q['bid'], 'logs': logs}
        return {'decision': 'EXIT_PENDING_EXECUTABLE_QUOTE', 'reasons': reasons, 'logs': logs}

    def _marks(self, c, q, ts):
        bid = q.get('bid')
        if bid is None or q.get('ts') is None or float(q['ts']) > ts:
            return
        m = c.setdefault('marks', {})
        m['peak_bid'] = max(m.get('peak_bid') or bid, bid)
        m['min_bid'] = min(m.get('min_bid') or bid, bid)
        m['last_bid'], m['last_ts'] = bid, ts
        if c.get('avg_entry'):
            m['max_gain_pct'] = round((m['peak_bid'] / c['avg_entry'] - 1) * 100, 2)
            m['max_drawdown_pct'] = round((m['min_bid'] / c['avg_entry'] - 1) * 100, 2)

    def _triggers(self, c, obs, ts, logs) -> list:
        r = []
        bull = c['direction'] == 'BULLISH'
        # 1. favorable overnight underlying gap
        op, pc, ot = obs.get('open_price'), obs.get('prior_close'), obs.get('open_time')
        if op is not None and pc is not None and ot is not None and c['first_entry_ts'] < float(ot) <= ts:
            g = S.GAP_MIN_FRACTION
            if (bull and op > pc * (1 + g)) or (not bull and op < pc * (1 - g)):
                r.append('FAVORABLE_REGULAR_SESSION_OPEN_GAP_SELL_ALL')
        # 2. planned / expiration deadline
        if ts >= min(c['planned_end'], cal.expiry_deadline(c['contract']['expiry'])):
            r.append('PLANNED_OR_EXPIRY_EXIT_DEADLINE')
        # 3. precommitted risk
        rp = c.get('risk_plan') or {}
        px, brk = obs.get('stock_price'), obs.get('structural_break') or {}
        lvl = rp.get('underlying_level')
        if lvl is not None and px is not None and (brk.get('evidence') or {}).get('rule'):
            if (bull and brk.get('bearish') and px <= lvl) or (not bull and brk.get('bullish') and px >= lvl):
                r.append('PRECOMMITTED_UNDERLYING_INVALIDATION')
        lim, q = rp.get('premium_loss_limit'), obs.get('quote') or {}
        if lim is not None and c.get('avg_entry') and quote_usable_for_exit(q, ts):
            if q['bid'] <= c['avg_entry'] * (1 - lim):
                r.append('PRECOMMITTED_PREMIUM_RISK_LIMIT')
        # 4. confirmed opposite-side rotation (management flow after THIS campaign's entry only)
        if obs.get('snapshot') is not None and obs.get('items') is not None:
            a = clusters.assess(obs['snapshot'], obs['items'], ts, since_ts=c['first_entry_ts'])
            want = clusters.BEAR if bull else clusters.BULL
            if a['state'] == clusters.CONTESTED:
                logs.append('CONTESTED_BOTH_SIDES_CLUSTERING')
            elif a['state'] == want:
                opp = a['clusters']['P' if bull else 'C']
                ft = [clusters.followthrough(obs['items'], cl, ts) for cl in opp]
                if any(f['satisfied'] for f in ft):
                    r.append('CONFIRMED_OPPOSITE_CLUSTER_ROTATION')
                else:
                    logs.append('ROTATION_AWAITING_INDEPENDENT_FOLLOWTHROUGH')
        return r


def _brief(a: dict) -> dict:
    return {'state': a['state'], 'calls_clustered': a['calls_clustered'], 'puts_clustered': a['puts_clustered'],
            'certifiable': a['certifiable'], 'reasons': a['reasons'], 'underlying': a['underlying'],
            'clusters': {k: [{x: cl[x] for x in ('kind', 'expiry', 'strikes', 'members', 'latest_end',
                                                 'resemblance_max')} for cl in v]
                         for k, v in a['clusters'].items()}}
