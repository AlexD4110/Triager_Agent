"""classify(message, context) -> dict. Rules first, then the model, then validation and fallbacks."""
import json
import re
from typing import Any

from pydantic import ValidationError

from triage.config import ROOT, Settings, get_settings, load_taxonomy, load_tie_breaks
from triage.rules import apply_rules, mask_cards
from triage.schemas import ModelOutput

PROMPT_DIR = ROOT / "triage" / "prompts"


def build_system_prompt() -> str:
    tax = load_taxonomy()
    categories = "\n".join(f"- {name}: {info['definition']}" for name, info in tax.items())
    tie_breaks = "\n".join(f"- {t}" for t in load_tie_breaks())
    examples = (PROMPT_DIR / "examples.txt").read_text(encoding="utf-8").strip()
    template = (PROMPT_DIR / "system.txt").read_text(encoding="utf-8")
    return template.format(categories=categories, tie_breaks=tie_breaks, examples=examples)


def build_user_prompt(text: str, context: dict[str, Any]) -> str:
    recent = [mask_cards(m) for m in context.get("recent_messages", [])[-3:]]
    lines = []
    if recent:
        lines.append("Last messages in this thread:\n" + "\n".join(f"- {m}" for m in recent))
    if context.get("host_live") is not None:
        lines.append(f"Host live now: {'yes' if context['host_live'] else 'no'}")
    lines.append(f'Message: "{text}"')
    return "\n".join(lines)


def parse_output(raw: str) -> ModelOutput:
    """Strips reasoning tags and code fences, then validates the first JSON object."""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in model output")
    return ModelOutput.model_validate(json.loads(raw[start:end + 1]))


def call_model(client: Any, model: str, system: str, user: str) -> ModelOutput:
    resp = client.messages.create(
        model=model, max_tokens=2000, system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return parse_output(text)


def _run(client: Any, model: str, system: str, user: str) -> ModelOutput:
    """One call, and one retry if the JSON does not parse or validate."""
    try:
        return call_model(client, model, system, user)
    except (ValueError, ValidationError):
        return call_model(client, model, system, user)


def make_client(settings: Settings) -> Any:
    """Builds the SDK client for the Qwen endpoint from QWEN_API_KEY and QWEN_BASE_URL."""
    import anthropic  # the SDK is only the transport; the endpoint serves Qwen models
    return anthropic.Anthropic(api_key=settings.api_key, base_url=settings.base_url or None)


def classify(message: str, context: dict[str, Any] | None = None, client: Any = None,
             settings: Settings | None = None) -> dict[str, Any]:
    """Returns the label dict. `fallback` names any degraded path; priority is never set here."""
    context = context or {}
    settings = settings or get_settings()
    text = mask_cards(message)
    rules = apply_rules(text)
    result: dict[str, Any] = {
        "category": None, "safety_flag": rules.safety_flag, "security_flag": rules.security_flag,
        "churn_signal": False, "mentions_host": None, "language": "en", "summary": "",
        "confidence": 0.0, "fallback": None, "rule_flags": [],
    }
    result["rule_flags"] = [f for f, on in (("safety", rules.safety_flag), ("security", rules.security_flag)) if on]

    if rules.is_noise:
        result.update(category="noise", confidence=1.0, summary="Filtered as noise by rules")
        return result

    if client is None:
        client = make_client(settings)
    system, user = build_system_prompt(), build_user_prompt(text, context)

    try:
        try:
            out = _run(client, settings.classifier_model, system, user)
        except (ValueError, ValidationError):
            raise
        except Exception:  # primary model unreachable: try the backup before giving up
            if not settings.backup_model:
                raise
            out = _run(client, settings.backup_model, system, user)
        if out.confidence < settings.confidence_cutoff and settings.backup_model:
            out = _run(client, settings.backup_model, system, user)
    except (ValueError, ValidationError):
        result["fallback"] = "parse_failed"
        return result
    except Exception:  # both models unreachable: rules-only result
        result["fallback"] = "model_down"
        return result

    data = out.model_dump()
    # Rule flags can only be added to, never removed.
    data["safety_flag"] = data["safety_flag"] or rules.safety_flag
    data["security_flag"] = data["security_flag"] or rules.security_flag
    result.update(data)
    if out.confidence < settings.confidence_cutoff:
        result["fallback"] = "low_confidence"
    return result
