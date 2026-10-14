"""Worker: claims jobs, labels each message, computes priority in code, saves, and alerts.

    python -m app.worker

Model calls happen here and never in the webhook. Each step uses its own short database transaction so a
slow model call never holds a connection open.
"""
import logging
import time
from typing import Any

from app import alerts, jobs
from app.store import connect
from triage.classify import classify, make_client
from triage.config import Settings, get_settings, load_dotenv
from triage.prioritize import prioritize

log = logging.getLogger("worker")
MODEL_FAILURES = {"parse_failed", "model_empty", "model_down"}
NOISE_TYPES = {"sticker", "reaction"}  # no words to read, treated like emoji-only noise
MODEL_DOWN_NOTICE_EVERY = 900  # seconds between "model unreachable" notices
_last_notice = 0.0


def label_message(message: dict[str, Any], context: dict[str, Any], client: Any, settings: Settings) -> dict[str, Any]:
    """Returns the label dict for one message. The model is skipped when there is nothing to read."""
    text = (message.get("text") or "").strip()
    if message["msg_type"] in NOISE_TYPES and not text:
        return {"category": "noise", "safety_flag": False, "security_flag": False, "churn_signal": False,
                "mentions_host": None, "language": "en", "summary": f"{message['msg_type']} only",
                "confidence": 1.0, "fallback": None}
    if not text:  # image, voice note, document with no caption: a person must look
        return {"category": None, "safety_flag": False, "security_flag": False, "churn_signal": False,
                "mentions_host": None, "language": "en", "summary": f"{message['msg_type']} message, no text",
                "confidence": 0.0, "fallback": "non_text"}
    return classify(text, context, client=client, settings=settings)


def build_context(conn: Any, message: dict[str, Any], gifter: dict[str, Any] | None,
                  live: dict[str, bool]) -> dict[str, Any]:
    hosts = [h.strip().lower() for h in (gifter or {}).get("hosts", "").split(",") if h.strip()]
    host_live = any(live.get(h) for h in hosts) if hosts else None
    return {"recent_messages": jobs.recent_texts(conn, message["wa_from"], message["id"]), "host_live": host_live}


def flag_from_history(conn: Any, message: dict[str, Any], result: dict[str, Any]) -> None:
    """When every model attempt failed, a sender with a recent safety flag gets the safety flag too, so the
    safety floor makes the message P0. This is a flag added by the rule layer, not a priority modifier, and
    it is only ever added. It applies to model failures only, never to a normal result."""
    if jobs.has_recent_safety_flag(conn, message["wa_from"], message["id"]):
        result["safety_flag"] = True
        result["summary"] = "Model failed; sender had a recent safety flag. Treat as urgent."
        log.warning("message %s: model failed and sender has a recent safety flag -> safety flag set", message["id"])


def run_one(client: Any, settings: Settings, poster: alerts.Poster = alerts.post_slack) -> bool:
    """Processes one job. Returns False when there was nothing to do."""
    with connect() as conn:
        job = jobs.claim_job(conn)
    if not job:
        return False
    try:
        with connect() as conn:
            message = jobs.load_message(conn, job["message_id"])
            gifter = jobs.get_gifter(conn, message["wa_from"])
            live = jobs.live_map(conn)
            context = build_context(conn, message, gifter, live)
        result = label_message(message, context, client, settings)  # slow: no connection held
        if result.get("fallback") in MODEL_FAILURES:
            with connect() as conn:
                flag_from_history(conn, message, result)
        priority, deadline = prioritize(result, {"tier": (gifter or {}).get("tier")}, live)
        with connect() as conn:
            result_id, due_at = jobs.save_result(conn, message, result, priority, deadline)
            jobs.finish_job(conn, job["id"], "done")
    except Exception as exc:
        log.exception("job %s failed", job["id"])
        with connect() as conn:
            log.warning("job %s -> %s", job["id"], jobs.fail_or_retry(conn, job, f"{type(exc).__name__}: {exc}"))
        return True

    if result.get("fallback") == "model_down":
        _notify_model_down(poster)
    if result_id:
        row = {"priority": priority, "category": result.get("category"), "summary": result.get("summary"),
               "deadline_minutes": deadline, "due_at": due_at, "fallback": result.get("fallback"),
               "profile_name": message.get("profile_name")}
        status, error = alerts.send_alert(row, poster)
        with connect() as conn:
            jobs.set_alert(conn, result_id, status, error) if status != "none" else jobs.mark_no_alert(conn, result_id)
        log.info("message %s -> %s %s (%dm), alert %s", message["id"], priority, result.get("category"), deadline, status)
    return True


def _notify_model_down(poster: alerts.Poster) -> None:
    global _last_notice
    if time.time() - _last_notice > MODEL_DOWN_NOTICE_EVERY:
        _last_notice = time.time()
        alerts.send_builder_notice("The classifier model is unreachable. Messages are getting rules-only "
                                   "labels at P2 until it recovers.", poster)


def retry_alerts(poster: alerts.Poster = alerts.post_slack) -> int:
    """Re-sends P0 and P1 alerts that failed earlier (Slack outage, missing webhook URL)."""
    with connect() as conn:
        pending = jobs.alerts_to_retry(conn)
    sent = 0
    for row in pending:
        status, error = alerts.send_alert(row, poster)
        with connect() as conn:
            jobs.set_alert(conn, row["result_id"], status, error)
        sent += status == "sent"
    return sent


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = get_settings()
    if not settings.api_key:
        log.warning("QWEN_API_KEY is not set: every message will get a rules-only label at P2")
    client = make_client(settings)
    last_housekeeping = 0.0
    log.info("worker started")
    while True:
        if time.time() - last_housekeeping > 60:
            last_housekeeping = time.time()
            with connect() as conn:
                requeued = jobs.requeue_stale(conn)
            if requeued:
                log.warning("requeued %d stale jobs", requeued)
            retry_alerts()
        if not run_one(client, settings):
            time.sleep(1)


if __name__ == "__main__":
    main()
