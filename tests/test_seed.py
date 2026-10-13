import csv

from app import jobs, seed, store
from triage.config import ROOT


def test_mock_gifters_cover_tiers_and_use_fake_numbers():
    rows = list(csv.DictReader(open(ROOT / "data" / "mock_gifters.csv")))
    assert {r["tier"] for r in rows} == {"top", "mid", "standard"}
    assert all(r["wa_id"].startswith("1555555") for r in rows)  # reserved fictional range


def test_seed_is_repeatable_and_set_live_normalizes_names(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    with store.connect() as c:
        seed.load_gifters(c, ROOT / "data" / "mock_gifters.csv")
        seed.load_gifters(c, ROOT / "data" / "mock_gifters.csv")
        assert c.execute("SELECT COUNT(*) FROM gifters").fetchone()[0] == 10
        seed.set_live(c, " @Mira ", True)
        assert jobs.live_map(c) == {"mira": True}
        seed.set_live(c, "MIRA", False)
        assert jobs.live_map(c) == {"mira": False}
