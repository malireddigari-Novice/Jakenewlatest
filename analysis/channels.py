"""
DTE channels + record provenance (flow handoff §8, §10) — pure, I/O-free.

Every signal is tagged with its New-York-calendar DTE bucket at signal time:
    zero_dte = 0 · weekly = 1–7 · short_term = 8–30 · swing = 31–99 · long_dated = 100+
A multi-expiry structure belongs to the bucket of its EARLIEST still-active expiry.

`stamp()` is the provenance block every derived record carries: schema + ruleset version and the NY
session date, so a stored record is never re-interpreted under later rules or today's data.
"""
from datetime import date

from data import exchange_calendar as xcal

SCHEMA_VERSION = 'jakenew-record-v2'      # v2 = handoff alignment (coverage, DTE bucket, catalyst, versions)
RULESET_VERSION = 'handoff-2026-10-17'    # bump when a gate/label/threshold rule changes meaning

_BUCKETS = ((0, 0, 'zero_dte'), (1, 7, 'weekly'), (8, 30, 'short_term'), (31, 99, 'swing'))


# Retired labels (threshold-fired "CONFIRMED"/"VERIFIED" overclaimed what public flow can show) →
# their replacement. Stored records keep their original text; readers map through this.
LEGACY_LABELS = {
    'OPPOSITE_SIDE_CAMPAIGN_CONFIRMED': 'OPPOSITE_SIDE_CAMPAIGN_SUSTAINED',
    'REVERSAL_CLUSTER_CONFIRMED':       'REVERSAL_CLUSTER_SUSTAINED',
    'ATTENTION_CONFIRMED':              'ATTENTION_SUSTAINED',
    'VERIFIED_DISTRIBUTION':            'SUSTAINED_DISTRIBUTION',
    'NEW_POSITION_CONFIRMED':           'OPENING_SUPPORTED',
    'PARTIALLY_CONFIRMED':              'OPENING_PARTIAL',
    'LIKELY_CLOSING_CHURN':             'OPENING_WEAKENED',
}


def current_label(label):
    return LEGACY_LABELS.get(label, label)


def dte_ny(expiry, now) -> int | None:
    """Days to expiry counted in New York calendar days at `now` (aware datetime)."""
    if expiry is None or now is None:
        return None
    exp = expiry if isinstance(expiry, date) else date.fromisoformat(str(expiry)[:10])
    return (exp - xcal.ny_date(now)).days


def dte_bucket(dte) -> str:
    if dte is None or dte < 0:
        return 'UNKNOWN'
    for lo, hi, name in _BUCKETS:
        if lo <= dte <= hi:
            return name
    return 'long_dated'


def home_bucket(expiries, now) -> str:
    """Bucket of the earliest still-active expiry of a (possibly multi-expiry) structure."""
    live = [d for d in (dte_ny(e, now) for e in expiries or []) if d is not None and d >= 0]
    return dte_bucket(min(live)) if live else 'UNKNOWN'


def stamp(now) -> dict:
    return {'schema_version': SCHEMA_VERSION, 'ruleset_version': RULESET_VERSION,
            'ny_session': xcal.ny_date(now).isoformat() if now is not None else None}
