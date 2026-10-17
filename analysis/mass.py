"""
Attention MASS + abnormality (spec §1-8) — the raw physics the wave state machine runs on.

  • Mass (§1-2): each contract's fresh premium weighted by strike relevance
        w_k = exp(-alpha · |K-S|/S),   mass_k = fresh_vol · ref_price · 100 · w_k
    summed to CallMass / PutMass / TickerMass, and (across the pool) AttentionShare.
  • Smoothing without losing speed (§3): fast/slow EWMA of ticker mass → AttentionImpulse.
  • Abnormality (§4): adaptive per-ticker Z (mean/std EWMA, frozen while abnormal so the
    baseline stays "non-event") for total, calls, and puts.
  • Derivatives (§5): velocity + acceleration of fast mass (total, call, put).
  • Control (§6): CallControl / PutControl / SignedControl from mass.
  • Strike quality (§7): HHI + SINGLE_STRIKE_DOMINANT vs COORDINATED_CHAIN vs DISTRIBUTED.
  • Ranking (§8): the 35/20/15/10/10/10 Attention Score, normalised across the Mag-7.

Pure functions + a small per-ticker stateful accumulator (`TickerMass`). No I/O.
"""
import math

import config


def relevance_weight(strike: float, spot: float, alpha: float = None) -> float:
    """w_k = exp(-alpha · |K-S|/S).  ATM≈1, one strike≈0.8, two≈0.6, then fades fast."""
    if not spot:
        return 1.0
    a = config.WAVE_RELEVANCE_ALPHA if alpha is None else alpha
    return math.exp(-a * abs(strike - spot) / spot)


def compute_masses(strikes: dict, spot: float) -> dict:
    """
    strikes: {(strike, side): {'fresh_vol', 'mark', ...}} for one ticker this poll.
    Returns CallMass/PutMass/TickerMass, per-side per-strike mass, HHI, class, and top strike.
    """
    call, put = {}, {}
    call_dan = put_dan = 0.0        # delta-adjusted notional = contracts · price · 100 · |delta|
    call_info = put_info = 0.0      # v3-review #15: PRICE-INDEPENDENT participation (contracts · relevance)
    for (k, side), d in strikes.items():
        fv = d.get('fresh_vol') or 0
        mark = d.get('mark')
        if fv <= 0 or not mark or mark <= 0:
            continue
        w = relevance_weight(k, spot)
        m = fv * float(mark) * 100.0 * w
        (call if side == 'CALL' else put)[k] = (call if side == 'CALL' else put).get(k, 0.0) + m
        dlt = d.get('delta')
        dan = fv * float(mark) * 100.0 * (abs(float(dlt)) if dlt is not None else 1.0)
        info = fv * w                                   # contracts, not dollars — a cheap ATM event counts
        if side == 'CALL':
            call_dan += dan; call_info += info
        else:
            put_dan += dan; put_info += info
    call_mass, put_mass = sum(call.values()), sum(put.values())
    return {
        'call_mass': call_mass, 'put_mass': put_mass, 'ticker_mass': call_mass + put_mass,
        'call_dan': call_dan, 'put_dan': put_dan, 'ticker_dan': call_dan + put_dan,
        # InformationMass (#15): capital magnitude and information content are different dimensions —
        # kept parallel so an expensive deep-ITM pool cannot bury a cleaner cheap-convexity event.
        'call_info': call_info, 'put_info': put_info, 'ticker_info': call_info + put_info,
        'call_strikes': call, 'put_strikes': put,
        'call': _side_quality(call), 'put': _side_quality(put),
    }


