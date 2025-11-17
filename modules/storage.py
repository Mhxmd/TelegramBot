"""
storage.py – minimal state + anti-spam helper for the marketplace bot

In the new ERD-based architecture, all persistent data (users, products,
orders, wallets, etc.) lives in PostgreSQL via db.py.

This module now only:
- Tracks simple per-user rate limiting (anti-spam)
- Stores transient per-user flow state (e.g. search mode flags)
"""

import time
from collections import defaultdict
from typing import Dict, Any, List

# ----------------------------------------------------------------------
# Public: user_flow_state
# Used by bot.py to store things like "search_mode" flags.
# Example:
#   state = storage.user_flow_state.setdefault(user_id, {})
#   state["search_mode"] = True
# ----------------------------------------------------------------------

user_flow_state: Dict[int, Dict[str, Any]] = {}

# ----------------------------------------------------------------------
# Internal request log for simple rate limiting
# ----------------------------------------------------------------------

_request_log: Dict[int, List[float]] = defaultdict(list)

# default window & max hits (you can tweak these)
_DEFAULT_WINDOW_SECONDS = 5
_DEFAULT_MAX_HITS = 8


def is_spamming(
    user_id: int,
    window_seconds: int = _DEFAULT_WINDOW_SECONDS,
    max_hits: int = _DEFAULT_MAX_HITS,
) -> bool:
    """
    Very simple spam protection:
    - Keeps timestamps of recent actions per user
    - If a user sends more than `max_hits` updates in `window_seconds`, returns True.

    Called in bot.py before handling /start and /shop.
    """
    now = time.time()
    hits = _request_log[user_id]

    # keep only hits within the time window
    hits = [t for t in hits if now - t <= window_seconds]
    hits.append(now)
    _request_log[user_id] = hits

    return len(hits) > max_hits
