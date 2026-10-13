import json
from types import SimpleNamespace

from triage.classify import build_system_prompt, classify, parse_output
from triage.config import Settings

SETTINGS = Settings("small", "big", 0.6)


def good(category="payment_issue", confidence=0.9, **kw):
    return json.dumps({"category": category, "safety_flag": False, "security_flag": False,
                       "churn_signal": False, "mentions_host": None, "language": "en",
                       "summary": "s", "confidence": confidence, **kw})


class Stub:
    """Fake client: returns queued replies (strings) or raises queued exceptions, recording calls."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=item)])


def test_parses_fenced_and_think_output():
    out = parse_output("<think>hmm</think>```json\n" + good() + "\n```")
    assert out.category == "payment_issue"


def test_noise_skips_model():
    stub = Stub()
    res = classify("🔥🔥🔥", client=stub, settings=SETTINGS)
    assert res["category"] == "noise" and not stub.calls


def test_rule_flag_survives_model_denial():
    res = classify("tell that creator to watch her back", client=Stub(good("host_conduct")), settings=SETTINGS)
    assert res["safety_flag"] is True and res["category"] == "host_conduct"


def test_model_can_add_flag():
    res = classify("a normal looking message", client=Stub(good("churn_risk", safety_flag=True)), settings=SETTINGS)
    assert res["safety_flag"] is True


def test_retry_once_then_parse_failed():
    stub = Stub("nonsense", "still nonsense")
    res = classify("got charged twice", client=stub, settings=SETTINGS)
    assert res["fallback"] == "parse_failed" and len(stub.calls) == 2


def test_retry_recovers():
    res = classify("got charged twice", client=Stub("nonsense", good()), settings=SETTINGS)
    assert res["fallback"] is None and res["category"] == "payment_issue"


def test_low_confidence_escalates_then_flags():
    stub = Stub(good(confidence=0.3), good(confidence=0.4))
    res = classify("got charged twice", client=stub, settings=SETTINGS)
    assert [c["model"] for c in stub.calls] == ["small", "big"]
    assert res["fallback"] == "low_confidence"


def test_low_confidence_escalation_fixes_it():
    res = classify("got charged twice", client=Stub(good(confidence=0.3), good(confidence=0.9)), settings=SETTINGS)
    assert res["fallback"] is None


def test_model_down_keeps_rule_flags():
    stub = Stub(RuntimeError("down"), RuntimeError("down"))
    res = classify("my account got hacked", client=stub, settings=SETTINGS)
    assert res["fallback"] == "model_down" and res["security_flag"] is True


def test_primary_down_uses_backup():
    stub = Stub(RuntimeError("down"), good())
    res = classify("got charged twice", client=stub, settings=SETTINGS)
    assert [c["model"] for c in stub.calls] == ["small", "big"]
    assert res["fallback"] is None and res["category"] == "payment_issue"


def test_card_numbers_masked_before_model():
    stub = Stub(good())
    classify("charged on 4111 1111 1111 1111 twice", client=stub, settings=SETTINGS)
    sent = stub.calls[0]["messages"][0]["content"]
    assert "4111" not in sent and "[CARD]" in sent


def test_prompt_lists_all_categories_and_no_priority_output():
    p = build_system_prompt()
    for c in ["safety", "account_security", "noise", "payment_issue"]:
        assert c in p
    assert "Do not return a priority" in p
