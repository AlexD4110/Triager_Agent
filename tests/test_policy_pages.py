from fastapi.testclient import TestClient

from app import policy_pages
from app.webhook import app

client = TestClient(app)


def test_privacy_page_is_public_html():
    r = client.get("/privacy")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert policy_pages.CONTACT_EMAIL in r.text and f"{policy_pages.RETENTION_DAYS} days" in r.text
    assert 'href="/data-deletion"' in r.text


def test_data_deletion_page_is_public_html():
    r = client.get("/data-deletion")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "Delete my data" in r.text and f"{policy_pages.DELETION_DAYS} days" in r.text


def test_existing_routes_unchanged():
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/webhook").status_code == 403
