"""prioritize(result, gifter, live_status) -> (priority, deadline). Plain code; the model never sets priority.

gifter: {"tier": "top" | other, "unreplied_last_10_min": int}
live_status: {host name: True when that host is live}; host names match ignoring case and a leading @
deadline: minutes the team has to respond.
"""
from typing import Any, Mapping

from triage.config import load_taxonomy

LEVELS = ["P0", "P1", "P2", "P3"]
DEADLINE_MIN = {"P0": 5, "P1": 30, "P2": 240, "P3": 1440}
TOP_P1_DEADLINE = 15
LIVE_GIFT_DEADLINE = 10
REPEAT_THRESHOLD = 3
FALLBACK_PRIORITY = {"parse_failed": "P1", "low_confidence": "P2", "model_down": "P2"}

_BASE = {name: info["base_priority"] for name, info in load_taxonomy().items()}


def _host_key(name: str | None) -> str:
    """Normalizes a host name so 'Mira', 'MIRA', ' @mira ' all match."""
    return (name or "").strip().lstrip("@").strip().lower()


def _up(priority: str) -> str:
    """Moves one level up but never into P0: modifiers cannot reach it."""
    return LEVELS[max(LEVELS.index(priority) - 1, 1)] if priority != "P0" else "P0"


def prioritize(result: Mapping[str, Any], gifter: Mapping[str, Any] | None,
               live_status: Mapping[str, bool] | None) -> tuple[str, int]:
    gifter, live_status = gifter or {}, live_status or {}
    if result.get("safety_flag") or result.get("security_flag"):
        return "P0", DEADLINE_MIN["P0"]  # safety floor

    category = result.get("category")
    fallback = result.get("fallback")
    if category in _BASE and _BASE[category] == "P0":
        return "P0", DEADLINE_MIN["P0"]
    if category not in _BASE:
        priority = FALLBACK_PRIORITY.get(fallback or "", "P2")
    elif fallback == "low_confidence":
        priority = FALLBACK_PRIORITY["low_confidence"]  # needs_human, P2
    else:
        priority = _BASE[category]

    deadline = DEADLINE_MIN[priority]
    live = {_host_key(k): v for k, v in live_status.items()}
    host = _host_key(result.get("mentions_host"))
    host_live = bool(host and live.get(host))

    if gifter.get("tier") == "top":
        if priority == "P2":
            priority = "P1"
            deadline = DEADLINE_MIN["P1"]
        if priority == "P1":
            deadline = min(deadline, TOP_P1_DEADLINE)
    if host_live:
        if category == "vip_request":
            priority = _up(priority) if priority != "P1" else priority
            deadline = min(deadline, DEADLINE_MIN[priority])
        if category == "gift_failed_live":
            deadline = min(deadline, LIVE_GIFT_DEADLINE)
    if int(gifter.get("unreplied_last_10_min", 0)) >= REPEAT_THRESHOLD:
        new = _up(priority)
        if new != priority:
            priority, deadline = new, min(deadline, DEADLINE_MIN[new])
    return priority, deadline
