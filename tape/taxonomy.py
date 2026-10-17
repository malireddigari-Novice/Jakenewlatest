"""
Structure taxonomy (flow handoff §5).

Two different questions, two functions:
  geometry(legs)       — PUBLIC TAPE: leg sides are not known, so only the shape of the strikes/expiries/
                         ratio is described ("VERTICAL_CANDIDATE"). Never a debit/credit, never a holder.
  classify_known(...)  — KNOWN SIDES (a user's own recorded position, or an independently verified
                         linkage): the full structure name. A covered position needs independently
                         verified stock, a cash-secured put needs verified collateral; otherwise the bare
                         short option is named, and a short put is downside exposure.
`ROLL_UP` means a numerically higher strike, NOT a bullish change. Nothing here is a recommendation; a
naked short-premium structure is never translated into a small-account purchase.

The handoff's ZIP (43 tags) was not available; this list implements every family the handoff names.
"""
from math import gcd
from functools import reduce

KNOWN_TAGS = (
    'LONG_CALL', 'LONG_PUT', 'SHORT_CALL', 'SHORT_PUT',
    'BULL_CALL_DEBIT_VERTICAL', 'BEAR_CALL_CREDIT_VERTICAL', 'BEAR_PUT_DEBIT_VERTICAL', 'BULL_PUT_CREDIT_VERTICAL',
    'LONG_CALENDAR', 'SHORT_CALENDAR', 'LONG_DIAGONAL', 'SHORT_DIAGONAL',
    'ROLL_UP', 'ROLL_DOWN', 'ROLL_OUT', 'ROLL_IN', 'ROLL_UP_AND_OUT', 'ROLL_DOWN_AND_OUT',
    'SYNTHETIC_LONG', 'SYNTHETIC_SHORT', 'RISK_REVERSAL_BULLISH', 'RISK_REVERSAL_BEARISH',
    'LONG_STRADDLE', 'SHORT_STRADDLE', 'LONG_STRANGLE', 'SHORT_STRANGLE',
    'LONG_IRON_CONDOR', 'SHORT_IRON_CONDOR', 'LONG_IRON_BUTTERFLY', 'SHORT_IRON_BUTTERFLY',
    'LONG_BUTTERFLY', 'SHORT_BUTTERFLY', 'BROKEN_WING_BUTTERFLY', 'LONG_CONDOR', 'SHORT_CONDOR',
    'CALL_RATIO_SPREAD', 'PUT_RATIO_SPREAD', 'CALL_BACKSPREAD', 'PUT_BACKSPREAD',
    'COLLAR', 'COVERED_CALL', 'CASH_SECURED_PUT', 'SEAGULL', 'UNCLASSIFIED',
)
ALIASES = {
    'BULL_CALL_DEBIT_VERTICAL': ('bull call spread', 'call debit spread'),
    'BEAR_PUT_DEBIT_VERTICAL': ('bear put spread', 'put debit spread'),
    'BEAR_CALL_CREDIT_VERTICAL': ('bear call spread', 'call credit spread'),
    'BULL_PUT_CREDIT_VERTICAL': ('bull put spread', 'put credit spread'),
    'LONG_CALENDAR': ('time spread', 'horizontal spread'),
    'SYNTHETIC_LONG': ('synthetic stock',),
    'RISK_REVERSAL_BULLISH': ('combo', 'split-strike synthetic', 'financed call', 'put-financed call'),
}
# Verified non-directional causes a print can be attributed to only with independent evidence.
NOISE_CAUSES = ('EXPIRY_PIN_ACTIVITY', 'EXERCISE_OR_ASSIGNMENT', 'CORPORATE_ACTION_ADJUSTMENT',
                'ERROR_CORRECTION', 'DIVIDEND_CAPTURE', 'MARKET_MAKER_INVENTORY')


