"""Slack alerts. P0 goes to the #p0-alerts channel with @channel, P1 to the team channel.

Alerts carry the model's one-line summary, never the raw message text, so Slack holds as little as
possible. Slack incoming webhooks are one HTTP POST each (standard library only).
"""
import json
import os
import urllib.request
from datetime import datetime
from typing import Any, Callable

Poster = Callable[[str, str], None]
P0_ENV, TEAM_ENV, BUILDER_ENV = "SLACK_P0_WEBHOOK_URL", "SLACK_TEAM_WEBHOOK_URL", "SLACK_BUILDER_WEBHOOK_URL"
TEAM_MENTION = "<!here>"  # webhooks cannot target one person without a Slack user ID


def post_slack(url: str, text: str) -> None:
    req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Slack returned {resp.status}")


def route(priority: str) -> tuple[str, str] | None:
    """Returns (webhook env var, mention) for an alertable priority, else None (P2 and P3 only queue)."""
    return {"P0": (P0_ENV, "<!channel>"), "P1": (TEAM_ENV, TEAM_MENTION)}.get(priority)


def format_alert(row: dict[str, Any]) -> str:
    mention = route(row["priority"])[1]
    due = datetime.fromisoformat(row["due_at"]).strftime("%H:%M UTC")
    who = row.get("profile_name") or "unknown sender"
    note = f" [{row['fallback']}]" if row.get("fallback") else ""
    return (f"{mention} *{row['priority']}* {row.get('category') or 'unlabeled'}{note} from {who}: "
            f"{row.get('summary') or 'needs a human look'}. Respond within {row['deadline_minutes']} min (by {due}).")


def send_alert(row: dict[str, Any], poster: Poster = post_slack) -> tuple[str, str | None]:
    """Returns ('sent'|'none'|'failed', error). Never raises: alerting must not break triage."""
    target = route(row["priority"])
    if not target:
        return "none", None
    url = os.environ.get(target[0], "")
    if not url:
        return "failed", f"{target[0]} is not set"
    try:
        poster(url, format_alert(row))
        return "sent", None
    except Exception as exc:  # network error, bad URL, Slack outage
        return "failed", f"{type(exc).__name__}: {exc}"[:300]


def send_builder_notice(text: str, poster: Poster = post_slack) -> None:
    """System notices (model unreachable). Uses the builder webhook, else the team one. Best effort."""
    url = os.environ.get(BUILDER_ENV) or os.environ.get(TEAM_ENV, "")
    if url:
        try:
            poster(url, f"[system] {text}")
        except Exception:
            pass
