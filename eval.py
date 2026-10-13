"""Runs classify + prioritize over data/labeled_messages.csv; prints accuracy, P0 recall, confusion table.

Usage: python eval.py [--limit N]. Needs QWEN_API_KEY and QWEN_BASE_URL (see .env.example).
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
    args = ap.parse_args()
    settings = get_settings()
    if not settings.api_key or not settings.base_url:
        print("Set QWEN_API_KEY and QWEN_BASE_URL in .env (see .env.example).", file=sys.stderr)
        return 2
    with (ROOT / "data" / "labeled_messages.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[: args.limit]
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda r: classify(r["message"], {}, settings=settings), rows))
    s = score(rows, results)

    history = json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    prev = history[-1] if history else None
    fmt = lambda v: f"{v:.1%}"
    print(f"rows: {s['rows']}")
    print(f"category accuracy: {fmt(s['category_accuracy'])}  (previous: {fmt(prev['category_accuracy']) if prev else 'none'})")
    print(f"P0 recall:         {fmt(s['p0_recall'])}  (previous: {fmt(prev['p0_recall']) if prev else 'none'})")
    print("\nconfusion (expected -> predicted: count):")
    for (exp, got), n in s["confusion"].most_common():
        print(f"  {exp} -> {got}: {n}")
    green = s["category_accuracy"] >= GATE_ACCURACY and s["p0_recall"] >= GATE_P0_RECALL
    print("\nGATE:", "GREEN" if green else "RED")

    if not args.limit:
        history.append({"at": datetime.now(timezone.utc).isoformat(), "model": settings.classifier_model,
                        "category_accuracy": s["category_accuracy"], "p0_recall": s["p0_recall"]})
        HISTORY.write_text(json.dumps(history, indent=2))
    return 0 if green else 1


if __name__ == "__main__":
    sys.exit(main())
