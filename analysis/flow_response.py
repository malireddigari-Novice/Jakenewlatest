"""
Flow Response / Premium Acceptance (new-spec, the GOOGL lesson) — pure, I/O-free.

High call volume is NOT automatically bullish accumulation. The GOOGL 362.5C had huge volume and a
great Vol/OI ratio, yet its premium was being *destroyed* the whole session — volume arriving while
the option made lower lows. That is rejection, not accumulation. The near-ATM 357.5C, by contrast,
saw volume while premium held/stabilised — acceptance.

Crucially we do NOT require premium *appreciation* to enter (that would make us late — the AMZN
lesson). We distinguish:
  • ABSORPTION — heavy volume arrives and premium STOPS falling / holds (bullish even if flat),
  • REJECTION — heavy volume arrives and premium keeps making lower lows,
  • NEUTRAL   — not enough volume/structure to say.

`premium_acceptance` returns {label, score 0-1, absorbing}. The engine uses ABSORPTION as positive
evidence (without needing appreciation) and REJECTION as a WATCH-not-ENTER signal.
"""
import config


def _prices(marks):
    """Normalise a marks series to a list of positive prices. Accepts bare floats OR (ts, price)
    tuples (contract_marks returns the latter)."""
    out = []
    for x in (marks or []):
        if x is None:
            continue
        v = x[1] if isinstance(x, (tuple, list)) else x
        if v is not None and v > 0:
            out.append(float(v))
    return out


def premium_acceptance(minute_vols, marks) -> dict:
    vols = [float(v) for v in (minute_vols or []) if v is not None and v >= 0]
    m = _prices(marks)
    if len(m) < 4 or len(vols) < 2:
        return {'label': 'NEUTRAL', 'score': 0.5, 'absorbing': False}

    n = max(1, len(vols) // 4)
    recent_vol = sum(vols[-n:]) / n
    prior_vol = (sum(vols[:-n]) / max(len(vols) - n, 1)) if len(vols) > n else recent_vol
    heavy = recent_vol >= config.ACCEPTANCE_HEAVY_MULT * max(prior_vol, 1e-9)
    if not heavy:
        return {'label': 'NEUTRAL', 'score': 0.5, 'absorbing': False}

    k = max(2, len(m) // 4)
    recent_low = min(m[-k:])
    prior_low = min(m[:-k]) if len(m) > k else recent_low
    if recent_low <= prior_low * (1 - config.ACCEPTANCE_REJECT_DROP):
        return {'label': 'REJECTION', 'score': 0.15, 'absorbing': False}   # heavy volume, lower lows
    holding = recent_low >= prior_low * 0.99                                # premium not falling
    return {'label': 'ABSORPTION' if holding else 'NEUTRAL',
            'score': 0.85 if holding else 0.5, 'absorbing': holding}
