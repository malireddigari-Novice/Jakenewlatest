"""
Per-strike event-time abnormality (new-spec P2, §3-5; safeguards #6-8, #13) — pure, I/O-free.

Total volume is not enough. What matters is: at THIS moment, which strike carries the most abnormal
NEW information relative to its OWN normal behavior and its neighbors?

  • BarVolumeShock — current 1-min volume vs the contract's own ROBUST baseline (median + MAD, which
    earlier large prints do not contaminate the way an arithmetic mean would). A persistently-busy
    contract adapts into its own background (high median → low shock); a normally-quiet contract that
    suddenly prints becomes highly informative — BackgroundFlowAdjustment falls out for free.
  • Tiny-baseline safeguard (#6) — a shock only counts as `significant` if it ALSO clears an absolute
    contracts + notional floor (1→20 contracts is a 20× ratio but not institutional).
  • StrikeRelativeShock — this strike's shock vs its neighbors' (is it unusual *right now* vs nearby).
  • ClusterShock — how many neighboring strikes are activating together (multi-strike coordination).
  • StrikePositionAtEvent (#8) — event-time moneyness bucket; never recompute from a later spot.
"""
import config


def bar_shock(minute_vols, mark=None) -> dict:
    """Robust one-minute volume shock for one contract from its trailing per-minute series."""
    v = [float(x) for x in (minute_vols or []) if x is not None and x >= 0]
    if len(v) < config.BARSHOCK_MIN_BINS:
        return {'shock': 0.0, 'current': (round(v[-1]) if v else 0), 'baseline': 0.0,
                'significant': False, 'notional': None}
    cur = v[-1]
    prior = sorted(v[:-1])
    n = len(prior)
    med = prior[n // 2]
    mad = sorted(abs(x - med) for x in prior)[n // 2]
    disp = 1.4826 * mad + config.BARSHOCK_EPS
    shock = round((cur - med) / disp, 2)
    notional = (cur * mark * 100) if mark else None
    significant = (cur >= config.BARSHOCK_MIN_CONTRACTS and shock >= config.BARSHOCK_MIN_Z
                   and (notional is None or notional >= config.BARSHOCK_MIN_NOTIONAL))
    return {'shock': shock, 'current': round(cur), 'baseline': round(med, 1),
            'significant': significant, 'notional': round(notional) if notional else None}


def strike_position(strike, spot, side) -> str:
    """Event-time moneyness bucket: 2ITM/1ITM/ATM/1OTM/2OTM (side-aware). Store this at event time —
    the same fixed strike changes relationship to spot through the session (#8)."""
    if not spot:
        return 'ATM'
    d = (strike - spot) / spot
    itm = (-d if side == 'CALL' else d)          # >0 = in the money
    if abs(d) < config.BARSHOCK_ATM_PCT:
        return 'ATM'
    tag = 'ITM' if itm > 0 else 'OTM'
    return ('2' + tag) if abs(d) >= config.BARSHOCK_FAR_PCT else ('1' + tag)


def relative_shock(this_shock, neighbor_shocks) -> float:
    """This strike's shock relative to its strongest neighbor (>1 = unusually informative vs nearby)."""
    others = [s for s in neighbor_shocks if s is not None]
    mx = max(others) if others else 0.0
    return round(this_shock / mx, 2) if mx > 0 else this_shock


def cluster_shock(shocks) -> int:
    """How many strikes are simultaneously elevated (multi-strike coordination count)."""
    return sum(1 for s in shocks if s is not None and s >= config.BARSHOCK_MIN_Z)


def classify_event(this_shock, rel_shock, cluster_count) -> str:
    """CONCENTRATED_SINGLE_STRIKE vs COORDINATED_MULTI_STRIKE vs a plain strike event / none."""
    if this_shock < config.BARSHOCK_MIN_Z:
        return 'NONE'
    if cluster_count >= config.BARSHOCK_CLUSTER_MIN:
        return 'COORDINATED_MULTI_STRIKE_EVENT'
    if rel_shock >= config.BARSHOCK_CONCENTRATED_REL:
        return 'CONCENTRATED_SINGLE_STRIKE_EVENT'
    return 'STRIKE_EVENT'
