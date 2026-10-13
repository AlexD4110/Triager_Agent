"""FastAPI routes for the WhatsApp Cloud API webhook. Receive-only: no outbound calls, no read receipts.

POST verifies Meta's signature, saves the raw payload, dedups on wamid, and returns 200.
Model calls happen in the worker, never here.
"""
import hashlib
import hmac
import logging
import os

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

from app import store
from app.policy_pages import router as policy_router
from triage.config import load_dotenv

load_dotenv()
log = logging.getLogger("webhook")
app = FastAPI(title="Gifter Triage webhook")
app.include_router(policy_router)


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Checks the X-Hub-Signature-256 header (sha256 HMAC of the raw body, keyed by the app secret)."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/webhook")
def verify(request: Request) -> Response:
    """Answers Meta's one-time verification challenge."""
    q = request.query_params
    token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    given = q.get("hub.verify_token", "")
    if q.get("hub.mode") == "subscribe" and token and hmac.compare_digest(token, given):
        return PlainTextResponse(q.get("hub.challenge", ""))
    return Response(status_code=403)


@app.post("/webhook")
async def receive(request: Request) -> Response:
    body = await request.body()
    ok = verify_signature(os.environ.get("WHATSAPP_APP_SECRET", ""), body,
                          request.headers.get("X-Hub-Signature-256"))
    if not ok:
        log.warning("rejected webhook: bad signature")
        return Response(status_code=403)  # nothing from an unverified sender is stored
    raw_id = store.save_raw(body, ok)
    payload = store.parse_json(body)
    if payload is None:
        log.warning("webhook body was not a JSON object; raw payload %s kept", raw_id)
    else:
        store.save_messages(raw_id, payload)
    return Response(status_code=200)
