"""Runs classify + prioritize over a labeled set; prints accuracy, P0 recall, confusion table.

    python eval.py [--limit N]          the synthetic set, data/labeled_messages.csv (the release gate)
    python eval.py --real [--limit N]   the approved, de-identified real set from the private database

The real set is kept apart from the synthetic one: its results go in their own history, and it is never
exported to a file. Needs QWEN_API_KEY and QWEN_BASE_URL (see .env.example).
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from triage.classify import classify
from triage.config import ROOT, get_settings
from triage.prioritize import prioritize

HISTORY = ROOT / "data" / "eval_history.json"
GATE_ACCURACY, GATE_P0_RECALL = 0.85, 0.95


def score(rows: list[dict[str, str]], results: list[dict]) -> dict:
    correct = sum(r["category"] == res["category"] for r, res in zip(rows, results))
    p0_rows = [(r, res) for r, res in zip(rows, results) if r["expected_priority"] == "P0"]
    p0_hit = sum(prioritize(res, None, None)[0] == "P0" for _, res in p0_rows)
    confusion = Counter((r["category"], str(res["category"])) for r, res in zip(rows, results)
                        if r["category"] != res["category"])
    return {
        "rows": len(rows), "category_accuracy": correct / len(rows),
        "p0_recall": p0_hit / len(p0_rows) if p0_rows else 1.0, "confusion": confusion,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--real", action="store_true", help="score the approved real set instead of the CSV")
    args = ap.parse_args()
    which = "real" if args.real else "synthetic"
    settings = get_settings()
    if not settings.api_key or not settings.base_url:
        print("Set QWEN_API_KEY and QWEN_BASE_URL in .env (see .env.example).", file=sys.stderr)
        return 2
    if args.real:
        from app import realset
        from app.store import connect
        with connect() as conn:
            rows = realset.approved(conn)
        if not rows:
            print("The real set has no approved examples yet. Build and review some first (see README).")
            return 2
        if len(rows) < realset.MIN_ROWS_FOR_STABLE_SCORE:
            print(f"Note: only {len(rows)} approved examples; scores this small are not stable.\n")
    else:
        with (ROOT / "data" / "labeled_messages.csv").open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[: args.limit]
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda r: classify(r["message"], {}, settings=settings), rows))
    s = score(rows, results)

    history = json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    same_set = [h for h in history if h.get("set", "synthetic") == which]
    prev = same_set[-1] if same_set else None
    fmt = lambda v: f"{v:.1%}"
    print(f"set: {which}, rows: {s['rows']}")
    print(f"category accuracy: {fmt(s['category_accuracy'])}  (previous: {fmt(prev['category_accuracy']) if prev else 'none'})")
    print(f"P0 recall:         {fmt(s['p0_recall'])}  (previous: {fmt(prev['p0_recall']) if prev else 'none'})")
    print("\nconfusion (expected -> predicted: count):")
    for (exp, got), n in s["confusion"].most_common():
        print(f"  {exp} -> {got}: {n}")
    green = s["category_accuracy"] >= GATE_ACCURACY and s["p0_recall"] >= GATE_P0_RECALL
    print("\nGATE:", "GREEN" if green else "RED")

    if not args.limit:
        history.append({"at": datetime.now(timezone.utc).isoformat(), "model": settings.classifier_model, "set": which,
                        "category_accuracy": s["category_accuracy"], "p0_recall": s["p0_recall"]})
        HISTORY.write_text(json.dumps(history, indent=2))
    return 0 if green else 1


if __name__ == "__main__":
    sys.exit(main())
