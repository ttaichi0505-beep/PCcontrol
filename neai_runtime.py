"""Thread-safe intent input and deliberately armed mouse-only plan execution."""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from neai_mouse import CursorController
from neai_protocol import Action, validate_plan
from neai_session import SharedSession


@dataclass
class Intent:
    id: str
    text: str
    created_at: float


@dataclass
class Plan:
    id: str
    actions: list[Action]
    created_at: float
    state: str = "queued"
    error: str | None = None


class ControlRuntime:
    def __init__(
        self,
        cursor: CursorController | None = None,
        session: SharedSession | None = None,
    ) -> None:
        self.cursor = cursor or CursorController()
        self.session = session or SharedSession(self.cursor)
        self._lock = threading.RLock()
        self._intents: queue.Queue[Intent] = queue.Queue()
        self._plans: queue.Queue[Plan] = queue.Queue()
        self._armed = False
        self._current: Plan | None = None
        self._last: Plan | None = None
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run, name="neai-cursor-worker", daemon=True)
        self._worker.start()

    def arm(self) -> None:
        with self._lock:
            self._armed = True

    def disarm(self) -> int:
        """Disarm and discard plans which have not begun running."""
        with self._lock:
            self._armed = False
        discarded = 0
        while True:
            try:
                plan = self._plans.get_nowait()
            except queue.Empty:
                return discarded
            plan.state = "discarded"
            with self._lock:
                self._last = plan
            discarded += 1

    def submit_intent(self, text: Any) -> Intent:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        if len(text) > 8_000:
            raise ValueError("text must contain at most 8000 characters")
        intent = Intent(uuid.uuid4().hex, text.strip(), time.time())
        self._intents.put(intent)
        return intent

    def next_intent(self) -> Intent | None:
        try:
            return self._intents.get_nowait()
        except queue.Empty:
            return None

    def submit_plan(self, payload: Any) -> Plan:
        actions = validate_plan(payload)
        return self._enqueue_plan(actions)

    def submit_action(self, payload: Any) -> Plan:
        if not isinstance(payload, dict):
            raise ValueError("action payload must be a JSON object")
        action = payload.get("action")
        if not isinstance(action, dict):
            raise ValueError("action must be a JSON object")
        return self._enqueue_plan(validate_plan({"actions": [action]}))

    def _enqueue_plan(self, actions: list[Action]) -> Plan:
        with self._lock:
            if not self._armed:
                raise PermissionError("cursor control is disarmed; arm it locally before submitting a plan")
        plan = Plan(uuid.uuid4().hex, actions, time.time())
        self._plans.put(plan)
        return plan

    def cursor_position(self) -> dict[str, Any]:
        return self.cursor.position()

    def shared_snapshot(self, *, scale: float = 1.0, include_image: bool = False) -> dict[str, Any]:
        snapshot = self.session.snapshot(scale=scale, include_image=include_image)
        with self._lock:
            snapshot["armed"] = self._armed
            snapshot["queueDepth"] = self._plans.qsize()
        return snapshot

    def status(self) -> dict[str, Any]:
        with self._lock:
            current = self._current
            last = self._last
            return {
                "mode": "shared_desktop",
                "armed": self._armed,
                "queueDepth": self._plans.qsize(),
                "currentPlan": self._plan_summary(current),
                "lastPlan": self._plan_summary(last),
                "mouseOnly": True,
                "allowedActions": ["move", "click", "double_click", "drag", "scroll", "wait"],
                "sessionUrl": "/api/session",
                "screenUrl": "/api/screen",
            }

    @staticmethod
    def _plan_summary(plan: Plan | None) -> dict[str, Any] | None:
        if plan is None:
            return None
        return {"id": plan.id, "state": plan.state, "actions": len(plan.actions), "error": plan.error}

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                plan = self._plans.get(timeout=0.2)
            except queue.Empty:
                continue
            with self._lock:
                if not self._armed:
                    plan.state = "discarded"
                    self._last = plan
                    continue
                plan.state = "running"
                self._current = plan
            try:
                for action in plan.actions:
                    with self._lock:
                        if not self._armed:
                            plan.state = "stopped"
                            break
                    self.cursor.execute(action)
                    self.session.invalidate()
                else:
                    plan.state = "completed"
            except Exception as error:  # Preserve the service; expose a concise diagnosis in status.
                plan.state = "failed"
                plan.error = str(error)
            finally:
                with self._lock:
                    self._current = None
                    self._last = plan

    def close(self) -> None:
        self.disarm()
        self._stop.set()
        self._worker.join(timeout=1)
