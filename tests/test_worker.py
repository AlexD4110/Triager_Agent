import json
from types import SimpleNamespace

import pytest

from app import alerts, jobs, seed, store, worker
from triage.config import ROOT, Settings

SETTINGS = Settings("small", "big", 0.6)


class Model:
    """Fake model client: queued replies (JSON strings) or exceptions."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        item = self.replies.pop(0) if self.replies else RuntimeError("no reply queued")
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=item)])


def label(category, confidence=0.9, **kw):
    base = {"category": category, "safety_flag": False, "security_flag": False, "churn_signal": False,
            "mentions_host": None, "language": "en", "summary": "s", "confidence": confidence}
    return json.dumps({**base, **kw})


class Slack:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def __call__(self, url, text):
        if self.fail:
            raise OSError("slack down")
        self.sent.append((url, text))


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("SLACK_P0_WEBHOOK_URL", "https://slack.test/p0")
    monkeypatch.setenv("SLACK_TEAM_WEBHOOK_URL", "https://slack.test/team")
    monkeypatch.setattr(worker, "_last_notice", 0.0)
    with store.connect() as c:
        seed.load_gifters(c, ROOT / "data" / "mock_gifters.csv")
        seed.load_live_status(c, ROOT / "data" / "mock_live_status.csv")


def add_message(wamid, sender, text, kind="text", name="Mock"):
    body = {kind: {"body": text}} if text is not None else {}
    payload = {"entry": [{"changes": [{"field": "messages", "value": {
        "contacts": [{"profile": {"name": name}, "wa_id": sender}],
        "messages": [{"from": sender, "id": wamid, "timestamp": "1749416383", "type": kind, **body}]}}]}]}
    store.save_messages(store.save_raw(json.dumps(payload).encode(), True), payload)


def result_for(wamid):
    with store.connect() as c:
        return jobs.fetch_all(c.execute(
            "SELECT r.*, j.status AS job_status FROM triage_results r JOIN messages m ON m.id = r.message_id"
            " JOIN jobs j ON j.message_id = m.id WHERE m.wamid = ?", (wamid,)))[0]


def run(model, slack=None):
    slack = slack or Slack()
    assert worker.run_one(model, SETTINGS, slack)
    return slack


def test_top_tier_live_failed_gift_is_p1_ten_minutes_and_alerts_team():
    add_message("w1", "15555550101", "my gift never showed, she's live")  # top tier, linked to mira (live)
    slack = run(Model(label("gift_failed_live", mentions_host="Mira")))
    r = result_for("w1")
    assert (r["priority"], r["deadline_minutes"], r["job_status"], r["alert_status"]) == ("P1", 10, "done", "sent")
    assert slack.sent[0][0] == "https://slack.test/team" and "<!here>" in slack.sent[0][1]


def test_host_matching_ignores_case():
    add_message("w2", "15555550107", "gift lost")  # standard tier
    run(Model(label("gift_failed_live", mentions_host="LENA")))  # live_status stores 'lena'
    assert result_for("w2")["deadline_minutes"] == 10


def test_rule_flag_forces_p0_even_if_model_disagrees():
    add_message("w3", "15555550107", "tell that creator to watch her back")
    slack = run(Model(label("host_conduct")))
    r = result_for("w3")
    assert (r["priority"], r["safety_flag"], r["deadline_minutes"]) == ("P0", 1, 5)
    assert slack.sent[0][0] == "https://slack.test/p0" and "<!channel>" in slack.sent[0][1]


def test_alert_has_summary_not_raw_text():
    add_message("w4", "15555550107", "tell that creator to watch her back")
    slack = run(Model(label("host_conduct", summary="Threat toward a host")))
    assert "Threat toward a host" in slack.sent[0][1] and "watch her back" not in slack.sent[0][1]


def test_noise_skips_model_and_gets_no_alert():
    add_message("w5", "15555550107", "🔥🔥🔥")
    model, slack = Model(), Slack()
    run(model, slack)
    r = result_for("w5")
    assert (r["category"], r["priority"], r["alert_status"]) == ("noise", "P3", "none")
    assert not model.calls and not slack.sent


def test_p2_is_queue_only():
    add_message("w6", "15555550109", "what time does she go live friday?")
    slack = run(Model(label("general_question")))
    assert result_for("w6")["priority"] == "P2" and not slack.sent


def test_top_tier_bumps_p2_to_p1_and_alerts():
    add_message("w7", "15555550102", "how do badges work?")
    slack = run(Model(label("general_question")))
    r = result_for("w7")
    assert (r["priority"], r["deadline_minutes"]) == ("P1", 15) and slack.sent


def test_non_text_message_goes_to_a_human_at_p2():
    add_message("w8", "15555550107", None, kind="image")
    model = Model()
    run(model)
    r = result_for("w8")
    assert (r["fallback"], r["priority"], r["category"]) == ("non_text", "P2", None) and not model.calls


def test_sticker_is_noise():
    add_message("w9", "15555550107", None, kind="sticker")
    run(Model())
    assert result_for("w9")["category"] == "noise"


def test_model_down_is_p2_and_notifies_builder_once():
    add_message("w10", "15555550107", "got charged twice")
    add_message("w11", "15555550109", "refund please")
    slack = Slack()
    run(Model(*[RuntimeError("down")] * 4), slack)
    run(Model(*[RuntimeError("down")] * 4), slack)
    assert result_for("w10")["fallback"] == "model_down" and result_for("w10")["priority"] == "P2"
    assert sum(t.startswith("[system]") for _, t in slack.sent) == 1


def test_model_down_still_honours_rule_flags():
    add_message("w12", "15555550107", "my account got hacked")
    run(Model(*[RuntimeError("down")] * 4))
    assert result_for("w12")["priority"] == "P0"


def test_failed_slack_is_recorded_then_retried():
    add_message("w13", "15555550107", "refund me now")
    run(Model(label("payment_issue")), Slack(fail=True))
    assert result_for("w13")["alert_status"] == "failed"
    good = Slack()
    assert worker.retry_alerts(good) == 1
    assert result_for("w13")["alert_status"] == "sent" and len(good.sent) == 1


def test_missing_webhook_url_is_recorded_as_failed(monkeypatch):
    monkeypatch.delenv("SLACK_TEAM_WEBHOOK_URL")
    add_message("w14", "15555550107", "refund me now")
    run(Model(label("payment_issue")))
    r = result_for("w14")
    assert r["alert_status"] == "failed" and "SLACK_TEAM_WEBHOOK_URL" in r["alert_error"]


def test_context_includes_recent_messages_and_host_live():
    add_message("a", "15555550101", "first")
    add_message("b", "15555550101", "second")
    add_message("c", "15555550101", "gift missing")
    model = Model(label("general_question"), label("general_question"), label("gift_failed_live"))
    for _ in range(3):
        run(model)
    prompt = model.calls[2]["messages"][0]["content"]
    assert "- first" in prompt and "- second" in prompt and "Host live now: yes" in prompt


def test_crashing_job_is_retried_then_failed(monkeypatch):
    add_message("w15", "15555550107", "hello there")
    monkeypatch.setattr(worker, "label_message", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    for _ in range(3):
        assert worker.run_one(None, SETTINGS, Slack())
    with store.connect() as c:
        status, attempts, err = c.execute("SELECT status, attempts, last_error FROM jobs").fetchone()
    assert (status, attempts) == ("failed", 3) and "boom" in err
    assert not worker.run_one(None, SETTINGS, Slack())


def test_stale_processing_job_is_requeued():
    add_message("w16", "15555550107", "hello there")
    with store.connect() as c:
        jobs.claim_job(c)
        c.execute("UPDATE jobs SET updated_at = '2000-01-01T00:00:00+00:00'")
    with store.connect() as c:
        assert jobs.requeue_stale(c) == 1
        assert jobs.claim_job(c) is not None


def test_each_message_triaged_once():
    add_message("w17", "15555550107", "hello there")
    run(Model(label("general_question")))
    assert not worker.run_one(Model(), SETTINGS, Slack())
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM triage_results").fetchone()[0] == 1


def test_worker_makes_no_whatsapp_calls():
    src = open(worker.__file__).read() + open(jobs.__file__).read() + open(alerts.__file__).read()
    assert "graph.facebook.com" not in src and "WHATSAPP_ACCESS_TOKEN" not in src
