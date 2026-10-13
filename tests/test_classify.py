import json
from triage.classify import build_system_prompt, classify, parse_output
from triage.config import Settings
from triage.qwen import Reply

SETTINGS = Settings("small", "big", 0.6)


def good(category="payment_issue", confidence=0.9, **kw):
    return json.dumps({"category": category, "safety_flag": False, "security_flag": False,
                       "churn_signal": False, "mentions_host": None, "language": "en",
                       "summary": "s", "confidence": confidence, **kw})


class Stub:
    """Fake client: queued replies (JSON strings, None for an empty reply) or exceptions, recording calls."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def complete(self, model, system, user, max_tokens=2000, thinking=None):
        self.calls.append({"model": model, "system": system, "user": user, "max_tokens": max_tokens,
                           "thinking": thinking})
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return Reply(text=item or "", finish_reason="stop" if item else "length", prompt_tokens=10,
                     output_tokens=7, reasoning_tokens=0, seconds=0.0)


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


def test_unparseable_every_time_tries_primary_again_then_backup_then_parse_failed():
    stub = Stub("nonsense", "still nonsense", "nope")
    res = classify("got charged twice", client=stub, settings=SETTINGS)
    assert res["fallback"] == "parse_failed" and [c["model"] for c in stub.calls] == ["small", "small", "big"]


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
    sent = stub.calls[0]["user"]
    assert "4111" not in sent and "[CARD]" in sent


def test_prompt_lists_all_categories_and_no_priority_output():
    p = build_system_prompt()
    for c in ["safety", "account_security", "noise", "payment_issue"]:
        assert c in p
    assert "Do not return a priority" in p


HISTORY = {"recent_messages": ["Some days I think everyone would be better without me"], "host_live": None}


def test_empty_reply_is_retried_without_sender_history():
    stub = Stub(None, good("gift_failed_live"))  # None = reply with no text block
    res = classify("my gift never showed", HISTORY, client=stub, settings=SETTINGS)
    first, second = (c["user"] for c in stub.calls)
    assert "better without me" in first and "better without me" not in second
    assert res["fallback"] is None and res["category"] == "gift_failed_live"


def test_empty_primary_twice_then_backup_succeeds():
    stub = Stub(None, None, good("gift_failed_live"))
    res = classify("my gift never showed", HISTORY, client=stub, settings=SETTINGS)
    assert [c["model"] for c in stub.calls] == ["small", "small", "big"] and res["fallback"] is None


def test_all_empty_is_model_empty_not_parse_failed(caplog):
    stub = Stub(None, None, None)
    with caplog.at_level("WARNING", logger="classify"):
        res = classify("my gift never showed", HISTORY, client=stub, settings=SETTINGS)
    assert res["fallback"] == "model_empty"
    assert "finish_reason=length" in caplog.text and "better without me" not in caplog.text


def test_model_empty_keeps_rule_flags_and_priority_floor():
    from triage.prioritize import prioritize
    flagged = classify("im 15 and my gift never showed", HISTORY, client=Stub(None, None, None), settings=SETTINGS)
    assert flagged["fallback"] == "model_empty" and prioritize(flagged, None, None)[0] == "P0"
    plain = classify("my gift never showed", HISTORY, client=Stub(None, None, None), settings=SETTINGS)
    assert prioritize(plain, None, None)[0] == "P1"


def test_unreachable_primary_goes_straight_to_backup():
    stub = Stub(RuntimeError("down"), good())
    res = classify("my gift never showed", HISTORY, client=stub, settings=SETTINGS)
    assert [c["model"] for c in stub.calls] == ["small", "big"] and res["fallback"] is None


def test_failed_low_confidence_recheck_keeps_first_answer():
    stub = Stub(good(confidence=0.3), RuntimeError("down"))
    res = classify("got charged twice", client=stub, settings=SETTINGS)
    assert res["category"] == "payment_issue" and res["fallback"] == "low_confidence"


def test_thinking_mode_is_sent_per_model():
    stub = Stub(good(confidence=0.3), good())
    settings = Settings("small", "big", 0.6, thinking_mode="off", backup_thinking_mode="budget", thinking_budget=64)
    classify("got charged twice", client=stub, settings=settings)
    assert stub.calls[0]["thinking"] == {"enable_thinking": False}
    assert stub.calls[1]["thinking"] == {"enable_thinking": True, "thinking_budget": 64}
