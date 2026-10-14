import sqlite3

import pytest

from app import queue, realset, seed, store, worker
from tests.test_queue import SETTINGS, Model, Slack, add_message, label, triage  # noqa: F401  (fixtures)
from tests.test_queue import env  # noqa: F401
from triage.config import ROOT


def correct(wamid, category="payment_issue", priority="P1", note="", name="Dana Smith"):
    with store.connect() as c:
        mid = c.execute("SELECT id FROM messages WHERE wamid = ?", (wamid,)).fetchone()[0]
        queue.save_correction(c, mid, category, priority, note)


def real_rows():
    with store.connect() as c:
        return c.execute("SELECT text_deid, category, priority, status FROM real_labeled_set ORDER BY id").fetchall()


def test_build_deidentifies_and_never_links_back():
    add_message("r1", "15555550107", "Dana here, charged twice on 4111 1111 1111 1111, Mira ignored it",
                name="Dana Smith")
    assert worker.run_one(Model(label("payment_issue")), SETTINGS, Slack())
    correct("r1", note="customer phone is 555-0100, call her")
    with store.connect() as c:
        counts = realset.build_candidates(c)
    assert counts == {"added": 1, "duplicate": 0, "skipped_no_text": 0}
    (text, cat, pri, status), = real_rows()
    assert text == "[NAME] here, charged twice on [CARD], [HOST] ignored it"
    assert (cat, pri, status) == ("payment_issue", "P1", "pending_review")
    with store.connect() as c:  # nothing identifying is stored in the real set row at all
        cols = [r[1] for r in c.execute("PRAGMA table_info(real_labeled_set)").fetchall()]
        stored = " ".join(str(v) for v in c.execute("SELECT * FROM real_labeled_set").fetchone())
    assert not {"message_id", "wa_from", "profile_name", "note"} & set(cols)
    assert "555-0100" not in stored and "Dana" not in stored and "15555550107" not in stored


def test_build_is_idempotent_and_dedups_identical_text():
    add_message("d1", "15555550107", "gift never showed")
    add_message("d2", "15555550109", "gift never showed")
    model = Model(label("gift_failed_live"), label("gift_failed_live"))
    worker.run_one(model, SETTINGS, Slack()); worker.run_one(model, SETTINGS, Slack())
    correct("d1", "gift_failed_live"); correct("d2", "gift_failed_live")
    with store.connect() as c:
        first = realset.build_candidates(c)
        second = realset.build_candidates(c)
    assert first == {"added": 1, "duplicate": 1, "skipped_no_text": 0}
    assert second == {"added": 0, "duplicate": 0, "skipped_no_text": 0}
    assert len(real_rows()) == 1


def test_non_text_messages_are_skipped():
    add_message("n1", "15555550107", None, kind="image")
    worker.run_one(Model(), SETTINGS, Slack())
    correct("n1", "general_question", "P2")
    with store.connect() as c:
        assert realset.build_candidates(c)["skipped_no_text"] == 1
    assert real_rows() == []


def test_only_approved_rows_are_used_for_scoring():
    add_message("a1", "15555550107", "got charged twice")
    add_message("a2", "15555550109", "refund me please")
    model = Model(label("payment_issue"), label("payment_issue"))
    worker.run_one(model, SETTINGS, Slack()); worker.run_one(model, SETTINGS, Slack())
    correct("a1"); correct("a2")
    with store.connect() as c:
        realset.build_candidates(c)
        assert realset.approved(c) == []  # pending rows never count
        ids = [r["id"] for r in realset.pending(c)]
        realset.review(c, ids[0], True, reviewer="tester")
        realset.review(c, ids[1], False, reviewer="tester")
        got = realset.approved(c)
    assert [r["message"] for r in got] == ["got charged twice"]
    assert got[0]["expected_priority"] == "P1" and got[0]["category"] == "payment_issue"


def test_review_edit_is_scrubbed_again_and_validated():
    add_message("e1", "15555550107", "charged twice")
    worker.run_one(Model(label("payment_issue")), SETTINGS, Slack())
    correct("e1")
    with store.connect() as c:
        realset.build_candidates(c)
        rid = realset.pending(c)[0]["id"]
        realset.review(c, rid, True, "reviewer typed jane@example.com by mistake", "payment_issue", "P1")
        assert realset.approved(c)[0]["message"] == "reviewer typed [EMAIL] by mistake"
        with pytest.raises(ValueError):
            realset.review(c, rid, True, "ok", "bogus_category", "P1")
        with pytest.raises(ValueError):
            realset.review(c, rid, True, "   ")
        with pytest.raises(ValueError):
            realset.review(c, 9999, True)


def test_expired_rows_are_not_used_and_can_be_purged():
    add_message("x1", "15555550107", "charged twice")
    worker.run_one(Model(label("payment_issue")), SETTINGS, Slack())
    correct("x1")
    with store.connect() as c:
        realset.build_candidates(c)
        realset.review(c, realset.pending(c)[0]["id"], True)
        c.execute("UPDATE real_labeled_set SET expires_at = '2000-01-01T00:00:00+00:00'")
        assert realset.approved(c) == []
        assert realset.purge_expired(c) == 1 and realset.status_counts(c) == {}


def test_review_page_runs_and_approve_button_works():
    from streamlit.testing.v1 import AppTest
    add_message("p1", "15555550107", "Dana here, charged twice", name="Dana Smith")
    worker.run_one(Model(label("payment_issue")), SETTINGS, Slack())
    correct("p1")
    with store.connect() as c:
        realset.build_candidates(c)
    at = AppTest.from_file(str(ROOT / "dashboard" / "pages" / "1_Real_set_review.py"), default_timeout=30).run()
    assert not at.exception
    assert at.text_area[0].value == "[NAME] here, charged twice"  # original name never reaches the page
    [b for b in at.button if b.label == "Approve"][0].click().run()
    assert not at.exception
    with store.connect() as c:
        assert [r["message"] for r in [dict(message=x["message"]) for x in realset.approved(c)]] == \
            ["[NAME] here, charged twice"]
