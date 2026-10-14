import json
import sys

import eval as evaluation  # the project's eval.py
from app import realset, store


def approve_example(text, category, priority):
    with store.connect() as c:
        c.execute("INSERT INTO real_labeled_set (text_deid, text_hash, category, priority, status, created_week,"
                  " created_at, expires_at) VALUES (?, ?, ?, ?, 'approved', '2026-W42', 'x', '2999-01-01T00:00:00+00:00')",
                  (text, realset.text_hash(text), category, priority))


def run_eval(monkeypatch, tmp_path, capsys, *args):
    monkeypatch.setattr(evaluation, "HISTORY", tmp_path / "history.json")
    monkeypatch.setenv("QWEN_API_KEY", "k")
    monkeypatch.setenv("QWEN_BASE_URL", "http://x.test")
    monkeypatch.setattr(sys, "argv", ["eval.py", *args])
    code = evaluation.main()
    return code, capsys.readouterr().out


def test_real_flag_scores_only_approved_rows_and_keeps_its_own_history(monkeypatch, tmp_path, capsys):
    approve_example("[NAME] was charged twice", "payment_issue", "P1")
    approve_example("someone is pretending to be me", "account_security", "P0")
    monkeypatch.setattr(evaluation, "classify", lambda msg, ctx, settings=None: {
        "category": "payment_issue" if "charged" in msg else "account_security",
        "safety_flag": False, "security_flag": False, "fallback": None})
    (tmp_path / "history.json").write_text(json.dumps([{"set": "synthetic", "category_accuracy": 0.5, "p0_recall": 0.5}]))
    code, out = run_eval(monkeypatch, tmp_path, capsys, "--real")
    assert "set: real, rows: 2" in out and "category accuracy: 100.0%  (previous: none)" in out  # not the synthetic run
    assert "only 2 approved examples" in out
    history = json.loads((tmp_path / "history.json").read_text())
    assert [h.get("set", "synthetic") for h in history] == ["synthetic", "real"]


def test_real_flag_with_nothing_approved_exits_cleanly(monkeypatch, tmp_path, capsys):
    code, out = run_eval(monkeypatch, tmp_path, capsys, "--real")
    assert code == 2 and "no approved examples" in out
