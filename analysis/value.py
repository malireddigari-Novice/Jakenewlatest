"""
Local-value cheapness + detection-latency diagnosis (follow-up spec §11-12) — pure, I/O-free.

'Distance from session low' is too crude (§21): a bad opening print or a stale quoted low mis-measures
how extended a contract really is. Cheapness should reference LOCAL value — campaign-start premium,
event VWAP, a local pre-event median, or a spread-qualified low.

And a CHASED rejection has two very different meanings that must be told apart (§11):
  • discovered early but EXECUTED late   → MISSED_DUE_TO_DETECTION_LATENCY (a speed problem to fix)
  • not recognized until after expansion → MISSED_DUE_TO_PRICE_EXTENSION (a disciplined, valid reject)

For §12, `notional_reject_label` distinguishes a single-strike shortfall that the cluster/ticker
aggregation would have covered from a genuinely thin event.
"""
import config


def local_value(marks=None, campaign_start=None, event_vwap=None, quoted_low=None):
    """A robust local value reference, preferring campaign-start premium, then event VWAP, then a
    local median of the recent mark series, then a valid quoted low. None if nothing usable."""
    for v in (campaign_start, event_vwap):
        if v and v > 0:
            return float(v)
    m = [float(x[1] if isinstance(x, (tuple, list)) else x)
         for x in (marks or []) if x is not None and (x[1] if isinstance(x, (tuple, list)) else x)]
    if m:
        s = sorted(m)
        return s[len(s) // 2]                     # local median
    if quoted_low and quoted_low > 0:
        return float(quoted_low)
    return None


def extension(mark, ref):
    """mark / local-value reference (how far above local value the premium already is)."""
    if not ref or ref <= 0 or mark is None:
        return 1.0
    return round(float(mark) / float(ref), 3)


def classify_chased(premium_drift):
    """premium_drift = alert_premium / campaign-start premium (PremiumDrift). A large drift means the
    contract was cheap when the campaign was first captured but ran before we acted — a detection
    latency problem — rather than a campaign we only recognised after it had already extended."""
    if premium_drift and premium_drift >= config.CHASED_LATENCY_DRIFT:
        return 'MISSED_DUE_TO_DETECTION_LATENCY'
    return 'MISSED_DUE_TO_PRICE_EXTENSION'


def notional_reject_label(single_notional, cluster_notional, floor):
    """§12 — which aggregation level fell short. If the cluster/ticker mass WOULD have met the floor,
    the miss is an aggregation problem, not a genuinely thin single strike."""
    if (cluster_notional or 0.0) >= floor > (single_notional or 0.0):
        return 'MISSED_DUE_TO_CLUSTER_AGGREGATION'
    return 'MISSED_DUE_TO_SINGLE_STRIKE_NOTIONAL'


def latency_metrics(stamps: dict, premiums: dict, eventual_mfe=None) -> dict:
    """Detection/decision/execution latency + premium drift + convexity-consumed + missed-asymmetry
    (§11-12) from timestamped stages. `stamps` values are epoch seconds; `premiums` are prices, keyed
    first_abnormal / sustained / eligible / accumulation / alert / fill."""
    def dt(a, b):
        ta, tb = stamps.get(a), stamps.get(b)
        return round(tb - ta, 0) if (ta is not None and tb is not None) else None

    def pr(k):
        return premiums.get(k)

    out = {
        'detection_latency_s': dt('sustained', 'alert') if stamps.get('sustained') is not None
        else dt('first_abnormal', 'alert'),
        'decision_latency_s': dt('eligible', 'alert'),
        'execution_latency_s': dt('alert', 'fill'),
        'premium_drift': round(pr('alert') / pr('accumulation'), 3)
        if (pr('alert') and pr('accumulation')) else None,
        'missed_asymmetry': round((pr('fill') or pr('alert') or 0.0) - pr('eligible'), 3)
        if pr('eligible') else None,
    }
    ap, ep = pr('alert'), pr('accumulation')
    out['convexity_consumed_before_alert'] = (round((ap - ep) / (eventual_mfe - ep), 3)
                                              if (eventual_mfe and ap and ep and eventual_mfe > ep)
                                              else None)
    return out
