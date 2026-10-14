"""Best-effort removal of personal details from a message before it is stored in the real labeled set.

Rules cover what can be found by pattern: emails, links, handles, card and phone numbers, long ids, and the
names we know (the sender's profile name and the host names). Free-form names written in the text cannot
be found reliably without a language model, so `residual` lists suspicious leftovers and a person must
review every example before it is approved. Never treat the output as safe without that review.
"""
import re
from dataclasses import dataclass, field

from triage.rules import CARD_RE

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_RE = re.compile(r"(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|net|org|io|co|app|me|tv)(?:/\S*)?\b", re.IGNORECASE)
HANDLE_RE = re.compile(r"(?<!\w)@\w{2,}")
PHONE_RE = re.compile(r"(?<!\w)\+?\(?\d[\d\s().-]{7,}\d(?!\w)")
LONG_NUMBER_RE = re.compile(r"\b\d{6,}\b")
WORD_RE = re.compile(r"[A-Za-zÀ-ÿ']+")
SKIP_NAME_TOKENS = {"the", "and", "gift", "gifts", "live", "test", "user", "name", "host", "mock", "demo"}
PLACEHOLDER_RE = re.compile(r"\[[A-Z]+\]")


@dataclass
class DeidResult:
    text: str
    replacements: int = 0
    residual: list[str] = field(default_factory=list)


def _sub(pattern: re.Pattern, token: str, text: str) -> tuple[str, int]:
    return pattern.subn(token, text)


def name_tokens(names: list[str | None]) -> set[str]:
    """Each name and each word of it (3+ letters), lower case, minus very common words."""
    out: set[str] = set()
    for name in names:
        if not name:
            continue
        out.add(name.strip().lower())
        out.update(t.lower() for t in WORD_RE.findall(name) if len(t) >= 3)
    return {t for t in out if t and t not in SKIP_NAME_TOKENS}


def deidentify(text: str, person_names: list[str | None] = (), host_names: list[str | None] = ()) -> DeidResult:
    total = 0
    for pattern, token in ((EMAIL_RE, "[EMAIL]"), (URL_RE, "[URL]"), (CARD_RE, "[CARD]"), (HANDLE_RE, "[HANDLE]"),
                           (PHONE_RE, "[PHONE]"), (LONG_NUMBER_RE, "[NUMBER]")):
        text, n = _sub(pattern, token, text)
        total += n
    for names, token in ((person_names, "[NAME]"), (host_names, "[HOST]")):
        for tok in sorted(name_tokens(list(names)), key=len, reverse=True):
            text, n = re.subn(rf"(?<!\w){re.escape(tok)}(?!\w)", token, text, flags=re.IGNORECASE)
            total += n
    return DeidResult(text.strip(), total, residual_flags(text))


def residual_flags(text: str) -> list[str]:
    """Things a person should look at: capitalized words in the middle of a sentence (possible names),
    digits left over, and anything that looks like a code."""
    flags: list[str] = []
    plain = PLACEHOLDER_RE.sub(" ", text)
    for sentence in re.split(r"(?<=[.!?])\s+|\n", plain):
        words = WORD_RE.findall(sentence)
        for w in words[1:]:
            if w[0].isupper() and len(w) > 1 and not w.isupper() and w != "I" and not w.startswith("I'"):
                flags.append(f"capitalized word: {w}")
    flags += [f"digits: {m}" for m in re.findall(r"\d{4,}", plain)]
    return sorted(set(flags))
