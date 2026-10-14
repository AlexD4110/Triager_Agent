"""Retention and deletion, matching what the privacy policy promises (app/policy_pages.py).

    .venv/bin/python -m app.retention status
    .venv/bin/python -m app.retention purge [--apply]           remove message text older than the retention period
    .venv/bin/python -m app.retention delete-sender NUMBER [--apply]   erase one sender's personal data

Both commands only count what they would change unless you pass --apply. The worker runs the purge daily
only when RETENTION_ENABLED=true. What is kept: category, priority, flags, and timing, which carry no text.
What is removed: message text, profile name, the model's summary, and the raw payload copy.
The de-identified real labeled set has no link to a sender, so it is not touched here; it expires on its own.
"""
import hashlib
import hmac
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from app.store import Db, connect
from triage.config import load_dotenv

RETENTION_DAYS = int(os.environ.get("MESSAGE_RETENTION_DAYS", "90"))
EMPTY_PAYLOAD = "{}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def sender_hash(wa_id: str) -> str:
    """Keyed hash, so the log cannot be reversed by trying phone numbers."""
    key = os.environ.get("WHATSAPP_APP_SECRET", "").encode() or b"unset"
    return hmac.new(key, wa_id.encode(), hashlib.sha256).hexdigest()[:20]


def normalize_number(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if not digits:
        raise ValueError("no digits in the number")
    return digits


def purge_old(conn: Db, days: int = RETENTION_DAYS, apply: bool = False, now: datetime | None = None) -> dict[str, int]:
    """Removes text and names from messages older than `days`, the model's summary for them, the raw payload
    copies, and old correction notes."""
    cutoff = ((now or _now()) - timedelta(days=days)).isoformat()
    counts = {
        "messages": conn.execute("SELECT COUNT(*) FROM messages WHERE received_at < ? AND "
                                 "(text IS NOT NULL OR profile_name IS NOT NULL)", (cutoff,)).fetchone()[0],
        "raw_payloads": conn.execute("SELECT COUNT(*) FROM raw_payloads WHERE received_at < ? AND body <> ?",
                                     (cutoff, EMPTY_PAYLOAD)).fetchone()[0],
        "summaries": conn.execute("SELECT COUNT(*) FROM triage_results WHERE summary IS NOT NULL AND message_id IN "
                                  "(SELECT id FROM messages WHERE received_at < ?)", (cutoff,)).fetchone()[0],
        "correction_notes": conn.execute("SELECT COUNT(*) FROM corrections WHERE note IS NOT NULL AND corrected_at < ?",
                                         (cutoff,)).fetchone()[0],
    }
    if apply:
        conn.execute("UPDATE messages SET text = NULL, profile_name = NULL WHERE received_at < ?", (cutoff,))
        conn.execute("UPDATE raw_payloads SET body = ? WHERE received_at < ?", (EMPTY_PAYLOAD, cutoff))
        conn.execute("UPDATE triage_results SET summary = NULL WHERE message_id IN "
                     "(SELECT id FROM messages WHERE received_at < ?)", (cutoff,))
        conn.execute("UPDATE corrections SET note = NULL WHERE corrected_at < ?", (cutoff,))
    return counts


def delete_sender(conn: Db, number: str, apply: bool = False, requested_at: datetime | None = None) -> dict[str, Any]:
    """Erases one sender's personal data: number, name, text, summaries, raw payload copies, replies,
    corrections, and gifter record. Labels and timing stay, tied only to an anonymous keyed hash."""
    wa_id = normalize_number(number)
    anon = "deleted-" + sender_hash(wa_id)
    ids = "SELECT id FROM messages WHERE wa_from = ?"
    counts = {
        "messages": conn.execute("SELECT COUNT(*) FROM messages WHERE wa_from = ?", (wa_id,)).fetchone()[0],
        "corrections": conn.execute(f"SELECT COUNT(*) FROM corrections WHERE message_id IN ({ids})", (wa_id,)).fetchone()[0],
        "replies": conn.execute("SELECT COUNT(*) FROM replies WHERE wa_from = ?", (wa_id,)).fetchone()[0],
        "gifter_records": conn.execute("SELECT COUNT(*) FROM gifters WHERE wa_id = ?", (wa_id,)).fetchone()[0],
    }
    if apply:
        conn.execute(f"UPDATE raw_payloads SET body = ? WHERE id IN (SELECT raw_payload_id FROM messages WHERE wa_from = ?)",
                     (EMPTY_PAYLOAD, wa_id))
        conn.execute(f"UPDATE triage_results SET summary = NULL, mentions_host = NULL WHERE message_id IN ({ids})", (wa_id,))
        conn.execute(f"DELETE FROM corrections WHERE message_id IN ({ids})", (wa_id,))
        conn.execute("UPDATE messages SET text = NULL, profile_name = NULL, wa_from = ? WHERE wa_from = ?", (anon, wa_id))
        conn.execute("DELETE FROM replies WHERE wa_from = ?", (wa_id,))
        conn.execute("DELETE FROM gifters WHERE wa_id = ?", (wa_id,))
        conn.execute("INSERT INTO deletion_log (sender_hash, requested_at, completed_at, messages_affected) "
                     "VALUES (?, ?, ?, ?)", (anon, (requested_at or _now()).isoformat(), _now().isoformat(), counts["messages"]))
    return counts


def retention_enabled() -> bool:
    return os.environ.get("RETENTION_ENABLED", "false").lower() in ("1", "true", "yes")


def status(conn: Db) -> dict[str, int]:
    return {
        "retention_days": RETENTION_DAYS,
        "would_purge_messages": purge_old(conn)["messages"],
        "deletion_requests_logged": conn.execute("SELECT COUNT(*) FROM deletion_log").fetchone()[0],
    }


def main(argv: list[str]) -> None:
    load_dotenv()
    apply = "--apply" in argv
    args = [a for a in argv if a != "--apply"]
    cmd = args[0] if args else "status"
    mode = "APPLIED" if apply else "dry run, nothing changed (add --apply to do it)"
    with connect() as conn:
        if cmd == "purge":
            print(f"purge older than {RETENTION_DAYS} days [{mode}]:", purge_old(conn, apply=apply))
        elif cmd == "delete-sender" and len(args) == 2:
            print(f"delete sender [{mode}]:", delete_sender(conn, args[1], apply=apply))
        else:
            print("status:", status(conn))


if __name__ == "__main__":
    main(sys.argv[1:])
