"""
Tiny JSON-file state store so a restart doesn't lose track of a live position.

The attention board's velocity history is intentionally NOT persisted — after a restart it
rebuilds during the warm-up window. Only the open position, per-symbol cooldowns, and daily
flags need to survive, and those are small enough for a single JSON file.
"""
import json
import logging
import os

import config

logger = logging.getLogger(__name__)

_DEFAULT = {'positions': [], 'cooldowns': {}, 'day': None, 'eod_done': None}


def _migrate(data: dict) -> dict:
    """Carry a v1 single 'position' forward into the v2 'positions' list."""
    if 'positions' not in data:
        pos = data.pop('position', None)
        data['positions'] = [pos] if pos else []
    return data


def load() -> dict:
    try:
        if os.path.exists(config.STATE_FILE):
            with open(config.STATE_FILE, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            return _migrate({**_DEFAULT, **data})
    except Exception as exc:
        logger.warning("state: load failed (%s) — starting fresh", exc)
    return dict(_DEFAULT)


def save(state: dict) -> None:
    try:
        tmp = config.STATE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(state, fh, indent=2, default=str)
        os.replace(tmp, config.STATE_FILE)
    except Exception as exc:
        logger.warning("state: save failed: %s", exc)
