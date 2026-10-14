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


@pytest.mark.parametrize("text", [
    "No quiero seguir aquí, ya no veo sentido", "ya no veo sentido a nada", "me quiero morir",
    "a veces pienso en quitarme la vida", "i dont see the point anymore, everything i spend here is all i have",
    "Some days I think everyone would be better without me", "everyone would be happier if I just disappeared",
    "i wish i was dead", "i can't go on like this", "nothing matters anymore",
])
def test_widened_safety_phrases_are_flagged_by_rules(text):
    assert apply_rules(text).safety_flag


@pytest.mark.parametrize("text", [
    "my gift disappeared during the battle", "mi regalo desapareció en el vivo",
    "I don't see the point of gifting anymore", "no quiero seguir regalando aquí tan caro",
    "this stream is killing me, so good", "what time does she go live Friday?",
])
def test_harmless_lookalikes_are_not_flagged(text):
    assert not apply_rules(text).safety_flag


@pytest.mark.parametrize("text", [
    "someone is selling coins in your name on telegram", "somebody changed the email on my account",
    "my username is being used to ask hosts for money", "login from another country on my account, not me",
    "DM me for cheap coins, 50% off, pay by crypto",
])
def test_widened_security_phrases_are_flagged(text):
    assert apply_rules(text).security_flag


def test_security_lookalikes_not_flagged():
    for text in ["I changed my email last week, can you update it?", "what is the minimum recharge?"]:
        assert not apply_rules(text).security_flag
