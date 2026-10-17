"""
Pinned, REVIEWED Alpaca/OPRA trade-condition map (flow handoff §3).

Source: GET data.alpaca.markets/v1beta1/options/meta/conditions/trade, fetched 2026-10-17, and checked
against real NVDA prints from 2026-10-16 (I, a, f, g, S, j, e, n observed). Alpaca reports ONE letter
per options trade (not numeric IDs). Tags describe EXECUTION MECHANICS, never customer intent, and can
coexist. `drift()` compares a live fetch against the pin so a provider change is detected, not guessed.

Only ORDINARY ELECTRONIC single-leg prints (I = AUTO, S = ISO) may receive a quote-side reading; every
auction / cross / floor / complex / stock-tied / late / cancel / unknown print leaves the side UNKNOWN.
"""
COND_MAP_VERSION = 'alpaca-opra-cond-2026-10-17'

# Provider mnemonic at pin time — compared against a live fetch to detect drift.
PROVIDER_TEXT = {
    'A': 'CANC', 'B': 'OSEQ', 'C': 'CNCL', 'D': 'LATE', 'E': 'CNCO', 'F': 'OPEN', 'G': 'CNOL',
    'H': 'OPNL', 'I': 'AUTO', 'J': 'REOP', 'S': 'ISOI', 'a': 'SLAN', 'b': 'SLAI', 'c': 'SLCN',
    'd': 'SCLI', 'e': 'SLFT', 'f': 'MLET', 'g': 'MLAT', 'h': 'MLCT', 'i': 'MLFT', 'j': 'MESL',
    'k': 'TLAT', 'l': 'MASL', 'm': 'MFSL', 'n': 'TLET', 'o': 'TLCT', 'p': 'TLFT', 'q': 'TESL',
    'r': 'TASL', 's': 'TFSL', 't': 'CBMO', 'u': 'MCTP', 'v': 'EXHT',
}

_TAGS = {
    'I': {'ELECTRONIC'},
    'S': {'ELECTRONIC', 'ISO'},          # reviewed sweep MECHANISM (one leg of a possible sweep)
    'a': {'AUCTION'}, 'b': {'AUCTION', 'ISO'},
    'c': {'CROSS'}, 'd': {'CROSS', 'ISO'},
    'e': {'FLOOR'},
    'f': {'COMPLEX', 'ELECTRONIC'}, 'j': {'COMPLEX', 'ELECTRONIC'},
    'g': {'COMPLEX', 'AUCTION'}, 'l': {'COMPLEX', 'AUCTION'},
    'h': {'COMPLEX', 'CROSS'},
    'i': {'COMPLEX', 'FLOOR'}, 'm': {'COMPLEX', 'FLOOR'}, 't': {'COMPLEX', 'FLOOR'},
    'k': {'STOCK_TIED', 'COMPLEX', 'AUCTION'}, 'r': {'STOCK_TIED', 'COMPLEX', 'AUCTION'},
    'n': {'STOCK_TIED', 'COMPLEX', 'ELECTRONIC'}, 'q': {'STOCK_TIED', 'COMPLEX', 'ELECTRONIC'},
    'o': {'STOCK_TIED', 'COMPLEX', 'CROSS'},
    'p': {'STOCK_TIED', 'COMPLEX', 'FLOOR'}, 's': {'STOCK_TIED', 'COMPLEX', 'FLOOR'},
    'u': {'COMPRESSION'},
    'v': {'EXTENDED_HOURS'},
    'A': {'CANCEL', 'CORRECTION'}, 'C': {'CANCEL', 'CORRECTION'},
    'E': {'CANCEL', 'CORRECTION'}, 'G': {'CANCEL', 'CORRECTION'},
    'B': {'LATE'}, 'D': {'LATE'}, 'F': {'LATE', 'OPENING'}, 'H': {'LATE', 'OPENING'},
    'J': {'REOPEN'},
}

_SIDE_BLOCKERS = {'AUCTION', 'CROSS', 'FLOOR', 'COMPLEX', 'STOCK_TIED', 'COMPRESSION', 'EXTENDED_HOURS',
                  'CANCEL', 'CORRECTION', 'LATE', 'REOPEN', 'UNKNOWN'}


def tags(code) -> frozenset:
    """Mechanics tags for one raw condition letter. Unknown/blank → {'UNKNOWN'}."""
    c = (code or '').strip()
    return frozenset(_TAGS.get(c, {'UNKNOWN'}))


def side_eligible(tagset) -> bool:
    """Ordinary electronic single-leg print — the only kind a quote-side reading may be attempted on."""
    return 'ELECTRONIC' in tagset and not (set(tagset) & _SIDE_BLOCKERS)


def is_cancel(tagset) -> bool:
    return 'CANCEL' in tagset


def drift(live: dict) -> list:
    """Letters whose live provider text no longer starts with the pinned mnemonic (or new letters)."""
    out = [k for k, v in (live or {}).items()
           if PROVIDER_TEXT.get(k) is None or not str(v).startswith(PROVIDER_TEXT[k])]
    return sorted(out)
