import csv
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _taxonomy() -> dict[str, str]:
    """Reads category names and base priorities from categories.yaml without a YAML library."""
    found: dict[str, str] = {}
    current = None
    for line in (ROOT / "categories.yaml").read_text(encoding="utf-8").splitlines():
        if m := re.match(r"^  (\w+):\s*$", line):
            current = m.group(1)
        elif current and (m := re.match(r"^    base_priority: (P[0-3])", line)):
            found[current] = m.group(1)
    return found


def _rows() -> list[dict[str, str]]:
    with (ROOT / "data" / "labeled_messages.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_taxonomy_has_ten_categories() -> None:
    assert len(_taxonomy()) == 10


def test_dataset_size_and_ids_unique() -> None:
    rows = _rows()
    assert len(rows) == 250
    assert len({r["id"] for r in rows}) == 250


def test_every_category_covered() -> None:
    counts = Counter(r["category"] for r in _rows())
    assert set(counts) == set(_taxonomy())
    assert all(n >= 20 for n in counts.values())


def test_hard_cases_count() -> None:
    assert sum(r["hard_case"] == "yes" for r in _rows()) == 30


def test_priorities_valid_and_match_base_unless_noted() -> None:
    tax = _taxonomy()
    for r in _rows():
        assert r["expected_priority"] in {"P0", "P1", "P2", "P3"}
        if r["expected_priority"] != tax[r["category"]]:
            assert r["hard_case"] == "yes", f"{r['id']} overrides priority without being a hard case"


def test_no_empty_or_duplicate_messages() -> None:
    msgs = [r["message"].strip().lower() for r in _rows()]
    assert all(msgs)
    assert len(set(msgs)) == len(msgs)
