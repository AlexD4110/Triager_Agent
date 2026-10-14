import pytest


@pytest.fixture(autouse=True)
def never_touch_the_real_database(tmp_path, monkeypatch):
    """Blank DATABASE_URL for every test. An empty value wins over load_dotenv(), which only fills unset
    variables, so no test or imported module can reach the real database. SQLite goes to a temp file."""
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "test.db"))