def _side_quality(strike_mass: dict) -> dict:
    """HHI + classification for one side's per-strike mass distribution (§7)."""
    total = sum(strike_mass.values())
    if total <= 0:
        return {'total': 0.0, 'hhi': 0.0, 'top_strike': None, 'top_share': 0.0,
                'class': 'THIN', 'quality': 0.0, 'n_active': 0}
    shares = {k: m / total for k, m in strike_mass.items()}
    hhi = sum(s * s for s in shares.values())
    ranked = sorted(shares.items(), key=lambda x: -x[1])
    top_k, top_s = ranked[0]
    second_s = ranked[1][1] if len(ranked) > 1 else 0.0
    n_meaningful = sum(1 for s in shares.values() if s >= config.WAVE_CHAIN_MIN_SHARE)
    top2_s = top_s + second_s
    # A COORDINATED_CHAIN is a SYNCHRONISED shape, not three mediocre strikes summed: at least two
    # strikes must EACH own a meaningful share AND a real second participant must exist AND the top
    # two together must dominate. Otherwise a single strike carrying it all is SINGLE_STRIKE_DOMINANT
    # — never let one strike's volume masquerade as a chain (spec §5/§13).
    if top_s >= config.WAVE_SINGLE_TOP_SHARE:
        cls, quality = 'SINGLE_STRIKE_DOMINANT', top_s
    elif (n_meaningful >= 2 and second_s >= config.CHAIN_MIN_SECOND_SHARE
          and top2_s >= config.CHAIN_MIN_TOP2_SHARE):
        cls, quality = 'COORDINATED_CHAIN', min(1.0, top2_s)
    elif top_s >= 0.45:                      # dominant-ish single strike that isn't a real chain
        cls, quality = 'SINGLE_STRIKE_DOMINANT', top_s
    elif len([s for s in shares.values() if s >= 0.05]) >= 4:
        cls, quality = 'DISTRIBUTED', 0.15
    else:
        cls, quality = 'THIN', top_s * 0.5
    return {'total': total, 'hhi': round(hhi, 3), 'top_strike': top_k, 'top_share': round(top_s, 3),
            'second_share': round(second_s, 3), 'top2_share': round(top2_s, 3),
            'class': cls, 'quality': round(quality, 3), 'n_active': n_meaningful}


class _EWMAZ:
    """
    Robust adaptive abnormality: z against an EWMA mean with a mean-absolute-deviation scale
    (std ≈ 1.4826·MAD), clipped. The baseline is ALWAYS updated (slowly) — so a wave that merely
    *remains* elevated has its abnormality decay toward zero (spec §5: a large but no-longer-fresh
    wave is not a new event), while a genuine surge above the recent norm still spikes z. A hard
    "freeze when abnormal" is deliberately avoided: it collapses the scale and makes z explode.
    """
    def __init__(self):
        self.mean = None; self.mad = None
        self.n = 0                     # samples behind the baseline (flow handoff §4: missing ≠ zero)

    def z_and_update(self, x: float) -> float:
        self.n += 1
        if self.mean is None:
            self.mean = x; self.mad = max(abs(x), config.WAVE_EPS)
            return 0.0
        dev = x - self.mean
        disp = 1.4826 * self.mad + config.WAVE_EPS
        z = max(-config.SHOCK_CLIP, min(config.SHOCK_CLIP, dev / disp))
        a = config.WAVE_BASELINE_ALPHA
        self.mean += a * dev
        self.mad = (1 - a) * self.mad + a * abs(dev)
        return round(z, 3)


