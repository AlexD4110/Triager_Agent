"""classify(message, context) -> dict. Rules first, then the model, then validation and fallbacks."""
import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from triage.config import ROOT, Settings, get_settings, load_taxonomy, load_tie_breaks
from triage.rules import apply_rules, mask_cards
from triage.schemas import ModelOutput

log = logging.getLogger("classify")
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


class ModelEmpty(Exception):
    """The model answered with no text at all (blocked, or chose not to answer)."""


def call_model(client: Any, model: str, system: str, user: str) -> ModelOutput:
    resp = client.messages.create(
        model=model, max_tokens=2000, system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    if not text.strip():
        # Never log the content. The stop reason tells a provider block from the model declining.
        usage = getattr(resp, "usage", None)
        log.warning("model_empty: model=%s stop_reason=%s blocks=%s output_tokens=%s", model,
                    getattr(resp, "stop_reason", None), [getattr(b, "type", "?") for b in resp.content],
                    getattr(usage, "output_tokens", None))
        raise ModelEmpty(f"stop_reason={getattr(resp, 'stop_reason', None)}")
    return parse_output(text)


def _attempts(settings: Settings, with_context: str, plain: str) -> list[tuple[str, str]]:
    """The order tried: primary with sender history, primary without it, then the backup without it."""
    steps = [(settings.classifier_model, with_context), (settings.classifier_model, plain)]
    if settings.backup_model:
        steps.append((settings.backup_model, plain))
    return steps


def run_chain(client: Any, settings: Settings, system: str, with_context: str,
              plain: str) -> tuple[ModelOutput | None, str, str | None]:
    """Returns (output, user prompt that worked, failure kind). Kind is model_empty, parse_failed or model_down.

    An unreachable primary skips straight to the backup. Empty and unparseable replies get a second try
    without the sender's earlier messages, because that history can derail the model.
    """
    kinds: list[str] = []
    primary_down = False
    for model, user in _attempts(settings, with_context, plain):
        if primary_down and model == settings.classifier_model:
            continue
        try:
            return call_model(client, model, system, user), user, None
        except ModelEmpty:
            kinds.append("model_empty")
        except (ValueError, ValidationError) as exc:
            log.warning("parse_failed: model=%s %s: %s", model, type(exc).__name__, str(exc)[:150])
            kinds.append("parse_failed")
        except Exception as exc:  # network or API outage
            log.warning("model_down: model=%s %s: %s", model, type(exc).__name__, str(exc)[:150])
            kinds.append("model_down")
            primary_down = primary_down or model == settings.classifier_model
    if all(k == "model_down" for k in kinds):
        return None, plain, "model_down"
    return None, plain, "parse_failed" if "parse_failed" in kinds else "model_empty"


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
    system = build_system_prompt()
    with_context, plain = build_user_prompt(text, context), build_user_prompt(text, {})

    out, used_prompt, failure = run_chain(client, settings, system, with_context, plain)
    if out is None:
        result["fallback"] = failure
        return result
    if out.confidence < settings.confidence_cutoff and settings.backup_model:
        try:  # second opinion; if the backup fails, keep the first answer
            out = call_model(client, settings.backup_model, system, used_prompt)
        except Exception as exc:
            log.warning("low-confidence recheck failed: %s", type(exc).__name__)

    data = out.model_dump()
    # Rule flags can only be added to, never removed.
    data["safety_flag"] = data["safety_flag"] or rules.safety_flag
    data["security_flag"] = data["security_flag"] or rules.security_flag
    result.update(data)
    if out.confidence < settings.confidence_cutoff:
        result["fallback"] = "low_confidence"
    return result
