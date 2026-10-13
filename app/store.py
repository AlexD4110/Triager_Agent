"""Storage for the webhook: raw payloads, messages, and the jobs queue.

Uses Supabase Postgres when DATABASE_URL is set, otherwise SQLite for local dev. The Postgres tables
come from sql/schema.sql (run once in Supabase); SQLite tables are created on first use.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from triage.config import ROOT

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_payloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    signature_ok INTEGER NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wamid TEXT NOT NULL UNIQUE,
    wa_from TEXT NOT NULL,
    profile_name TEXT,
    group_id TEXT,
    msg_type TEXT NOT NULL,
    text TEXT,
    sent_at TEXT,
    received_at TEXT NOT NULL,
    raw_payload_id INTEGER NOT NULL REFERENCES raw_payloads(id)
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL UNIQUE REFERENCES messages(id),
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL
);
"""


def db_path() -> Path:
    return ROOT / os.environ.get("SQLITE_PATH", "data/triage.db")


def database_url() -> str:
    """The Postgres URL, or an empty string for SQLite. A leftover placeholder password is an error."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if "[YOUR-PASSWORD]" in url:
        raise RuntimeError("DATABASE_URL still contains [YOUR-PASSWORD]; put the real database password in .env")
    return url


class Db:
    """One connection with one interface for both backends. SQL is written with ? placeholders."""

    def __init__(self, url: str):
        self.postgres = bool(url)
        if self.postgres:
            import psycopg
            self.conn = psycopg.connect(url)
        else:
            path = db_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(path)
            self.conn.executescript(SQLITE_SCHEMA)

    def execute(self, sql: str, params: tuple = ()) -> Any:
        if self.postgres:
            sql = sql.replace("?", "%s")
        return self.conn.execute(sql, params)

    def __enter__(self) -> "Db":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type:
                self.conn.rollback()
            else:
                self.conn.commit()
        finally:
            self.conn.close()


def connect() -> Db:
    return Db(database_url())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pulls inbound messages out of a Meta webhook payload. Status updates are skipped."""
    found: list[dict[str, Any]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            for m in value.get("messages", []):
                if not m.get("id") or not m.get("from"):
                    continue
                kind = m.get("type", "unknown")
                body = m.get(kind, {}) if isinstance(m.get(kind), dict) else {}
                ts = m.get("timestamp")
                found.append({
                    "wamid": m["id"], "wa_from": m["from"], "profile_name": names.get(m["from"]),
                    "group_id": m.get("group_id"), "msg_type": kind,
                    "text": body.get("body") or body.get("caption"),
                    "sent_at": datetime.fromtimestamp(int(ts), timezone.utc).isoformat() if ts else None,
                })
    return found


def save_raw(body: bytes, signature_ok: bool) -> int:
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO raw_payloads (received_at, signature_ok, body) VALUES (?, ?, ?) RETURNING id",
            (_now(), int(signature_ok), body.decode("utf-8", errors="replace").replace("\x00", "")),
        ).fetchone()
        return int(row[0])


def save_messages(raw_id: int, payload: dict[str, Any]) -> int:
    """Inserts new messages and one job each. A wamid seen before is ignored. Returns new count."""
    new = 0
    with connect() as conn:
        for m in extract_messages(payload):
            row = conn.execute(
                "INSERT INTO messages (wamid, wa_from, profile_name, group_id, msg_type, text,"
                " sent_at, received_at, raw_payload_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (wamid) DO NOTHING RETURNING id",
                (m["wamid"], m["wa_from"], m["profile_name"], m["group_id"], m["msg_type"], m["text"],
                 m["sent_at"], _now(), raw_id),
            ).fetchone()
            if row:
                conn.execute("INSERT INTO jobs (message_id, created_at) VALUES (?, ?)", (row[0], _now()))
                new += 1
    return new


def parse_json(body: bytes) -> dict[str, Any] | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
