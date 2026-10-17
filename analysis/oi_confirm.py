"""
T+1 campaign review via next-day open interest (new-spec) — pure reconciliation + JSONL store.

Today we only observe transactions. The next published OI is an AGGREGATE check: it can show that
some net contracts were opened, never who opened them or at what cost.

OI accounting (rule `oi-recon-v1`). For one unchanged contract and two adjacent, correctly aligned
OI vintages, let V = complete intervening-session volume and Δ = new OI − old OI. Every contract
traded is opening-on-both-sides (OO), closing-on-both-sides (CC) or a transfer (T):

    V = OO + CC + T          Δ = OO − CC

so the admissible ranges are
    OO ∈ [max(Δ,0), floor((V+Δ)/2)]      CC ∈ [max(−Δ,0), floor((V−Δ)/2)]
    T  ∈ [(V−|Δ|) mod 2, V−|Δ|]
If |Δ| > V the inputs are inconsistent (missing/corrected volume, wrong vintage, exercise, expiry or a
corporate action) → RECONCILE_REQUIRED, no inference.

Labels (aggregate annotations, never a verified BTO/STO of any trader):
    OPENING_SUPPORTED  Δ ≥ OI_SUPPORT_RATIO × V   — most of the session's volume can be net opening
    OPENING_PARTIAL    0 < Δ < that               — some net opening
    OPENING_WEAKENED   Δ ≤ 0                      — flat OI can hide transfers / offsetting opens+closes;
                                                    falling OI means aggregate closes outnumbered opens
    RECONCILE_REQUIRED |Δ| > V
    INCONCLUSIVE       a required input is missing

V must be the FULL completed session's volume. The fresh-window volume seen at entry is NOT V, and
today's published OI belongs to the PRIOR settlement — never compare it with today's partial volume.
For 0DTE there is no next-session OI before expiry: the review is skipped, not inferred.
"""
import json

import config

RULE_VERSION = 'oi-recon-v1'

# Retired labels from the pre-`oi-recon-v1` classifier → their bounded replacement. Stored records
# keep their original text; readers map through this.
LEGACY_LABELS = {
    'NEW_POSITION_CONFIRMED': 'OPENING_SUPPORTED',
    'PARTIALLY_CONFIRMED':    'OPENING_PARTIAL',
    'LIKELY_CLOSING_CHURN':   'OPENING_WEAKENED',
    'INCONCLUSIVE':           'INCONCLUSIVE',
}


def oi_bounds(volume: int, delta: int) -> dict | None:
    """Admissible OO/CC/T ranges for session volume V and OI change Δ. None when |Δ| > V."""
    v, d = int(volume), int(delta)
    if v < 0 or abs(d) > v:
        return None
    return {'oo_min': max(d, 0), 'oo_max': (v + d) // 2,
            'cc_min': max(-d, 0), 'cc_max': (v - d) // 2,
            't_min': (v - abs(d)) % 2, 't_max': v - abs(d)}


def reconcile(prior_oi, session_volume, new_oi) -> dict:
    """Full reconciliation record: {label, delta, volume, bounds, rule_version}."""
    out = {'label': 'INCONCLUSIVE', 'delta': None, 'volume': session_volume, 'bounds': None,
           'rule_version': RULE_VERSION}
    if new_oi is None or prior_oi is None or session_volume is None or session_volume < 0:
        return out
    delta = int(new_oi) - int(prior_oi)
    out['delta'] = delta
    bounds = oi_bounds(session_volume, delta)
    if bounds is None:
        out['label'] = 'RECONCILE_REQUIRED'
        return out
    out['bounds'] = bounds
    if delta <= 0:
        out['label'] = 'OPENING_WEAKENED' if session_volume > 0 else 'INCONCLUSIVE'
    elif delta >= config.OI_SUPPORT_RATIO * session_volume:
        out['label'] = 'OPENING_SUPPORTED'
    else:
        out['label'] = 'OPENING_PARTIAL'
    return out


def classify_oi_change(prior_oi, session_volume, new_oi) -> str:
    """Label only (see `reconcile`)."""
    return reconcile(prior_oi, session_volume, new_oi)['label']


def record_campaign(path: str, fingerprint: dict) -> None:
    """Append one campaign fingerprint for T+1 review. Swallow errors — research logging is never
    fatal. Stamps the reconciliation rule version so later readers know which rules applied."""
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'rule_version': RULE_VERSION, **fingerprint}, default=str) + '\n')
    except Exception:
        pass


def load_campaigns(path: str) -> list:
    out = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except FileNotFoundError:
        pass
    return out
