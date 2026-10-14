"""Database operations for the worker: claiming jobs, building context, saving results, alert state."""
from datetime import datetime, timedelta, timezone
from typing import Any

from app.store import Db

MAX_JOB_ATTEMPTS = 3
MAX_ALERT_ATTEMPTS = 5
STALE_MINUTES = 5
SAFETY_HISTORY_HOURS = 24


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_all(cursor: Any) -> list[dict[str, Any]]:
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def claim_job(conn: Db) -> dict[str, Any] | None:
    """Atomically takes the oldest new job. Postgres uses SKIP LOCKED so several workers never collide."""
    lock = " FOR UPDATE SKIP LOCKED" if conn.postgres else ""
    now = _now()
    row = conn.execute(
        "UPDATE jobs SET status = 'processing', attempts = attempts + 1, updated_at = ?"
        " WHERE id = (SELECT id FROM jobs WHERE status = 'new' ORDER BY id LIMIT 1" + lock + ")"
        " RETURNING id, message_id, attempts",
        (now,),
    ).fetchone()
    return {"id": row[0], "message_id": row[1], "attempts": row[2]} if row else None


def requeue_stale(conn: Db) -> int:
    """Jobs stuck in 'processing' (worker crashed) go back to 'new'."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES)).isoformat()
    cur = conn.execute(
        "UPDATE jobs SET status = 'new', updated_at = ? WHERE status = 'processing' AND updated_at < ?",
        (_now(), cutoff),
    )
    return cur.rowcount


def finish_job(conn: Db, job_id: int, status: str, error: str | None = None) -> None:
    conn.execute("UPDATE jobs SET status = ?, last_error = ?, updated_at = ? WHERE id = ?",
                 (status, error, _now(), job_id))


def fail_or_retry(conn: Db, job: dict[str, Any], error: str) -> str:
    """A crashed job goes back to 'new' until it has used its attempts, then becomes 'failed'."""
    status = "new" if job["attempts"] < MAX_JOB_ATTEMPTS else "failed"
    finish_job(conn, job["id"], status, error[:500])
    return status


def load_message(conn: Db, message_id: int) -> dict[str, Any]:
    cur = conn.execute("SELECT id, wa_from, profile_name, msg_type, text, received_at FROM messages WHERE id = ?",
                       (message_id,))
    return fetch_all(cur)[0]


def recent_texts(conn: Db, wa_from: str, before_id: int, limit: int = 3) -> list[str]:
    """The sender's last few earlier messages, oldest first. Context for the model only."""
    cur = conn.execute(
        "SELECT text FROM messages WHERE wa_from = ? AND id < ? AND text IS NOT NULL ORDER BY id DESC LIMIT ?",
        (wa_from, before_id, limit),
    )
    return [r[0] for r in reversed(cur.fetchall())]


def has_recent_safety_flag(conn: Db, wa_from: str, before_id: int, hours: int = SAFETY_HISTORY_HOURS) -> bool:
    """True if this sender had an earlier message flagged for safety (rule or model flag, or the safety
    category) within `hours`. Results that were themselves fallbacks never count, so a history flag cannot
    keep passing itself along."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    row = conn.execute(
        "SELECT 1 FROM triage_results r JOIN messages m ON m.id = r.message_id"
        " WHERE m.wa_from = ? AND m.id < ? AND m.received_at >= ? AND r.fallback IS NULL"
        " AND (r.safety_flag = 1 OR r.category = 'safety') LIMIT 1",
        (wa_from, before_id, cutoff),
    ).fetchone()
    return row is not None


def unreplied_recent_count(conn: Db, wa_from: str, anchor_iso: str, minutes: int = 10) -> int:
    """Messages from this sender in the `minutes` up to and including `anchor_iso`, counting only those
    that arrived after the last time a person marked the sender as replied. Drives the repeat-sender
    modifier: receive-only code cannot see WhatsApp replies, so the dashboard's Mark replied button
    is the signal."""
    anchor = datetime.fromisoformat(anchor_iso)
    cutoff = (anchor - timedelta(minutes=minutes)).isoformat()
    last_reply = conn.execute("SELECT MAX(replied_at) FROM replies WHERE wa_from = ?", (wa_from,)).fetchone()[0]
    since = max(cutoff, last_reply) if last_reply else cutoff
    row = conn.execute("SELECT COUNT(*) FROM messages WHERE wa_from = ? AND received_at > ? AND received_at <= ?",
                       (wa_from, since, anchor_iso)).fetchone()
    return int(row[0])


def get_gifter(conn: Db, wa_id: str) -> dict[str, Any] | None:
    rows = fetch_all(conn.execute("SELECT wa_id, name, tier, hosts FROM gifters WHERE wa_id = ?", (wa_id,)))
    return rows[0] if rows else None


def live_map(conn: Db) -> dict[str, bool]:
    return {host: bool(is_live) for host, is_live in conn.execute("SELECT host, is_live FROM live_status").fetchall()}


def save_result(conn: Db, message: dict[str, Any], result: dict[str, Any], priority: str,
                deadline: int) -> tuple[int, str]:
    """Stores the triage result and returns (result id, due_at). due_at counts from when the message arrived.
    The id is 0 when this message already has a result (a retried job)."""
    received = datetime.fromisoformat(message["received_at"])
    due_at = (received + timedelta(minutes=deadline)).isoformat()
    row = conn.execute(
        "INSERT INTO triage_results (message_id, category, safety_flag, security_flag, churn_signal,"
        " mentions_host, language, summary, confidence, fallback, priority, deadline_minutes, due_at, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (message_id) DO NOTHING RETURNING id",
        (message["id"], result.get("category"), int(bool(result.get("safety_flag"))),
         int(bool(result.get("security_flag"))), int(bool(result.get("churn_signal"))),
         result.get("mentions_host"), result.get("language"), result.get("summary"), result.get("confidence"),
         result.get("fallback"), priority, deadline, due_at, _now()),
    ).fetchone()
    return (int(row[0]) if row else 0), due_at


def set_alert(conn: Db, result_id: int, status: str, error: str | None = None) -> None:
    conn.execute("UPDATE triage_results SET alert_status = ?, alert_error = ?,"
                 " alert_attempts = alert_attempts + 1 WHERE id = ?", (status, error, result_id))


def mark_no_alert(conn: Db, result_id: int) -> None:
    conn.execute("UPDATE triage_results SET alert_status = 'none' WHERE id = ?", (result_id,))


def alerts_to_retry(conn: Db, limit: int = 20) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT r.id AS result_id, r.priority, r.category, r.summary, r.deadline_minutes, r.due_at,"
        " r.fallback, m.profile_name FROM triage_results r JOIN messages m ON m.id = r.message_id"
        " WHERE r.alert_status = 'failed' AND r.alert_attempts < ? ORDER BY r.id LIMIT ?",
        (MAX_ALERT_ATTEMPTS, limit),
    )
    return fetch_all(cur)
