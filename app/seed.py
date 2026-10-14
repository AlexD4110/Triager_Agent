"""Loads the mock gifter tiers and live status, and flips a host live or off.

    python -m app.seed                  load data/mock_gifters.csv and data/mock_live_status.csv
    python -m app.seed live mira on     mark a host live (or off)
    python -m app.seed tier 15551234567 top "Display Name"   add or change one gifter
All data in the mock files is synthetic.
"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.store import Db, connect
from triage.config import ROOT, load_dotenv


def upsert_gifter(conn: Db, wa_id: str, name: str, tier: str, hosts: str) -> None:
    conn.execute(
        "INSERT INTO gifters (wa_id, name, tier, hosts) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (wa_id) DO UPDATE SET name = excluded.name, tier = excluded.tier, hosts = excluded.hosts",
        (wa_id, name, tier, hosts))


def set_live(conn: Db, host: str, is_live: bool) -> None:
    conn.execute(
        "INSERT INTO live_status (host, is_live, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT (host) DO UPDATE SET is_live = excluded.is_live, updated_at = excluded.updated_at",
        (host.strip().lstrip("@").lower(), int(is_live), datetime.now(timezone.utc).isoformat()))


def load_gifters(conn: Db, path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        upsert_gifter(conn, r["wa_id"], r["name"], r["tier"], r["hosts"].replace(";", ","))
    return len(rows)


def load_live_status(conn: Db, path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        set_live(conn, r["host"], r["is_live"] == "1")
    return len(rows)


def main(argv: list[str]) -> None:
    load_dotenv()
    with connect() as conn:
        if argv[:1] == ["live"] and len(argv) == 3:
            set_live(conn, argv[1], argv[2].lower() in ("on", "1", "true"))
            print(f"{argv[1]} live = {argv[2]}")
        elif argv[:1] == ["tier"] and len(argv) >= 3:
            upsert_gifter(conn, argv[1], argv[3] if len(argv) > 3 else "", argv[2], "")
            print(f"{argv[1]} tier = {argv[2]}")
        else:
            print("gifters loaded:", load_gifters(conn, ROOT / "data" / "mock_gifters.csv"))
            print("hosts loaded:", load_live_status(conn, ROOT / "data" / "mock_live_status.csv"))


if __name__ == "__main__":
    main(sys.argv[1:])
