"""Fills a throwaway local database (data/demo.db) with synthetic triaged messages to try the dashboard.

    .venv/bin/python tools/demo_queue.py
    DATABASE_URL= SQLITE_PATH=data/demo.db .venv/bin/streamlit run dashboard/app.py --server.address localhost

Never touches Supabase: it forces SQLite. All names, numbers, and messages are invented.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_URL"] = ""
os.environ["SQLITE_PATH"] = "data/demo.db"

from app import jobs, queue, store  # noqa: E402
from triage.config import ROOT  # noqa: E402

# (sender, name, text, category, priority, deadline minutes, minutes ago received, extra flags)
DEMO = [
    ("15555550201", "Demo Gifter A", "tell that creator to watch her back", "host_conduct", "P0", 5, 40, {"safety_flag": 1}),
    ("15555550202", "Demo Gifter B", "someone is messaging hosts pretending to be me", "account_security", "P0", 5, 2, {"security_flag": 1}),
    ("15555550203", "Demo Gifter C", "sent a rocket to Mira and it never showed, she's live", "gift_failed_live", "P1", 10, 25, {"mentions_host": "Mira"}),
    ("15555550204", "Demo Gifter D", "got charged twice for 7,000 coins", "payment_issue", "P1", 30, 12, {}),
    ("15555550205", "Demo Gifter E", "done gifting here, nobody even said thank you", "churn_risk", "P1", 30, 50, {"churn_signal": 1}),
    ("15555550206", "Demo Gifter F", "can I get a shoutout tonight?", "vip_request", "P2", 240, 90, {}),
    ("15555550207", "Demo Gifter G", "what time does she go live Friday?", "general_question", "P2", 240, 15, {}),
    ("15555550208", "Demo Gifter H", "charged on 4111 1111 1111 1111 twice", "payment_issue", "P1", 30, 5, {}),
    ("15555550209", "Demo Gifter I", "last night's stream was amazing", "positive_feedback", "P3", 1440, 300, {}),
    ("15555550210", "Demo Gifter J", "[unreadable voice note]", None, "P2", 240, 8, {"fallback": "non_text"}),
]


def main() -> None:
    db = ROOT / "data" / "demo.db"
    db.unlink(missing_ok=True)
    now = datetime.now(timezone.utc)
    for n, (sender, name, text, category, priority, deadline, ago, extra) in enumerate(DEMO, 1):
        received = (now - timedelta(minutes=ago)).isoformat()
        payload = {"entry": [{"changes": [{"field": "messages", "value": {
            "contacts": [{"profile": {"name": name}, "wa_id": sender}],
            "messages": [{"from": sender, "id": f"demo.{n}", "timestamp": "1749416383", "type": "text",
                          "text": {"body": text}}]}}]}]}
        store.save_messages(store.save_raw(json.dumps(payload).encode(), True), payload)
        with store.connect() as c:
            message = jobs.fetch_all(c.execute("SELECT id, received_at FROM messages WHERE wamid = ?", (f"demo.{n}",)))[0]
            c.execute("UPDATE messages SET received_at = ? WHERE id = ?", (received, message["id"]))
            message["received_at"] = received
            result = {"category": category, "summary": f"Demo summary for {category or 'unlabeled'}", "confidence": 0.9,
                      "safety_flag": 0, "security_flag": 0, "churn_signal": 0, "mentions_host": None,
                      "language": "en", "fallback": None, **extra}
            jobs.save_result(c, message, result, priority, deadline)
            jobs.finish_job(c, 1, "done")
    with store.connect() as c:
        queue.mark_replied(c, "15555550209", "demo")  # one already-replied item to show the toggle
    print(f"Demo database ready at {db}\nRun the dashboard against it with:\n"
          "  DATABASE_URL= SQLITE_PATH=data/demo.db .venv/bin/streamlit run dashboard/app.py --server.address localhost")


if __name__ == "__main__":
    main()
