"""Queue, mark-replied, and label-correction logic behind the dashboard. The UI in dashboard/app.py is thin."""
from datetime import datetime, timezone
from typing import Any

from app.jobs import fetch_all
from app.store import Db
from triage.config import load_taxonomy
from triage.rules import mask_cards

PRIORITIES = ["P0", "P1", "P2", "P3"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def categories() -> dict[str, str]:
    """{category: base priority} from categories.yaml."""
    return {name: info["base_priority"] for name, info in load_taxonomy().items()}


def fetch_queue(conn: Db, include_replied: bool = False, now: datetime | None = None,
                limit: int = 300) -> list[dict[str, Any]]:
    """Triaged messages sorted by priority, then deadline. Replied items are hidden unless asked for.

    An item counts as replied when a person marked its sender replied after the message arrived.
    """
    now = now or _now()
    cur = conn.execute(
        "SELECT r.id AS result_id, r.message_id, r.category, r.priority, r.deadline_minutes, r.due_at,"
        " r.summary, r.confidence, r.safety_flag, r.security_flag, r.churn_signal, r.fallback,"
        " r.mentions_host, r.alert_status, m.wa_from, m.profile_name, m.text, m.msg_type, m.received_at,"
        " c.corrected_category, c.corrected_priority,"
        " (SELECT MAX(p.replied_at) FROM replies p WHERE p.wa_from = m.wa_from AND p.replied_at >= m.received_at)"
        " AS replied_at"
        " FROM triage_results r JOIN messages m ON m.id = r.message_id"
        " LEFT JOIN corrections c ON c.message_id = r.message_id"
        " ORDER BY r.id DESC LIMIT ?",
        (limit,),
    )
    items = []
    for row in fetch_all(cur):
        row["replied"] = row["replied_at"] is not None
        if row["replied"] and not include_replied:
            continue
        due = datetime.fromisoformat(row["due_at"])
        row["minutes_left"] = round((due - now).total_seconds() / 60)
        row["overdue"] = (not row["replied"]) and row["minutes_left"] < 0
        row["text_display"] = mask_cards(row["text"] or f"[{row['msg_type']} message, no text]")
        items.append(row)
    items.sort(key=lambda r: (r["replied"], PRIORITIES.index(r["priority"]), r["due_at"]))
    return items


def stats(items: list[dict[str, Any]]) -> dict[str, int]:
    open_items = [i for i in items if not i["replied"]]
    out = {p: sum(i["priority"] == p for i in open_items) for p in PRIORITIES}
    out["open"], out["overdue"] = len(open_items), sum(i["overdue"] for i in open_items)
    return out


def mark_replied(conn: Db, wa_from: str, marked_by: str = "dashboard") -> None:
    """A person answered this sender in WhatsApp. Closes their open items and resets the repeat count."""
    conn.execute("INSERT INTO replies (wa_from, replied_at, marked_by) VALUES (?, ?, ?)",
                 (wa_from, _now().isoformat(), marked_by))


def save_correction(conn: Db, message_id: int, category: str, priority: str, note: str = "",
                    corrected_by: str = "dashboard") -> None:
    """Records the right label for a message. One correction per message; saving again replaces it."""
    if category not in categories():
        raise ValueError(f"unknown category: {category}")
    if priority not in PRIORITIES:
        raise ValueError(f"unknown priority: {priority}")
    original = fetch_all(conn.execute(
        "SELECT category, priority FROM triage_results WHERE message_id = ?", (message_id,)))
    if not original:
        raise ValueError(f"message {message_id} has no triage result")
    conn.execute(
        "INSERT INTO corrections (message_id, original_category, original_priority, corrected_category,"
        " corrected_priority, note, corrected_by, corrected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (message_id) DO UPDATE SET corrected_category = excluded.corrected_category,"
        " corrected_priority = excluded.corrected_priority, note = excluded.note,"
        " corrected_by = excluded.corrected_by, corrected_at = excluded.corrected_at, exported_at = NULL",
        (message_id, original[0]["category"], original[0]["priority"], category, priority, note[:500],
         corrected_by, _now().isoformat()))
