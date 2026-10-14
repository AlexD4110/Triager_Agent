from datetime import datetime, timedelta, timezone

import pytest

from app import jobs, monitor, seed, store
from tests.test_worker import Slack, add_message


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("SLACK_TEAM_WEBHOOK_URL", "https://slack.test/team")
    monitor._last_sent.clear()
    monitor.COOLDOWN_SECONDS.update(stalled_queue=900, silence=3600, model_errors=3600)


NOW = datetime.now(timezone.utc)


def ago(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat()


def add_result(n, fallback=None, minutes_ago=1):
    add_message(f"m{n}", "15555550107", f"text {n}")
    with store.connect() as c:
        mid = c.execute("SELECT id FROM messages WHERE wamid = ?", (f"m{n}",)).fetchone()[0]
        msg = {"id": mid, "received_at": ago(minutes_ago)}
        jobs.save_result(c, msg, {"category": None if fallback else "general_question", "fallback": fallback},
                         "P2", 240)
        c.execute("UPDATE triage_results SET created_at = ? WHERE message_id = ?", (ago(minutes_ago), mid))
        c.execute("UPDATE jobs SET status = 'done' WHERE message_id = ?", (mid,))


def live(host="mira", on=True):
    with store.connect() as c:
        seed.set_live(c, host, on)


def run():
    slack = Slack()
    with store.connect() as c:
        sent = monitor.check(c, slack, now=NOW)
    return sent, slack


def test_quiet_system_raises_nothing():
    sent, slack = run()
    assert sent == [] and not slack.sent


def test_stalled_queue_alerts_once_then_waits_for_cooldown(monkeypatch):
    add_message("s1", "15555550107", "hello")
    with store.connect() as c:
        c.execute("UPDATE jobs SET created_at = ?", (ago(10),))
    sent, slack = run()
    assert sent == ["stalled_queue"] and "[system]" in slack.sent[0][1] and "10 min" in slack.sent[0][1]
    assert run()[0] == []  # inside the cooldown


def test_fresh_job_is_not_a_stall():
    add_message("s2", "15555550107", "hello")
    assert run()[0] == []


def test_silence_only_while_a_host_is_live():
    add_result(1, minutes_ago=40)
    assert run()[0] == []  # nobody live: quiet is normal
    live("mira", True)
    sent, slack = run()
    assert sent == ["silence"] and "15 minutes" in slack.sent[0][1]


def test_recent_traffic_prevents_silence_alert():
    live("mira", True)
    add_result(1, minutes_ago=2)
    assert run()[0] == []


def test_silence_alert_when_a_host_is_live_and_nothing_ever_arrived():
    live("lena", True)
    assert run()[0] == ["silence"]


def test_error_rate_needs_enough_samples_and_a_rate_over_five_percent():
    for n in range(8):
        add_result(n, "model_down" if n < 4 else None)
    assert run()[0] == []  # only 8 results: too few to judge
    for n in range(8, 20):
        add_result(n)  # 4 failures of 20 = 20%
    sent, slack = run()
    assert sent == ["model_errors"] and "20%" in slack.sent[0][1]


def test_low_error_rate_is_fine():
    for n in range(40):
        add_result(n, "parse_failed" if n == 0 else None)  # 1 of 40 = 2.5%
    assert run()[0] == []


def test_recovery_resets_the_cooldown():
    live("mira", True)
    assert run()[0] == ["silence"]
    add_result(1, minutes_ago=1)
    assert run()[0] == []  # recovered, state cleared
    with store.connect() as c:
        c.execute("UPDATE triage_results SET created_at = ?", (ago(40),))
    assert run()[0] == ["silence"]  # alerts again right away, not after an hour


def test_worker_monitor_failure_never_crashes_the_worker(monkeypatch):
    from app import worker
    monkeypatch.setattr(monitor, "check", lambda conn: (_ for _ in ()).throw(RuntimeError("boom")))
    worker.run_monitor()
