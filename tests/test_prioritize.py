from triage.prioritize import prioritize


def r(category, **kw):
    return {"category": category, "safety_flag": False, "security_flag": False, "mentions_host": None,
            "fallback": None, **kw}


def test_base_priorities():
    assert prioritize(r("payment_issue"), None, None) == ("P1", 30)
    assert prioritize(r("general_question"), None, None) == ("P2", 240)
    assert prioritize(r("noise"), None, None) == ("P3", 1440)
    assert prioritize(r("account_security"), None, None) == ("P0", 5)


def test_modifier_top_tier_bumps_p2_to_p1():
    assert prioritize(r("general_question"), {"tier": "top"}, None) == ("P1", 15)


def test_modifier_top_tier_shortens_p1_deadline():
    assert prioritize(r("payment_issue"), {"tier": "top"}, None) == ("P1", 15)


def test_modifier_live_vip_request_to_p1():
    res = r("vip_request", mentions_host="Mira")
    assert prioritize(res, None, {"mira": True})[0] == "P1"
    assert prioritize(res, None, {"mira": False})[0] == "P2"


def test_modifier_live_gift_failed_ten_minute_deadline():
    res = r("gift_failed_live", mentions_host="Mira")
    assert prioritize(res, None, {"mira": True}) == ("P1", 10)
    assert prioritize(res, None, {}) == ("P1", 30)


def test_modifier_repeat_sender_moves_up_one_level():
    assert prioritize(r("general_question"), {"unreplied_last_10_min": 3}, None)[0] == "P1"
    assert prioritize(r("noise"), {"unreplied_last_10_min": 3}, None)[0] == "P2"
    assert prioritize(r("general_question"), {"unreplied_last_10_min": 2}, None)[0] == "P2"


def test_safety_floor_overrides_category():
    assert prioritize(r("noise", safety_flag=True), None, None) == ("P0", 5)
    assert prioritize(r("positive_feedback", security_flag=True), None, None)[0] == "P0"


def test_ceiling_modifiers_never_reach_p0():
    gifter = {"tier": "top", "unreplied_last_10_min": 9}
    assert prioritize(r("payment_issue", mentions_host="x"), gifter, {"x": True})[0] == "P1"
    assert prioritize(r("vip_request", mentions_host="x"), gifter, {"x": True})[0] == "P1"


def test_fallbacks():
    assert prioritize(r(None, fallback="parse_failed"), None, None)[0] == "P1"
    assert prioritize(r(None, fallback="model_down"), None, None)[0] == "P2"
    assert prioritize(r("payment_issue", fallback="low_confidence"), None, None)[0] == "P2"
