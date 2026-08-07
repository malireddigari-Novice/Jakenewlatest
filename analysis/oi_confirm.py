"""
T+1 campaign confirmation via next-day open interest (new-spec) — pure classifier + JSONL store.

Today we only observe transactions and infer intent. Tomorrow's OI is the retrospective ground
truth: if today's big volume became NEW open interest, the engine correctly detected a position
being established; if OI did not rise (or fell), the volume was likely closing / churn.

Flow:
  • On an entry, `record_campaign()` stores the fingerprint — prior_OI, today_volume, fresh premium,
    call/put control, strike cluster.
  • Next session, once OI is available (Schwab), `classify_oi_change()` labels each prior campaign:
    NEW_POSITION_CONFIRMED / PARTIALLY_CONFIRMED / LIKELY_CLOSING_CHURN / INCONCLUSIVE.
Over time this becomes labelled training evidence for the real-time inference. Needs Schwab OI
(currently off) to fetch next-day OI; the classifier + store are ready for when it is on.
"""
import json


def classify_oi_change(prior_oi, today_volume, new_oi) -> str:
    """How much of today's volume became new open interest overnight."""
    if new_oi is None or prior_oi is None or not today_volume or today_volume <= 0:
        return 'INCONCLUSIVE'
    delta = new_oi - prior_oi
    ratio = delta / today_volume
    if ratio >= 0.50:
        return 'NEW_POSITION_CONFIRMED'          # most of the volume stuck as new OI
    if ratio >= 0.15:
        return 'PARTIALLY_CONFIRMED'
    if delta <= 0:
        return 'LIKELY_CLOSING_CHURN'            # OI flat/down despite big volume → closing
    return 'INCONCLUSIVE'


def record_campaign(path: str, fingerprint: dict) -> None:
    """Append one campaign fingerprint (date, symbol, side, strike, cluster, prior_oi, today_volume,
    fresh_premium, control) for T+1 review. Swallow errors — research logging is never fatal."""
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(fingerprint, default=str) + '\n')
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
