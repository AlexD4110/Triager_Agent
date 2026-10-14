"""Health checks run by the worker every minute. Alerts go to the builder Slack webhook (else the team one).

1. stalled_queue: jobs waiting too long, so the worker is down or stuck. Not in the spec; added because a
   stuck worker silently breaks the 5 minute P0 target.
2. silence: nothing triaged for SILENCE_MINUTES while a host is live (SPEC: no messages processed for 15
   minutes during live hours). "Live hours" means at least one host is marked live in live_status.
3. model_errors: more than ERROR_RATE of the last hour's results fell back because the model failed.

Each condition alerts at most once per cooldown so a long outage does not flood Slack.
"""
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from app import alerts
from app.store import Db

STALL_MINUTES = float(os.environ.get("MONITOR_STALL_MINUTES", "3"))
SILENCE_MINUTES = float(os.environ.get("MONITOR_SILENCE_MINUTES", "15"))
ERROR_RATE = float(os.environ.get("MONITOR_ERROR_RATE", "0.05"))
MIN_SAMPLE = 10  # fewer results than this in the window is too few to judge a rate
COOLDOWN_SECONDS = {"stalled_queue": 900, "silence": 3600, "model_errors": 3600}
MODEL_FAILURES = ("parse_failed", "model_empty", "model_down")

_last_sent: dict[str, float] = {}


def _iso(minutes_ago: float, now: datetime) -> str:
    return (now - timedelta(minutes=minutes_ago)).isoformat()


def evaluate(conn: Db, now: datetime | None = None) -> dict[str, str]:
    """Returns {condition: message} for every condition that is currently true. No alerts are sent here."""
    now = now or datetime.now(timezone.utc)
    problems: dict[str, str] = {}

    waiting = conn.execute("SELECT COUNT(*), MIN(created_at) FROM jobs WHERE status = 'new' AND created_at < ?",
                           (_iso(STALL_MINUTES, now),)).fetchone()
    if waiting[0]:
        age = (now - datetime.fromisoformat(waiting[1])).total_seconds() / 60
        problems["stalled_queue"] = (f"{waiting[0]} message(s) have been waiting for triage, the oldest for "
                                     f"{age:.0f} min. The worker may be down or stuck.")

    host_live = conn.execute("SELECT COUNT(*) FROM live_status WHERE is_live = 1").fetchone()[0]
    if host_live:
        latest = conn.execute("SELECT MAX(created_at) FROM triage_results").fetchone()[0]
        if latest is None or latest < _iso(SILENCE_MINUTES, now):
            problems["silence"] = (f"No messages triaged in the last {SILENCE_MINUTES:.0f} minutes while "
                                   f"{host_live} host(s) are live. Check the webhook, Meta subscription, and worker.")

    total, failed = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(CASE WHEN fallback IN (?, ?, ?) THEN 1 ELSE 0 END), 0) "
        "FROM triage_results WHERE created_at >= ?", (*MODEL_FAILURES, _iso(60, now))).fetchone()
    if total >= MIN_SAMPLE and failed / total > ERROR_RATE:
        problems["model_errors"] = (f"{failed} of the last {total} results ({failed / total:.0%}) fell back because "
                                    f"the model failed. Limit is {ERROR_RATE:.0%}.")
    return problems


def check(conn: Db, poster: alerts.Poster = alerts.post_slack, now: datetime | None = None,
          clock: Callable[[], float] = time.time) -> list[str]:
    """Evaluates every condition and sends an alert for each one that is new or past its cooldown."""
    sent = []
    problems = evaluate(conn, now)
    for name in COOLDOWN_SECONDS:
        if name not in problems:
            _last_sent.pop(name, None)  # recovered: the next outage alerts right away
        elif clock() - _last_sent.get(name, 0.0) >= COOLDOWN_SECONDS[name]:
            _last_sent[name] = clock()
            alerts.send_builder_notice(f"{name.replace('_', ' ')}: {problems[name]}", poster)
            sent.append(name)
    return sent
