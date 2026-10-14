"""Rule layer: runs before the model. Flags found here can be added to, never removed."""
import re
from dataclasses import dataclass

CARD_RE = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")
SAFETY_RE = re.compile(
    r"kill myself|\bkms\b|suicid|hurt myself|self[- ]?harm|ending it|end it all|end my life"
    r"|don'?t want to be here|no point|better (?:off )?without me|(?:happier|better) (?:off )?if i (?:was|were) gone|if i (?:just )?disappear"
    r"|wish i (?:was|were) (?:dead|gone)|want to die|can'?t go on|no reason to (?:live|go on)|nothing matters"
    r"|(?:don'?t|do not|dont) see the point (?:anymore|of (?:anything|living|life|going on|it all))"
    r"|hopeless"
    r"|no quiero (?:seguir (?:aqu[ií]|viviendo|adelante|as[ií])|vivir|estar aqu[ií])|no veo (?:el )?sentido"
    r"|(?:me )?quiero morir|matarme|quitarme la vida|hacerme da[nñ]o|mejor sin m[ií]|no vale la pena vivir|acabar con todo"
    r"|tired of everything|don'?t know what i'?ll do"
    r"|\bkill (?:him|her|you|them|that|the)\b|\bhurt (?:you|her|him|them)\b|someone is going to get hurt"
    r"|watch (?:her|his|your) back|find out where \w+ lives|know where you live|show up at (?:her|his|my) house"
    r"|i(?:'ll| will) find (?:you|her|him|out)|\bthreat|doxx|regrets? (?:this|it)"
    r"|\bi'?m (?:1[0-7]|[7-9])\b|\bim (?:1[0-7]|[7-9])\b|\b(?:1[0-7]|[7-9]) years? old"
    r"|\b(?:[1-9]|1[0-2])(?:st|nd|rd|th) grade|middle school|high school|under ?age|\bminor\b"
    r"|using (?:her|his|my) (?:mom|dad|mother|father)'?s|mom doesn'?t know|dad found out"
    r"|meet (?:her|him|me) alone|don'?t tell anyone|not to tell anyone|send (?:me )?photos"
    r"|\bis (?:she|he|the host) (?:1[0-7]|[7-9])\b|(?:host|she|he) is (?:1[0-7]|[7-9])\b",
    re.IGNORECASE,
)
SECURITY_RE = re.compile(
    r"hack|phish|scam|impersonat|pretending to be|pretends to be|fake (?:account|support|profile)"
    r"|(?:someone|somebody|they) (?:changed|reset) (?:the|my) (?:email|password|phone)"
    r"|selling .{0,25} in your name|using my (?:name|username|account|profile)|(?:my|your) (?:name|username) is being used"
    r"|login from (?:another|a different|an unknown) (?:country|device|location)|unknown (?:device|login)"
    r"|cheap coins|pay (?:by|in|with) crypto"
    r"|spoof|cloned|login code|verification code|verify my account|2fa|password (?:changed|reset)|knows? my password|account (?:was )?taken"
    r"|someone (?:else )?(?:is )?(?:using|logged)|unauthori[sz]ed|locked out|recovery email"
    r"|hackearon|hackeo|estafa",
    re.IGNORECASE,
)
EMOJI_ONLY_RE = re.compile(r"^[\W_\d]*$", re.UNICODE)


@dataclass(frozen=True)
class RuleResult:
    is_noise: bool
    safety_flag: bool
    security_flag: bool


def mask_cards(text: str) -> str:
    """Replaces card-like digit runs with a token before text reaches the model."""
    return CARD_RE.sub("[CARD]", text)


def is_noise(text: str) -> bool:
    """Emoji-only, symbol-only, or under 3 characters."""
    stripped = text.strip()
    return len(stripped) < 3 or bool(EMOJI_ONLY_RE.match(stripped))


def apply_rules(text: str) -> RuleResult:
    safety = bool(SAFETY_RE.search(text))
    security = bool(SECURITY_RE.search(text))
    # Safety and security language outranks the noise filter.
    return RuleResult(is_noise(text) and not (safety or security), safety, security)
