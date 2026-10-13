import pytest

from triage.rules import apply_rules, mask_cards


@pytest.mark.parametrize("text", ["🔥🔥🔥", "ok", "?", "...", "hi"])
def test_noise(text):
    assert apply_rules(text).is_noise


@pytest.mark.parametrize("text", [
    "I will find you and your team", "im 15 can you give me the badge", "i feel like ending it",
    "tell that creator to watch her back", "he said he'd show up at her house",
])
def test_safety_flags(text):
    assert apply_rules(text).safety_flag


@pytest.mark.parametrize("text", [
    "my account got hacked", "they asked for my verification code", "a scam account is DMing me",
    "ayuda me hackearon la cuenta",
])
def test_security_flags(text):
    assert apply_rules(text).security_flag


def test_clean_message_has_no_flags():
    r = apply_rules("what time does she go live Friday?")
    assert not (r.is_noise or r.safety_flag or r.security_flag)


def test_chargeback_is_not_a_p0_flag():
    r = apply_rules("refund me or I do a chargeback")
    assert not (r.safety_flag or r.security_flag)


def test_mask_cards():
    assert mask_cards("card 4111 1111 1111 1111 failed") == "card [CARD] failed"
    assert mask_cards("card ending in 4242") == "card ending in 4242"
