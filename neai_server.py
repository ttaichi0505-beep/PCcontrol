"""Local NeAI input system and cursor-only PC control service."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from neai_protocol import ActionValidationError
from neai_runtime import ControlRuntime, Intent


HOST = "127.0.0.1"
PORT = 8765
MAX_BODY_BYTES = 64 * 1024
WEB_DIR = Path(__file__).with_name("web")


def query_float(path: str, name: str, default: float) -> float:
    values = parse_qs(urlparse(path).query).get(name)
    if not values:
        return default
    try:
        return float(values[0])
    except ValueError as error:
        raise ValueError(f"{name} must be a number") from error


def query_bool(path: str, name: str) -> bool:
    values = parse_qs(urlparse(path).query).get(name, [])
    return values and values[0].lower() in {"1", "true", "yes"}


def intent_json(intent: Intent | None) -> dict[str, Any]:
    if intent is None:
        return {"intent": None}
    return {"intent": {"id": intent.id, "text": intent.text, "createdAt": intent.created_at}}


class NeAIRequestHandler(BaseHTTPRequestHandler):
    server: "NeAIHTTPServer"

    def log_message(self, format: str, *args: object) -> None:
        # The default line is useful, but include no request payloads (they may contain user data).
        print(f"[neai] {self.address_string()} - {format % args}")

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length_text = self.headers.get("Content-Length")
        if length_text is None:
            raise ValueError("Content-Length is required")
        try:
            length = int(length_text)
        except ValueError as error:
            raise ValueError("invalid Content-Length") from error
        if not 0 <= length <= MAX_BODY_BYTES:
            raise ValueError(f"request body must be at most {MAX_BODY_BYTES} bytes")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("request must contain UTF-8 JSON") from error
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    def _binary(self, status: HTTPStatus, content_type: str, body: bytes, extra_headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/status":
                self._json(HTTPStatus.OK, self.server.runtime.status())
                return
            if path == "/api/session":
                scale = query_float(self.path, "scale", 1.0)
                include_image = query_bool(self.path, "includeImage")
                self._json(HTTPStatus.OK, self.server.runtime.shared_snapshot(scale=scale, include_image=include_image))
                return
            if path == "/api/screen":
                scale = query_float(self.path, "scale", 1.0)
                png, meta = self.server.runtime.session.frame_png(scale=scale)
                self._binary(
                    HTTPStatus.OK,
                    "image/png",
                    png,
                    {
                        "X-NeAI-Frame-Seq": str(meta["seq"]),
                        "X-NeAI-Frame-Width": str(meta["width"]),
                        "X-NeAI-Frame-Height": str(meta["height"]),
                    },
                )
                return
            if path == "/api/cursor":
                self._json(HTTPStatus.OK, {"cursor": self.server.runtime.cursor_position()})
                return
            if path == "/api/intents/next":
                self._json(HTTPStatus.OK, intent_json(self.server.runtime.next_intent()))
                return
        except ValueError as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        if path in {"/", "/index.html"}:
            body = (WEB_DIR / "index.html").read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            data = self._read_json()
            if self.path == "/api/arm":
                if data.get("confirmation") != "ARM":
                    raise ValueError('confirmation must exactly be "ARM"')
                self.server.runtime.arm()
                self._json(HTTPStatus.OK, self.server.runtime.status())
            elif self.path == "/api/disarm":
                discarded = self.server.runtime.disarm()
                self._json(HTTPStatus.OK, {**self.server.runtime.status(), "discarded": discarded})
            elif self.path == "/api/intents":
                intent = self.server.runtime.submit_intent(data.get("text"))
                self._json(HTTPStatus.CREATED, intent_json(intent))
            elif self.path == "/api/plans":
                plan = self.server.runtime.submit_plan(data)
                self._json(HTTPStatus.ACCEPTED, {"id": plan.id, "state": plan.state})
            elif self.path == "/api/actions":
                plan = self.server.runtime.submit_action(data)
                self._json(HTTPStatus.ACCEPTED, {"id": plan.id, "state": plan.state, "actions": len(plan.actions)})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except PermissionError as error:
            self._json(HTTPStatus.CONFLICT, {"error": str(error)})
        except (ValueError, ActionValidationError) as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})


class NeAIHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, runtime: ControlRuntime) -> None:
        super().__init__((HOST, PORT), NeAIRequestHandler)
        self.runtime = runtime


def main() -> None:
    runtime = ControlRuntime()
    server = NeAIHTTPServer(runtime)
    print(f"NeAI Cursor Control: http://{HOST}:{PORT}")
    print("Shared desktop session is ready. Cursor control is DISARMED until you enter ARM locally.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping NeAI Cursor Control.")
    finally:
        server.server_close()
        runtime.close()


if __name__ == "__main__":
    main()