class TickerMass:
    """Per-ticker stateful accumulator: EWMA fast/slow, Z, velocity/accel, WaveEnergy."""

    def __init__(self):
        self.fast = self.slow = 0.0
        self.fast_call = self.fast_put = 0.0
        self.prev_fast = self.prev_vel = 0.0
        self.prev_fast_call = self.prev_vel_call = 0.0
        self.prev_fast_put = self.prev_vel_put = 0.0
        self.z_tot = _EWMAZ(); self.z_call = _EWMAZ(); self.z_put = _EWMAZ()
        self.wave_energy = 0.0
        self.post_wave_min = None      # local FastMass minimum since a wave ended (refractory renewal)

    def update(self, m: dict) -> dict:
        lf, ls = config.WAVE_LAMBDA_FAST, config.WAVE_LAMBDA_SLOW
        tm, cm, pm = m['ticker_mass'], m['call_mass'], m['put_mass']
        self.fast = lf * tm + (1 - lf) * self.fast
        self.slow = ls * tm + (1 - ls) * self.slow
        self.fast_call = lf * cm + (1 - lf) * self.fast_call
        self.fast_put = lf * pm + (1 - lf) * self.fast_put

        vel = self.fast - self.prev_fast
        acc = vel - self.prev_vel
        vel_call = self.fast_call - self.prev_fast_call
        acc_call = vel_call - self.prev_vel_call
        vel_put = self.fast_put - self.prev_fast_put
        acc_put = vel_put - self.prev_vel_put
        self.prev_fast, self.prev_vel = self.fast, vel
        self.prev_fast_call, self.prev_vel_call = self.fast_call, vel_call
        self.prev_fast_put, self.prev_vel_put = self.fast_put, vel_put

        z = self.z_tot.z_and_update(tm)
        zc = self.z_call.z_and_update(cm)
        zp = self.z_put.z_and_update(pm)
        impulse = self.fast / max(self.slow, config.WAVE_EPS)
        self.wave_energy += max(0.0, self.fast - (self.z_tot.mean or 0.0))
        if self.post_wave_min is not None:
            self.post_wave_min = min(self.post_wave_min, self.fast)

        total = cm + pm
        call_ctrl = cm / max(total, config.WAVE_EPS) if total > 0 else 0.0
        put_ctrl = pm / max(total, config.WAVE_EPS) if total > 0 else 0.0
        return {
            'ticker_mass': tm, 'call_mass': cm, 'put_mass': pm,
            'call_dan': m.get('call_dan', 0.0), 'put_dan': m.get('put_dan', 0.0),
            'ticker_dan': m.get('ticker_dan', 0.0),
            'fast_mass': self.fast, 'slow_mass': self.slow, 'impulse': round(impulse, 3),
            'mass_z': z, 'call_z': zc, 'put_z': zp,
            'velocity': round(vel), 'acceleration': round(acc),
            'call_velocity': round(vel_call), 'put_velocity': round(vel_put),
            'call_acceleration': round(acc_call), 'put_acceleration': round(acc_put),
            'call_control': round(call_ctrl, 3), 'put_control': round(put_ctrl, 3),
            'signed_control': round(call_ctrl - put_ctrl, 3),
            'wave_energy': round(self.wave_energy), 'baseline_mean': round(self.z_tot.mean or 0.0),
            # z on an UNSEEDED baseline is 0 by construction ("no evidence"), not "measured normal" —
            # the label keeps the two apart in the ledger and research reads.
            'baseline_n': self.z_tot.n,
            'baseline_quality': ('SEEDED' if self.z_tot.n > config.MASS_BASELINE_MIN_SAMPLES else 'UNSEEDED'),
        }

    def mark_wave_end(self):
        self.post_wave_min = self.fast


def _norm(vals: dict) -> dict:
    mx = max((v for v in vals.values() if v and v > 0), default=0.0)
    return {k: (max(0.0, v or 0.0) / mx if mx > 0 else 0.0) for k, v in vals.items()}


def rank_attention(metrics: dict) -> list:
    """
    Attention Score (§8), normalised across the Mag-7:
        35·share + 20·Z + 15·(+velocity) + 10·(+accel) + 10·side-dominance + 10·strike-quality
    `metrics[ticker]` must carry attention_share, mass_z, velocity, acceleration, and the
    dominant side's control + strike quality. Returns rows sorted by score desc, with rank.
    """
    syms = list(metrics)
    share = {s: metrics[s].get('attention_share', 0.0) for s in syms}
    zc = {s: metrics[s].get('mass_z', 0.0) for s in syms}
    vel = {s: metrics[s].get('velocity', 0.0) for s in syms}
    acc = {s: metrics[s].get('acceleration', 0.0) for s in syms}
    ns, nz, nv, na = _norm(share), _norm(zc), _norm(vel), _norm(acc)
    rows = []
    for s in syms:
        m = metrics[s]
        dom = m.get('dominant_side')
        ctrl = m.get('call_control', 0.0) if dom == 'CALL' else m.get('put_control', 0.0)
        side_dom_q = max(0.0, min(1.0, 2 * ctrl - 1))
        strike_q = (m.get(dom.lower(), {}) or {}).get('quality', 0.0) if dom else 0.0
        score = (35 * ns[s] + 20 * nz[s] + 15 * nv[s] + 10 * na[s]
                 + 10 * side_dom_q + 10 * strike_q)
        rows.append({**m, 'symbol': s, 'attention_score': round(score, 1),
                     'side_dominance_quality': round(side_dom_q, 3),
                     'strike_quality': round(strike_q, 3)})
    rows.sort(key=lambda r: r['attention_score'], reverse=True)
    for i, r in enumerate(rows):
        r['rank'] = i + 1
    return rows
