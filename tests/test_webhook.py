import asyncio
import hashlib
import hmac
import json
import sqlite3

import pytest
from starlette.requests import Request

from app import store, webhook

SECRET = "test-secret"
PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": "1"},
        "contacts": [{"profile": {"name": "Test Gifter"}, "wa_id": "15550001111"}],
        "messages": [{"from": "15550001111", "id": "wamid.TEST1", "timestamp": "1749416383",
                      "type": "text", "text": {"body": "got charged twice"}}],
    }}]}],
}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRET)
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "vtoken")


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def make_request(method: str, body: bytes = b"", headers: dict | None = None, query: str = "") -> Request:
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {"type": "http", "method": method, "path": "/webhook", "query_string": query.encode(),
             "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]}
    return Request(scope, receive)


def post(body: bytes, signature: str | None):
    headers = {"X-Hub-Signature-256": signature} if signature else {}
    return asyncio.run(webhook.receive(make_request("POST", body, headers)))


def rows(table: str) -> int:
    with store.connect() as c:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_verify_signature():
    body = b"{}"
    assert webhook.verify_signature(SECRET, body, sign(body))
    assert not webhook.verify_signature(SECRET, body, sign(body, "other"))
    assert not webhook.verify_signature(SECRET, body, None)
    assert not webhook.verify_signature("", body, sign(body, ""))


def test_get_challenge_ok_and_wrong_token():
    ok = webhook.verify(make_request("GET", query="hub.mode=subscribe&hub.verify_token=vtoken&hub.challenge=12345"))
    assert ok.status_code == 200 and ok.body == b"12345"
    bad = webhook.verify(make_request("GET", query="hub.mode=subscribe&hub.verify_token=nope&hub.challenge=1"))
    assert bad.status_code == 403


def test_post_saves_message_and_job():
    body = json.dumps(PAYLOAD).encode()
    assert post(body, sign(body)).status_code == 200
    assert (rows("raw_payloads"), rows("messages"), rows("jobs")) == (1, 1, 1)
    with sqlite3.connect(store.db_path()) as c:
        text, name = c.execute("SELECT text, profile_name FROM messages").fetchone()
    assert (text, name) == ("got charged twice", "Test Gifter")


def test_duplicate_wamid_is_ignored_but_raw_kept():
    body = json.dumps(PAYLOAD).encode()
    post(body, sign(body))
    assert post(body, sign(body)).status_code == 200
    assert (rows("raw_payloads"), rows("messages"), rows("jobs")) == (2, 1, 1)


def test_bad_signature_rejected_and_nothing_stored():
    body = json.dumps(PAYLOAD).encode()
    assert post(body, sign(body, "wrong")).status_code == 403
    assert post(body, None).status_code == 403
    assert rows("raw_payloads") == 0


def test_status_updates_and_bad_json_return_200_without_messages():
    status = json.dumps({"entry": [{"changes": [{"field": "messages", "value": {
        "statuses": [{"id": "wamid.X", "status": "delivered"}]}}]}]}).encode()
    assert post(status, sign(status)).status_code == 200
    junk = b"not json"
    assert post(junk, sign(junk)).status_code == 200
    assert rows("messages") == 0 and rows("raw_payloads") == 2


def test_placeholder_database_url_is_rejected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:[YOUR-PASSWORD]@h:5432/postgres")
    with pytest.raises(RuntimeError, match="YOUR-PASSWORD"):
        store.connect()


def test_postgres_placeholders_are_translated():
    class FakeConn:
        def execute(self, sql, params):
            self.sql = sql
            return self

    db = store.Db.__new__(store.Db)
    db.postgres, db.conn = True, FakeConn()
    db.execute("INSERT INTO t (a, b) VALUES (?, ?)", (1, 2))
    assert db.conn.sql == "INSERT INTO t (a, b) VALUES (%s, %s)"


def test_webhook_makes_no_outbound_calls():
    src = open(webhook.__file__).read() + open(store.__file__).read()
    assert "requests" not in src and "httpx" not in src and "graph.facebook.com" not in src
