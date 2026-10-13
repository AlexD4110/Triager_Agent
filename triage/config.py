"""Settings from environment variables, plus the taxonomy read from categories.yaml."""
import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Loads KEY=VALUE lines into os.environ without overriding values already set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    classifier_model: str = "qwen3.8-flash"
    backup_model: str = "qwen3.8-max"  # empty string means no backup pass
    confidence_cutoff: float = 0.6
    api_key: str = ""
    base_url: str = ""  # e.g. https://<host>/compatible-mode/v1
    thinking_mode: str = "on"  # on | off | budget, for the main model
    backup_thinking_mode: str = "on"  # same choices, for the backup model
    thinking_budget: int = 256  # reasoning token cap when a mode is "budget"
    max_tokens: int = 2000


def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        classifier_model=os.environ.get("CLASSIFIER_MODEL", "qwen3.8-flash"),
        backup_model=os.environ.get("BACKUP_MODEL", "qwen3.8-max"),
        confidence_cutoff=float(os.environ.get("CONFIDENCE_CUTOFF", "0.6")),
        api_key=os.environ.get("QWEN_API_KEY", ""),
        base_url=os.environ.get("QWEN_BASE_URL", ""),
        thinking_mode=os.environ.get("THINKING_MODE", "on"),
        backup_thinking_mode=os.environ.get("BACKUP_THINKING_MODE", "on"),
        thinking_budget=int(os.environ.get("THINKING_BUDGET", "256")),
        max_tokens=int(os.environ.get("MAX_OUTPUT_TOKENS", "2000")),
    )


def load_taxonomy(path: Path = ROOT / "categories.yaml") -> dict[str, dict[str, str]]:
    """Returns {category: {base_priority, definition}} from categories.yaml (no YAML library needed)."""
    tax: dict[str, dict[str, str]] = {}
    current = None
    in_categories = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("categories:"):
            in_categories = True
        elif line and not line.startswith(" ") and not line.startswith("#"):
            in_categories = False
        if not in_categories:
            continue
        if m := re.match(r"^  (\w+):\s*$", line):
            current = m.group(1)
            tax[current] = {}
        elif current and (m := re.match(r"^    (base_priority|definition): (.*)$", line)):
            tax[current][m.group(1)] = m.group(2).strip()
    return tax


def load_tie_breaks(path: Path = ROOT / "categories.yaml") -> list[str]:
    """Returns the tie-break sentences listed under tie_breaks in categories.yaml."""
    out: list[str] = []
    active = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("tie_breaks:"):
            active = True
        elif line and not line.startswith((" ", "#")):
            active = False
        elif active and (m := re.match(r'^  - "(.*)"\s*$', line)):
            out.append(m.group(1))
    return out
