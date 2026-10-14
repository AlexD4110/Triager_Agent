import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from triage.qwen import QwenClient, QwenError, thinking_params

SEEN: list[dict] = []
STATE = {"status": 200, "body": None}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers["Content-Length"])
        SEEN.append({"path": self.path, "auth": self.headers["Authorization"],
                     "body": json.loads(self.rfile.read(length))})
        body = json.dumps(STATE["body"]).encode()
        self.send_response(STATE["status"])
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture()
def server():
    SEEN.clear()
    STATE.update(status=200, body={
        "choices": [{"message": {"content": '{"x": 1}', "reasoning_content": "hmm"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 40, "completion_tokens": 25,
                  "completion_tokens_details": {"reasoning_tokens": 20}}})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/compatible-mode/v1"
    httpd.shutdown()


def test_request_shape_and_reply_parsing(server):
    client = QwenClient("secret-key", server)
    reply = client.complete("m1", "SYS", "USER", 123, {"enable_thinking": False})
    req = SEEN[0]
    assert req["path"] == "/compatible-mode/v1/chat/completions" and req["auth"] == "Bearer secret-key"
    assert req["body"]["model"] == "m1" and req["body"]["max_tokens"] == 123
    assert req["body"]["enable_thinking"] is False
    assert req["body"]["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]
    assert (reply.text, reply.finish_reason, reply.prompt_tokens, reply.output_tokens, reply.reasoning_tokens) == \
        ('{"x": 1}', "stop", 40, 25, 20)


def test_missing_content_becomes_empty_text(server):
    STATE["body"] = {"choices": [{"message": {"content": None}, "finish_reason": "length"}], "usage": {}}
    reply = QwenClient("k", server).complete("m", "s", "u")
    assert reply.text == "" and reply.finish_reason == "length" and reply.output_tokens == 0


def test_http_error_and_error_body_raise_without_leaking_key(server):
    STATE.update(status=400, body={"error": {"message": "bad param"}})
    with pytest.raises(QwenError) as exc:
        QwenClient("secret-key", server).complete("m", "s", "u")
    assert "400" in str(exc.value) and "secret-key" not in str(exc.value)
    STATE.update(status=200, body={"error": {"message": "overloaded"}})
    with pytest.raises(QwenError, match="overloaded"):
        QwenClient("secret-key", server).complete("m", "s", "u")


def test_unreachable_and_unset_url_raise():
    with pytest.raises(QwenError):
        QwenClient("k", "http://127.0.0.1:9", timeout=2).complete("m", "s", "u")
    with pytest.raises(QwenError, match="QWEN_BASE_URL"):
        QwenClient("k", "").complete("m", "s", "u")


def test_thinking_params_modes():
    assert thinking_params("off") == {"enable_thinking": False}
    assert thinking_params("on") == {"enable_thinking": True}
    assert thinking_params("budget", 64) == {"enable_thinking": True, "thinking_budget": 64}
