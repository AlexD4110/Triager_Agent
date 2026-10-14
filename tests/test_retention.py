from datetime import datetime, timedelta, timezone

import pytest

from app import policy_pages, queue, retention, seed, store, worker
from tests.test_queue import triage
from tests.test_worker import Model, Slack, add_message, label, SETTINGS
from tests.test_queue import env  # noqa: F401  (autouse fixture: tmp database, mock gifters)
from triage.config import ROOT


def age(wamid, days):
    old = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with store.connect() as c:
        c.execute("UPDATE messages SET received_at = ? WHERE wamid = ?", (old, wamid))
        c.execute("UPDATE raw_payloads SET received_at = ? WHERE id IN "
                  "(SELECT raw_payload_id FROM messages WHERE wamid = ?)", (old, wamid))


def row(wamid):
    with store.connect() as c:
        return c.execute("SELECT m.text, m.profile_name, m.wa_from, r.category, r.priority, r.summary, p.body "
                         "FROM messages m JOIN triage_results r ON r.message_id = m.id "
                         "JOIN raw_payloads p ON p.id = m.raw_payload_id WHERE m.wamid = ?", (wamid,)).fetchone()


def test_policy_page_and_code_agree_on_retention():
    assert retention.RETENTION_DAYS == policy_pages.RETENTION_DAYS == 90


def test_purge_dry_run_changes_nothing_then_apply_removes_text_but_keeps_labels():
    triage("old", "15555550107", "got charged twice", "payment_issue")
    triage("new", "15555550109", "refund please", "payment_issue")
    age("old", 120)
    before = row("old")
    with store.connect() as c:
        dry = retention.purge_old(c)
    assert dry == {"messages": 1, "raw_payloads": 1, "summaries": 1, "correction_notes": 0}
    assert row("old") == before  # dry run: untouched
    with store.connect() as c:
        retention.purge_old(c, apply=True)
    text, name, wa_from, category, priority, summary, body = row("old")
    assert (text, name, summary, body) == (None, None, None, "{}")
    assert (category, priority, wa_from) == ("payment_issue", "P1", "15555550107")  # labels and timing stay
    assert row("new")[0] == "refund please"  # recent message untouched
    with store.connect() as c:
        assert retention.purge_old(c, apply=True)["messages"] == 0  # idempotent


def test_old_correction_notes_are_cleared():
    triage("n1", "15555550107", "hello there", "general_question")
    age("n1", 5)
    with store.connect() as c:
        mid = c.execute("SELECT id FROM messages").fetchone()[0]
        queue.save_correction(c, mid, "vip_request", "P2", "caller said her number is 555-0100")
        c.execute("UPDATE corrections SET corrected_at = ?", ((datetime.now(timezone.utc) - timedelta(days=200)).isoformat(),))
        assert retention.purge_old(c, apply=True)["correction_notes"] == 1
        assert c.execute("SELECT note FROM corrections").fetchone()[0] is None


def test_delete_sender_erases_that_sender_only():
    triage("a1", "15555550107", "got charged twice", "payment_issue")
    triage("a2", "15555550107", "still waiting", "payment_issue")
    triage("b1", "15555550109", "other person's message", "general_question")
    with store.connect() as c:
        mid = c.execute("SELECT id FROM messages WHERE wamid = 'a1'").fetchone()[0]
        queue.save_correction(c, mid, "vip_request", "P2")
        queue.mark_replied(c, "15555550107")
        dry = retention.delete_sender(c, "+1 (555) 555-0107")
        assert dry == {"messages": 2, "corrections": 1, "replies": 1, "gifter_records": 1}
        assert c.execute("SELECT COUNT(*) FROM deletion_log").fetchone()[0] == 0  # dry run logs nothing
        retention.delete_sender(c, "15555550107", apply=True)
        assert retention.delete_sender(c, "15555550107", apply=True)["messages"] == 0  # already gone
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM messages WHERE wa_from = '15555550107'").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM messages WHERE text IS NOT NULL").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM gifters WHERE wa_id = '15555550107'").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM replies").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM corrections").fetchone()[0] == 0
        log = c.execute("SELECT sender_hash, messages_affected FROM deletion_log").fetchall()
        everything = " ".join(str(v) for r in c.execute("SELECT * FROM messages").fetchall() for v in r)
    assert len(log) == 2 and log[0][1] == 2  # the repeat call logged a zero-message request
    assert "15555550107" not in str(log) and "15555550107" not in everything
    assert row("b1")[0] == "other person's message"  # the other sender is untouched
    assert row("a1")[3:5] == ("payment_issue", "P1")  # labels stay for statistics


def test_normalize_number():
    assert retention.normalize_number("+1 (555) 555-0107") == "15555550107"
    with pytest.raises(ValueError):
        retention.normalize_number("call me")


def test_automatic_purge_is_off_unless_enabled(monkeypatch):
    triage("auto", "15555550107", "got charged twice", "payment_issue")
    age("auto", 400)
    monkeypatch.delenv("RETENTION_ENABLED", raising=False)
    worker.run_retention()
    assert row("auto")[0] == "got charged twice"
    monkeypatch.setenv("RETENTION_ENABLED", "true")
    worker.run_retention()
    assert row("auto")[0] is None


def test_command_line_defaults_to_dry_run(capsys):
    triage("cli", "15555550107", "got charged twice", "payment_issue")
    age("cli", 400)
    retention.main(["purge"])
    assert "dry run" in capsys.readouterr().out and row("cli")[0] == "got charged twice"
    retention.main(["purge", "--apply"])
    assert row("cli")[0] is None
