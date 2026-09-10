"""NeAI client for a shared-desktop observe-act loop."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class NeAIClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8765") -> None:
        self.base_url = base_url.rstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        accept_json: bool = True,
    ) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read()
                if not accept_json:
                    return raw, dict(response.headers)
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(detail).get("error", detail)
            except json.JSONDecodeError:
                message = detail or error.reason
            raise RuntimeError(message) from error

    def status(self) -> dict[str, Any]:
        return self._request("GET", "/api/status")

    def session(self, *, scale: float = 1.0, include_image: bool = False) -> dict[str, Any]:
        query = f"?scale={scale}"
        if include_image:
            query += "&includeImage=1"
        return self._request("GET", f"/api/session{query}")

    def screen_png(self, *, scale: float = 1.0) -> tuple[bytes, dict[str, str]]:
        png, headers = self._request("GET", f"/api/screen?scale={scale}", accept_json=False)
        return png, {key.lower(): value for key, value in headers.items()}

    def next_intent(self) -> dict[str, Any] | None:
        payload = self._request("GET", "/api/intents/next")
        return payload.get("intent")

    def submit_action(self, action: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/actions", {"action": action})

    def submit_plan(self, actions: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request("POST", "/api/plans", {"actions": actions})


def main() -> None:
    client = NeAIClient()
    snapshot = client.session(scale=0.5)
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    intent = client.next_intent()
    print("next intent:", json.dumps(intent, ensure_ascii=False) if intent else "none")


if __name__ == "__main__":
    main()
