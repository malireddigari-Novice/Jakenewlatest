"""
Remaining-convexity contract ranking (handoff Priority 2) — pure, I/O-free.

The engine kept buying the most VISIBLE strike (META 565C) while a nearby strike (570C/580C) offered
far more convexity per premium dollar after resetting. Direction can be right while the expression is
expensive. This ranks candidate contracts across the near-ATM surface by how much CONVEXITY you buy per
dollar of premium, not by mass or which strike is loudest:

    convexity_score = w_gpp   · gamma-per-premium-dollar   (γ / mark — the core convexity/$ measure)
                    + w_cheap · room-from-low              (cheap = more remaining upside, less given back)
                    + w_rel   · moneyness relevance        (near-ATM keeps gamma live; far OTM is a lottery)

OPRA gives delta+gamma+IV (no vega/theta), so this is gamma-based convexity; theta/vega refinements are
a documented follow-up. Used to prefer the best expression of a confirmed campaign, not to pick a side.
"""
import config


def gamma_per_premium(gamma, mark) -> float:
    """Gamma per $ of premium — how much convexity one premium dollar buys. Higher = cheaper convexity."""
    if not gamma or not mark or mark <= 0:
        return 0.0
    return float(gamma) / float(mark)


def convexity_score(sd, spot) -> float:
    """0..~1 remaining-convexity-per-dollar for one contract snapshot (needs mark; gamma optional)."""
    mark = sd.get('mark')
    if not mark or mark <= 0:
        return 0.0
    gpp = gamma_per_premium(sd.get('gamma'), mark)
    gpp_term = max(0.0, min(1.0, gpp / config.CONVEXITY_GPP_REF)) if sd.get('gamma') is not None else 0.5
    low = sd.get('day_low') or mark
    ext = (mark / low) if low else 1.0
    cheap = (max(0.0, min(1.0, 1.0 - (ext - 1.0) / max(config.GATE_MAX_DIST_FROM_LOW - 1.0, 1e-9)))
             if ext >= 1 else 1.0)
    rel = (max(0.0, 1.0 - abs(sd['strike'] - spot) / (spot * config.CONVEXITY_MONEYNESS_PCT))
           if spot else 0.5)
    return round(config.CONVEXITY_W_GPP * gpp_term + config.CONVEXITY_W_CHEAP * cheap
                 + config.CONVEXITY_W_REL * rel, 4)


def rank(candidates, spot) -> list:
    """Rank quotable candidates by convexity-per-dollar, best first. Each returned dict carries
    convexity_score + gamma_per_premium for the ledger/log."""
    out = []
    for s in candidates or []:
        if not s.get('mark'):
            continue
        d = dict(s)
        d['convexity_score'] = convexity_score(s, spot)
        d['gamma_per_premium'] = round(gamma_per_premium(s.get('gamma'), s.get('mark')), 6)
        out.append(d)
    out.sort(key=lambda x: -x['convexity_score'])
    return out


def best(candidates, spot):
    r = rank(candidates, spot)
    return r[0] if r else None