def reduced_ratio(qtys) -> str:
    """Quantities reduced by their greatest common divisor: 4,000 / 7,000 → '4:7'."""
    q = [abs(int(x)) for x in qtys if x]
    if not q:
        return ''
    g = reduce(gcd, q)
    return ':'.join(str(x // g) for x in q)


def geometry(legs) -> str:
    """Shape only. legs: [{expiry (date|None), right 'C'/'P', strike, qty}] — sides UNKNOWN."""
    n = len(legs)
    exps = {l['expiry'] for l in legs}
    rights = {l['right'] for l in legs}
    strikes = sorted(l['strike'] for l in legs)
    ratio = reduced_ratio(l['qty'] for l in sorted(legs, key=lambda l: (str(l['expiry']), l['right'], l['strike'])))
    if None in exps:
        return 'EXPIRY_UNKNOWN_MULTI_LEG_CANDIDATE'
    if n == 2:
        a, b = legs
        if len(rights) == 1:
            if a['expiry'] == b['expiry']:
                return 'VERTICAL_CANDIDATE' if ratio == '1:1' else 'RATIO_SPREAD_CANDIDATE'
            if a['strike'] == b['strike']:
                return 'CALENDAR_OR_ROLL_OUT_CANDIDATE'
            return 'DIAGONAL_OR_ROLL_CANDIDATE'
        if a['expiry'] == b['expiry']:
            return ('STRADDLE_OR_SYNTHETIC_CANDIDATE' if a['strike'] == b['strike']
                    else 'STRANGLE_RISK_REVERSAL_OR_COLLAR_CANDIDATE')
        return 'CROSS_EXPIRY_CALL_PUT_CANDIDATE'
    if n == 3 and len(exps) == 1:
        if len(rights) == 1:
            byk = sorted(legs, key=lambda l: l['strike'])
            if reduced_ratio(l['qty'] for l in byk) == '1:2:1':
                equal = abs((strikes[1] - strikes[0]) - (strikes[2] - strikes[1])) < 1e-9
                return 'BUTTERFLY_CANDIDATE' if equal else 'UNEQUAL_WING_BUTTERFLY_CANDIDATE'
            return 'THREE_LEG_SAME_RIGHT_CANDIDATE'
        return 'SEAGULL_CANDIDATE'
    if n == 4 and len(exps) == 1:
        if len(rights) == 2 and sum(1 for l in legs if l['right'] == 'C') == 2:
            mids = strikes[1:3]
            return ('IRON_BUTTERFLY_CANDIDATE' if mids[0] == mids[1] else 'IRON_CONDOR_CANDIDATE')
        if len(rights) == 1:
            return 'CONDOR_CANDIDATE'
    return 'MULTI_LEG_CANDIDATE'


def _single(l):
    long = l['qty'] > 0
    return ('LONG_' if long else 'SHORT_') + ('CALL' if l['right'] == 'C' else 'PUT')


def classify_known(legs, *, stock_qty_verified=None, collateral_verified=False) -> dict:
    """legs: [{expiry, right, strike, qty (signed: + long / − short)}] with INDEPENDENTLY KNOWN sides.
    stock_qty_verified: shares independently verified (None = unknown). Returns {tag, aliases, note}."""
    legs = [l for l in legs if l.get('qty')]
    note = None
    if len(legs) == 1:
        l = legs[0]
        tag = _single(l)
        if tag == 'SHORT_CALL' and stock_qty_verified and stock_qty_verified >= 100 * abs(l['qty']):
            tag = 'COVERED_CALL'
        elif tag == 'SHORT_PUT':
            tag = 'CASH_SECURED_PUT' if collateral_verified else 'SHORT_PUT'
            note = None if collateral_verified else 'short put = downside exposure (collateral not verified)'
        elif tag == 'SHORT_CALL':
            note = 'uncovered short call (stock not independently verified)'
        return {'tag': tag, 'aliases': ALIASES.get(tag, ()), 'note': note}

    rights = {l['right'] for l in legs}
    exps = {l['expiry'] for l in legs}
    longs = [l for l in legs if l['qty'] > 0]
    shorts = [l for l in legs if l['qty'] < 0]
    tag = 'UNCLASSIFIED'
    if len(legs) == 2:
        a, b = sorted(legs, key=lambda l: (l['expiry'], l['strike']))
        same_size = abs(a['qty']) == abs(b['qty'])
        if len(rights) == 1 and len(exps) == 1 and longs and shorts:
            lo, hi = (a, b) if a['strike'] < b['strike'] else (b, a)
            r = a['right']
            if same_size:
                if r == 'C':
                    tag = 'BULL_CALL_DEBIT_VERTICAL' if lo['qty'] > 0 else 'BEAR_CALL_CREDIT_VERTICAL'
                else:
                    tag = 'BEAR_PUT_DEBIT_VERTICAL' if hi['qty'] > 0 else 'BULL_PUT_CREDIT_VERTICAL'
            else:
                more_long = sum(abs(l['qty']) for l in longs) > sum(abs(l['qty']) for l in shorts)
                tag = (('CALL_BACKSPREAD' if more_long else 'CALL_RATIO_SPREAD') if r == 'C'
                       else ('PUT_BACKSPREAD' if more_long else 'PUT_RATIO_SPREAD'))
        elif len(rights) == 1 and len(exps) == 2 and longs and shorts:
            near, far = a, b
            if near['strike'] == far['strike']:
                tag = 'LONG_CALENDAR' if far['qty'] > 0 else 'SHORT_CALENDAR'
            else:
                tag = 'LONG_DIAGONAL' if far['qty'] > 0 else 'SHORT_DIAGONAL'
        elif len(rights) == 2 and len(exps) == 1:
            c = next(l for l in legs if l['right'] == 'C')
            p = next(l for l in legs if l['right'] == 'P')
            if c['qty'] > 0 and p['qty'] > 0:
                tag = 'LONG_STRADDLE' if c['strike'] == p['strike'] else 'LONG_STRANGLE'
            elif c['qty'] < 0 and p['qty'] < 0:
                tag = 'SHORT_STRADDLE' if c['strike'] == p['strike'] else 'SHORT_STRANGLE'
            elif c['qty'] > 0 > p['qty']:
                if stock_qty_verified:
                    tag = 'UNCLASSIFIED'
                elif c['strike'] == p['strike']:
                    tag = 'SYNTHETIC_LONG'
                else:
                    tag = 'RISK_REVERSAL_BULLISH'
                    note = 'short put leg = downside exposure'
            else:
                if stock_qty_verified and stock_qty_verified >= 100 * abs(c['qty']):
                    tag = 'COLLAR'
                elif c['strike'] == p['strike']:
                    tag = 'SYNTHETIC_SHORT'
                else:
                    tag = 'RISK_REVERSAL_BEARISH'
                    note = 'short call leg uncovered unless stock is verified'
    elif len(legs) == 3 and len(exps) == 1:
        byk = sorted(legs, key=lambda l: l['strike'])
        if len(rights) == 1 and reduced_ratio(l['qty'] for l in byk) == '1:2:1':
            ks = [l['strike'] for l in byk]
            equal = abs((ks[1] - ks[0]) - (ks[2] - ks[1])) < 1e-9
            if not equal:
                tag = 'BROKEN_WING_BUTTERFLY'
            else:
                tag = 'LONG_BUTTERFLY' if byk[0]['qty'] > 0 else 'SHORT_BUTTERFLY'
        elif len(rights) == 2:
            calls = [l for l in legs if l['right'] == 'C']
            puts = [l for l in legs if l['right'] == 'P']
            if len(calls) == 2 and len(puts) == 1 and puts[0]['qty'] < 0:
                tag = 'SEAGULL'
                note = 'short put leg = downside exposure'
    elif len(legs) == 4 and len(exps) == 1:
        byk = sorted(legs, key=lambda l: (l['strike'], l['right']))
        if len(rights) == 2:
            inner = [l for l in legs if l['strike'] in (byk[1]['strike'], byk[2]['strike'])]
            short_inner = all(l['qty'] < 0 for l in inner)
            butterfly = byk[1]['strike'] == byk[2]['strike']
            if butterfly:
                tag = 'SHORT_IRON_BUTTERFLY' if short_inner else 'LONG_IRON_BUTTERFLY'
            else:
                tag = 'SHORT_IRON_CONDOR' if short_inner else 'LONG_IRON_CONDOR'
        elif len(rights) == 1:
            tag = 'LONG_CONDOR' if byk[0]['qty'] > 0 else 'SHORT_CONDOR'
    return {'tag': tag, 'aliases': ALIASES.get(tag, ()), 'note': note}


def roll_label(old, new) -> str:
    """Geometry of moving from `old` to `new` leg (same right). Higher strike is UP, later expiry is OUT —
    direction of the strike move is geometry, not a bullish/bearish claim."""
    up = new['strike'] > old['strike']
    down = new['strike'] < old['strike']
    out = new['expiry'] > old['expiry']
    back = new['expiry'] < old['expiry']
    if up and out:
        return 'ROLL_UP_AND_OUT'
    if down and out:
        return 'ROLL_DOWN_AND_OUT'
    if up:
        return 'ROLL_UP'
    if down:
        return 'ROLL_DOWN'
    if out:
        return 'ROLL_OUT'
    if back:
        return 'ROLL_IN'
    return 'UNCLASSIFIED'
