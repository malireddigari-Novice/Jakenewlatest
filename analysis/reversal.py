"""
Stateful opposite-side reversal detection (new-spec P3, §11-15, safeguard #10) — pure.

A single opposite-side print must NOT flip a position. Opposite flow accumulates EVIDENCE through a
persistent cluster that remembers events across time (the NVDA 215C @ 11:02 and 217.5C @ 11:43 belong
to one developing call reversal even 41 minutes apart):

    NONE → OPPOSITE_FLOW_DETECTED → REVERSAL_WATCH → REVERSAL_CLUSTER_CONFIRMED → REVERSAL_ACTIVATED

Only at REVERSAL_ACTIVATED does the incumbent leave. And EXIT ≠ REVERSE (safeguard #10, the most
important addition): opposite flow can invalidate the incumbent (EXIT to flat) without being strong
enough to ENTER the opposite side. Three outcomes: HOLD / EXIT_FLAT / EXIT_REVERSE.
"""
import config

STATES = ('NONE', 'OPPOSITE_FLOW_DETECTED', 'REVERSAL_WATCH', 'REVERSAL_CLUSTER_CONFIRMED',
          'REVERSAL_ACTIVATED')


def _ts(now):
    return now.timestamp() if hasattr(now, 'timestamp') else float(now)


def new_cluster(ticker, incumbent_side) -> dict:
    return {'ticker': ticker, 'incumbent_side': incumbent_side,
            'opposite_side': 'PUT' if incumbent_side == 'CALL' else 'CALL',
            'state': 'NONE', 'first_ts': None, 'last_ts': None, 'events': 0,
            'strikes': [], 'confirm_evals': 0}


def update(cluster: dict, ev: dict, now) -> dict:
    """Advance/decay the reversal state from this poll's opposite-side evidence.
    ev keys: opp_abnormal(bool), opp_control(0-1), opp_premium_accept(bool), cross_strike(bool),
    incumbent_progress_fail(bool), opp_strike(optional)."""
    opp_evt = bool(ev.get('opp_abnormal')) and (ev.get('opp_control', 0.0) or 0.0) >= config.REV_OPP_CONTROL_MIN
    if opp_evt:
        cluster['events'] += 1
        cluster['last_ts'] = _ts(now)
        if cluster['first_ts'] is None:
            cluster['first_ts'] = _ts(now)
        s = ev.get('opp_strike')
        if s is not None and s not in cluster['strikes']:
            cluster['strikes'].append(s)
    else:
        cluster['confirm_evals'] = max(0, cluster['confirm_evals'] - 1)   # decay without fresh evidence

    st = cluster['state']
    if st == 'NONE':
        if opp_evt:
            cluster['state'] = 'OPPOSITE_FLOW_DETECTED'
    elif st == 'OPPOSITE_FLOW_DETECTED':
        if cluster['events'] >= config.REV_WATCH_EVENTS:
            cluster['state'] = 'REVERSAL_WATCH'
        elif cluster['events'] == 0:
            cluster['state'] = 'NONE'
    elif st == 'REVERSAL_WATCH':
        # confirmation needs breadth/persistence AND the opposite premium being accepted (not a lone
        # ITM print that fizzles) — cross-strike OR ≥2 strikes OR sustained events, plus acceptance.
        confirm = ((ev.get('cross_strike') or len(cluster['strikes']) >= 2
                    or cluster['events'] >= config.REV_CONFIRM_EVENTS)
                   and ev.get('opp_premium_accept'))
        cluster['confirm_evals'] = cluster['confirm_evals'] + 1 if confirm else max(0, cluster['confirm_evals'] - 1)
        if cluster['confirm_evals'] >= config.REV_CONFIRM_EVALS:
            cluster['state'] = 'REVERSAL_CLUSTER_CONFIRMED'
    elif st == 'REVERSAL_CLUSTER_CONFIRMED':
        # activation needs the incumbent to actually be failing OR the opposite to seize real control
        if ev.get('incumbent_progress_fail') or (ev.get('opp_control', 0.0) or 0.0) >= config.REV_ACTIVATE_CONTROL:
            cluster['state'] = 'REVERSAL_ACTIVATED'
    return cluster


def outcome(cluster: dict, opp_qualifies: bool) -> str:
    """HOLD until REVERSAL_ACTIVATED; then EXIT_REVERSE if the opposite side independently qualifies
    as a fresh entry, else EXIT_FLAT (invalidate the incumbent without entering the other side)."""
    if cluster.get('state') != 'REVERSAL_ACTIVATED':
        return 'HOLD'
    return 'EXIT_REVERSE' if opp_qualifies else 'EXIT_FLAT'


def flip_plan(cluster: dict, opp_qualifies: bool) -> dict:
    """P5 opposite-side flip hand-off. When outcome is EXIT_REVERSE the flip is only HALF done — the
    incumbent leaves, but the opposite side must be entered as a FRESH campaign that recomputes its own
    ATM/best-convexity contract and passes every normal activation gate (absolute + route + spot). This
    returns a FLIP_PENDING descriptor for the announcement/log; it does NOT enter — the opposite entry
    always flows through the normal gated entry path on this/subsequent polls."""
    if outcome(cluster, opp_qualifies) != 'EXIT_REVERSE':
        return {'flip': False}
    return {'flip': True, 'state': 'FLIP_PENDING',
            'ticker': cluster.get('ticker'),
            'from_side': cluster.get('incumbent_side'),
            'to_side': cluster.get('opposite_side'),
            'events': cluster.get('events'), 'strikes': list(cluster.get('strikes') or []),
            'reason': (f"reversal ACTIVATED on {cluster.get('ticker')}: "
                       f"{cluster.get('incumbent_side')}→{cluster.get('opposite_side')}; opposite must "
                       f"recompute ATM and re-activate through the normal gates before it opens")}
