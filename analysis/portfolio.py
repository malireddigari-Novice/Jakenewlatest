"""
Portfolio correlation risk layer (addendum #18) — pure, I/O-free.

Signal DISCOVERY stays unconstrained: multiple Mag-7 campaigns may coexist (safeguard #7), and this
layer is never a discovery or a hold constraint. But the Mag-7 are one highly-correlated factor — four
independent CALL campaigns is really one enormous LONG-NASDAQ / LONG-LARGE-CAP-TECH bet. Good detection
logic should not accidentally build a massively concentrated book.

So, separately from the campaign engine, we measure aggregate CORRELATED exposure across open
positions and answer one risk question at entry time: would adding this position push same-direction
correlated exposure past the cap? A CALL is +1 directional unit of long-tech, a PUT is −1. The cap is
on the count of same-direction correlated campaigns (PORT_MAX_CORR_SIDE) and, optionally, on the net
delta-adjusted notional (PORT_MAX_NET_DELTA_NOTIONAL). This is a veto only — it slows concentration,
it never forces an exit and never suppresses discovery/holding.
"""
import config


def _dir(side) -> int:
    return 1 if side == 'CALL' else -1


def exposure(positions) -> dict:
    """Aggregate correlated exposure across open positions.
    Each position: {'side', 'qty', 'entry_price', 'delta'(optional)}. Long-tech = CALL(+)/PUT(−)."""
    n_call = sum(1 for p in positions if p.get('side') == 'CALL')
    n_put = sum(1 for p in positions if p.get('side') == 'PUT')
    net_dn = 0.0
    for p in positions:
        qty = p.get('qty') or 0
        price = p.get('entry_price') or 0.0
        dlt = p.get('delta')
        dn = qty * price * 100.0 * (abs(float(dlt)) if dlt is not None else 1.0)
        net_dn += _dir(p.get('side')) * dn
    return {'n_call': n_call, 'n_put': n_put, 'n_long_tech': n_call, 'n_short_tech': n_put,
            'net_delta_notional': round(net_dn), 'gross_positions': len(positions)}


def gate(new_side, positions) -> dict:
    """Would opening a NEW `new_side` position breach the correlated-exposure cap? Returns
    {ok, reason, exposure}. ok=True allows the entry. Same-ticker management is the caller's concern —
    this only counts DISTINCT correlated directional exposure."""
    exp = exposure(positions)
    same = exp['n_long_tech'] if new_side == 'CALL' else exp['n_short_tech']
    if config.PORT_MAX_CORR_SIDE > 0 and same >= config.PORT_MAX_CORR_SIDE:
        return {'ok': False, 'exposure': exp,
                'reason': (f'{same} correlated {new_side} campaign(s) already open ≥ cap '
                           f'{config.PORT_MAX_CORR_SIDE} — adding another concentrates one long-tech factor')}
    if config.PORT_MAX_NET_DELTA_NOTIONAL > 0:
        # projecting the new leg as ~one average existing unit of directional notional
        avg = (abs(exp['net_delta_notional']) / max(1, exp['gross_positions'])) if exp['gross_positions'] else 0.0
        projected = exp['net_delta_notional'] + _dir(new_side) * avg
        if abs(projected) > config.PORT_MAX_NET_DELTA_NOTIONAL:
            return {'ok': False, 'exposure': exp,
                    'reason': (f'net Δ-notional ${projected:,.0f} would exceed cap '
                               f'${config.PORT_MAX_NET_DELTA_NOTIONAL:,.0f}')}
    return {'ok': True, 'exposure': exp, 'reason': 'within correlated-exposure limits'}
