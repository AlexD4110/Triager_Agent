import pytest

from triage.deidentify import deidentify, name_tokens, residual_flags


@pytest.mark.parametrize("raw, expected", [
    ("email me at jane.doe@example.com please", "email me at [EMAIL] please"),
    ("see https://example.com/pay?id=9 now", "see [URL] now"),
    ("charged on 4111 1111 1111 1111 twice", "charged on [CARD] twice"),
    ("call +1 (555) 010-2233 tonight", "call [PHONE] tonight"),
    ("my id is 12345678 on the app", "my id is [NUMBER] on the app"),
    ("dm @coolgifter99 about it", "dm [HANDLE] about it"),
])
def test_pattern_based_details_are_replaced(raw, expected):
    assert deidentify(raw).text == expected


def test_known_names_are_replaced_whole_word_and_case_insensitive():
    out = deidentify("Dana said MIRA ignored my gift, thanks dana", person_names=["Dana Smith"],
                     host_names=["mira"])
    assert out.text == "[NAME] said [HOST] ignored my gift, thanks [NAME]"
    assert out.replacements == 3


def test_common_words_and_substrings_are_not_scrubbed():
    out = deidentify("the gift never showed, Daniela too", person_names=["Dan", "Test Gift"])
    assert "Daniela" in out.text and "gift" in out.text  # whole words only, common words skipped


def test_amounts_and_meaning_survive():
    assert deidentify("got charged twice for 7,000 coins").text == "got charged twice for 7,000 coins"


def test_residual_flags_possible_names_and_digits():
    assert "capitalized word: Priya" in deidentify("I told Priya about it").residual
    assert "digits: 99887" in deidentify("order 99887 failed").residual  # 5 digits: not auto-replaced, flagged
    assert any(f.startswith("digits") for f in residual_flags("code 1234 here"))
    assert deidentify("my gift never showed. She is live!").residual == []


def test_placeholders_do_not_count_as_residual():
    assert deidentify("email a@b.com or call 555 123 4567 today").residual == []


def test_name_tokens():
    assert name_tokens(["Ana Maria Lopez", None]) >= {"ana maria lopez", "maria", "lopez", "ana"}
