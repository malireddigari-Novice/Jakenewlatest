"""Shared identities and small helpers for the campaign-flow policy.

A contract is a dict: {ticker, right ('C'|'P'), strike (float), expiry ('YYYY-MM-DD'), adj ('' when the
series is standard), multiplier (100 standard), occ}. Every timestamp the policy reads is an epoch float
(seconds, UTC) produced from a timezone-aware datetime; New York calendar logic lives in `calendar_ny`.
"""
import hashlib
import json


def series_key(c: dict) -> tuple:
    """Exact option-series identity (§3): ticker, right, strike, expiration and adjustment identity."""
    return (c['ticker'], c['right'], round(float(c['strike']), 4), str(c['expiry']), c.get('adj') or '')


def occ(ticker: str, expiry: str, right: str, strike: float) -> str:
    y, m, d = str(expiry).split('-')
    return f"{ticker}{y[2:]}{m}{d}{right}{int(round(float(strike) * 1000)):08d}"


def contract(ticker, right, strike, expiry, adj='', multiplier=100) -> dict:
    return {'ticker': ticker, 'right': right, 'strike': float(strike), 'expiry': str(expiry),
            'adj': adj or '', 'multiplier': multiplier, 'occ': occ(ticker, expiry, right, strike)}


def is_adjusted(c: dict) -> bool:
    return bool(c.get('adj')) or int(c.get('multiplier') or 100) != 100


def stable_id(*parts) -> str:
    return hashlib.sha256('|'.join(json.dumps(p, sort_keys=True, default=str) for p in parts)
                          .encode()).hexdigest()[:20]


def window_id(w: dict) -> str:
    return stable_id('win', series_key(w['contract']), w['start'], w['end'])


def direction_right(direction: str) -> str:
    return 'C' if direction == 'BULLISH' else 'P'


def opposite(direction: str) -> str:
    return 'BEARISH' if direction == 'BULLISH' else 'BULLISH'
