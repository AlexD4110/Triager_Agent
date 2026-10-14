"""The real labeled set: de-identified examples built from human corrections, kept in the private database.

    .venv/bin/python -m app.realset build      weekly: de-identify new corrections into pending rows
    .venv/bin/python -m app.realset purge      delete rows past their expiry
    .venv/bin/python -m app.realset status     counts by status

Flow: a person corrects a label in the dashboard, `build` de-identifies the message and stores it as
pending_review with no link back to the message, sender, or time of day, and a person approves or edits it
on the dashboard's review page. Only approved rows are ever used to score the classifier. This set is kept
apart from the synthetic evaluation set on purpose.
"""
import hashlib
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from app.jobs import fetch_all
from app.queue import PRIORITIES, categories
from app.store import Db, connect
from triage.config import load_dotenv
from triage.deidentify import deidentify, residual_flags

RETENTION_DAYS = int(os.environ.get("REAL_SET_RETENTION_DAYS", "365"))
MIN_ROWS_FOR_STABLE_SCORE = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def text_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()


def build_candidates(conn: Db) -> dict[str, int]:
    """De-identifies corrections that have not been processed yet. The sender's name and every known host
    name are scrubbed. The correction's free-text note is never copied. Returns counts."""
    hosts = [r[0] for r in conn.execute("SELECT host FROM live_status").fetchall()]
    cur = conn.execute(
        "SELECT c.id AS correction_id, c.corrected_category, c.corrected_priority, m.text, m.profile_name,"
        " r.mentions_host FROM corrections c JOIN messages m ON m.id = c.message_id"
        " LEFT JOIN triage_results r ON r.message_id = c.message_id WHERE c.exported_at IS NULL")
    counts = {"added": 0, "duplicate": 0, "skipped_no_text": 0}
    now = _now()
    week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    for row in fetch_all(cur):
        if (row["text"] or "").strip():
            res = deidentify(row["text"], [row["profile_name"]], hosts + [row["mentions_host"]])
            inserted = conn.execute(
                "INSERT INTO real_labeled_set (text_deid, text_hash, category, priority, residual, created_week,"
                " created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (text_hash) DO NOTHING"
                " RETURNING id",
                (res.text, text_hash(res.text), row["corrected_category"], row["corrected_priority"],
                 "; ".join(res.residual), week, now.isoformat(),
                 (now + timedelta(days=RETENTION_DAYS)).isoformat())).fetchone()
            counts["added" if inserted else "duplicate"] += 1
        else:
            counts["skipped_no_text"] += 1
        conn.execute("UPDATE corrections SET exported_at = ? WHERE id = ?", (now.isoformat(), row["correction_id"]))
    return counts


def pending(conn: Db) -> list[dict[str, Any]]:
    return fetch_all(conn.execute(
        "SELECT id, text_deid, category, priority, residual, created_week FROM real_labeled_set"
        " WHERE status = 'pending_review' ORDER BY id"))


def review(conn: Db, row_id: int, approve: bool, text: str | None = None, category: str | None = None,
           priority: str | None = None, reviewer: str = "dashboard") -> None:
    """Approve (optionally with an edited text and label) or reject. Edited text is scrubbed of anything
    pattern-detectable again, so a reviewer cannot accidentally paste personal details back in."""
    current = fetch_all(conn.execute("SELECT text_deid, category, priority FROM real_labeled_set WHERE id = ?", (row_id,)))
    if not current:
        raise ValueError(f"no such row: {row_id}")
    new_text = deidentify(text).text if text is not None else current[0]["text_deid"]
    new_cat, new_pri = category or current[0]["category"], priority or current[0]["priority"]
    if new_cat not in categories() or new_pri not in PRIORITIES:
        raise ValueError("unknown category or priority")
    if not new_text.strip():
        raise ValueError("text is empty")
    conn.execute(
        "UPDATE real_labeled_set SET text_deid = ?, text_hash = ?, category = ?, priority = ?, status = ?,"
        " residual = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
        (new_text, text_hash(new_text), new_cat, new_pri, "approved" if approve else "rejected",
         "; ".join(residual_flags(new_text)), reviewer, _now().isoformat(), row_id))


def approved(conn: Db) -> list[dict[str, str]]:
    """Approved, unexpired examples shaped like the evaluation rows (message, category, expected_priority)."""
    rows = fetch_all(conn.execute(
        "SELECT text_deid, category, priority FROM real_labeled_set WHERE status = 'approved' AND expires_at > ?"
        " ORDER BY id", (_now().isoformat(),)))
    return [{"message": r["text_deid"], "category": r["category"], "expected_priority": r["priority"]} for r in rows]


def purge_expired(conn: Db) -> int:
    return conn.execute("DELETE FROM real_labeled_set WHERE expires_at <= ?", (_now().isoformat(),)).rowcount


def status_counts(conn: Db) -> dict[str, int]:
    return {s: n for s, n in conn.execute("SELECT status, COUNT(*) FROM real_labeled_set GROUP BY status").fetchall()}


def main(argv: list[str]) -> None:
    load_dotenv()
    cmd = argv[0] if argv else "status"
    with connect() as conn:
        if cmd == "build":
            print("build:", build_candidates(conn))
        elif cmd == "purge":
            print("purged:", purge_expired(conn))
        print("real set:", status_counts(conn))


if __name__ == "__main__":
    main(sys.argv[1:])
