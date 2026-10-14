import json
from datetime import datetime, timedelta, timezone

import pytest

from app import jobs, queue, seed, store, worker
from tests.test_worker import Model, Slack, add_message, label, SETTINGS
from triage.config import ROOT


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_P0_WEBHOOK_URL", "https://slack.test/p0")
    monkeypatch.setenv("SLACK_TEAM_WEBHOOK_URL", "https://slack.test/team")
    monkeypatch.setattr(worker, "_last_notice", 0.0)
    with store.connect() as c:
        seed.load_gifters(c, ROOT / "data" / "mock_gifters.csv")
        seed.load_live_status(c, ROOT / "data" / "mock_live_status.csv")


def triage(wamid, sender, text, category, hours_ago=0.0):
    add_message(wamid, sender, text)
    if hours_ago:
        old = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
        with store.connect() as c:
            c.execute("UPDATE messages SET received_at = ? WHERE wamid = ?", (old, wamid))
    assert worker.run_one(Model(label(category)), SETTINGS, Slack())


def items(**kw):
    with store.connect() as c:
        return queue.fetch_queue(c, **kw)


def test_sorted_by_priority_then_deadline():
    triage("a", "15555550107", "what time is the stream", "general_question")      # P2
    triage("b", "15555550109", "got charged twice", "payment_issue")               # P1
    triage("c", "15555550108", "my account got hacked", "account_security")        # P0
    triage("d", "15555550110", "great stream", "positive_feedback")                # P3
    assert [i["priority"] for i in items()] == ["P0", "P1", "P2", "P3"]


def test_overdue_is_flagged_and_counted():
    triage("old", "15555550107", "got charged twice", "payment_issue", hours_ago=2)  # P1, 30 min target
    triage("new", "15555550109", "got charged twice", "payment_issue")
    got = {i["text"]: i for i in items()}
    overdue = [i for i in items() if i["overdue"]]
    assert len(overdue) == 1 and overdue[0]["minutes_left"] < 0
    assert queue.stats(items())["overdue"] == 1 and got


def test_mark_replied_hides_the_senders_items_and_can_be_shown():
    triage("r1", "15555550107", "got charged twice", "payment_issue")
    triage("r2", "15555550109", "what time is the stream", "general_question")
    with store.connect() as c:
        queue.mark_replied(c, "15555550107", "tester")
    assert [i["wa_from"] for i in items()] == ["15555550109"]
    shown = items(include_replied=True)
    assert [i["replied"] for i in shown] == [False, True]  # open first, replied last


def test_message_after_a_reply_is_open_again():
    triage("m1", "15555550107", "got charged twice", "payment_issue")
    with store.connect() as c:
        queue.mark_replied(c, "15555550107")
    triage("m2", "15555550107", "still waiting", "payment_issue")
    assert [i["text"] for i in items()] == ["still waiting"]


def test_card_numbers_are_masked_on_screen():
    triage("c1", "15555550107", "charged on 4111 1111 1111 1111 twice", "payment_issue")
    assert "4111" not in items()[0]["text_display"] and "[CARD]" in items()[0]["text_display"]


def test_correction_saved_replaced_and_validated():
    triage("x1", "15555550107", "what time is the stream", "general_question")
    mid = items()[0]["message_id"]
    with store.connect() as c:
        queue.save_correction(c, mid, "vip_request", "P1", "wanted a shoutout", "tester")
        queue.save_correction(c, mid, "payment_issue", "P1", "actually payment", "tester")
        rows = c.execute("SELECT original_category, corrected_category, note FROM corrections").fetchall()
        with pytest.raises(ValueError):
            queue.save_correction(c, mid, "not_a_category", "P1")
        with pytest.raises(ValueError):
            queue.save_correction(c, mid, "noise", "P9")
    assert rows == [("general_question", "payment_issue", "actually payment")]
    assert items()[0]["corrected_category"] == "payment_issue"


def test_repeat_sender_three_in_ten_minutes_lifts_priority():
    # P2 questions from a standard-tier sender: the 3rd unreplied message in 10 minutes becomes P1
    for n in range(3):
        add_message(f"rep{n}", "15555550107", f"question {n}")
    model = Model(*[label("general_question")] * 3)
    for _ in range(3):
        worker.run_one(model, SETTINGS, Slack())
    prios = {i["text"]: i["priority"] for i in items()}
    assert prios == {"question 0": "P2", "question 1": "P2", "question 2": "P1"}


def test_mark_replied_resets_the_repeat_count():
    for n in range(2):
        add_message(f"rs{n}", "15555550107", f"question {n}")
    model = Model(*[label("general_question")] * 4)
    worker.run_one(model, SETTINGS, Slack())
    worker.run_one(model, SETTINGS, Slack())
    with store.connect() as c:
        queue.mark_replied(c, "15555550107")
    add_message("rs2", "15555550107", "question 2")
    worker.run_one(model, SETTINGS, Slack())
    with store.connect() as c:
        last = c.execute("SELECT priority FROM triage_results ORDER BY id DESC LIMIT 1").fetchone()[0]
        n = jobs.unreplied_recent_count(c, "15555550107", datetime.now(timezone.utc).isoformat())
    assert last == "P2" and n == 1  # only the message after the reply counts


def test_repeat_count_ignores_messages_older_than_ten_minutes():
    add_message("o1", "15555550107", "old one")
    add_message("o2", "15555550107", "old two")
    old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    with store.connect() as c:
        c.execute("UPDATE messages SET received_at = ? WHERE wamid IN ('o1', 'o2')", (old,))
    add_message("o3", "15555550107", "new")
    with store.connect() as c:
        row = c.execute("SELECT received_at FROM messages WHERE wamid = 'o3'").fetchone()[0]
        assert jobs.unreplied_recent_count(c, "15555550107", row) == 1


def test_dashboard_script_runs_and_buttons_work():
    from streamlit.testing.v1 import AppTest
    triage("ui1", "15555550107", "got charged twice", "payment_issue")
    at = AppTest.from_file(str(ROOT / "dashboard" / "app.py"), default_timeout=30).run()
    assert not at.exception
    assert any("payment_issue" in m.value for m in at.markdown)
    reply = [b for b in at.button if b.label == "Mark replied"][0]
    reply.click().run()
    assert not at.exception
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM replies").fetchone()[0] == 1
    assert not [b for b in at.button if b.label == "Mark replied"]  # item left the queue
