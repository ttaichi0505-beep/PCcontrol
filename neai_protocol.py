"""Strict, mouse-only protocol validation for NeAI Cursor Control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ActionValidationError(ValueError):
    """Raised when a plan cannot be represented by the mouse-only protocol."""


@dataclass(frozen=True)
class Action:
    type: str
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, **self.data}


ALLOWED_ACTIONS = frozenset({"move", "click", "double_click", "drag", "scroll", "wait"})
MAX_ACTIONS = 100
MAX_DURATION_MS = 5_000
MAX_WAIT_MS = 10_000
MAX_SCROLL_DELTA = 12_000


def _number(value: Any, name: str, *, minimum: float = -100_000, maximum: float = 100_000) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ActionValidationError(f"{name} must be a number")
    if not minimum <= value <= maximum:
        raise ActionValidationError(f"{name} must be between {minimum:g} and {maximum:g}")
    return round(value)


def _duration(raw: dict[str, Any], default: int = 0) -> int:
    value = raw.get("durationMs", default)
    return _number(value, "durationMs", minimum=0, maximum=MAX_DURATION_MS)


def _coordinates(raw: dict[str, Any], x_name: str = "x", y_name: str = "y") -> dict[str, int]:
    return {
        x_name: _number(raw.get(x_name), x_name),
        y_name: _number(raw.get(y_name), y_name),
    }


def _button(raw: dict[str, Any]) -> str:
    button = raw.get("button", "left")
    if button not in {"left", "right", "middle"}:
        raise ActionValidationError("button must be left, right, or middle")
    return button


def validate_plan(payload: Any) -> list[Action]:
    """Validate and normalize a plan.

    Keyboard, shell, window-manager, and arbitrary action types are rejected here.
    The executor additionally checks every coordinate against the current virtual
    desktop immediately before it moves the real cursor.
    """

    if not isinstance(payload, dict):
        raise ActionValidationError("plan must be a JSON object")
    raw_actions = payload.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        raise ActionValidationError("actions must be a non-empty array")
    if len(raw_actions) > MAX_ACTIONS:
        raise ActionValidationError(f"a plan may contain at most {MAX_ACTIONS} actions")

    actions: list[Action] = []
    total_pause_ms = 0
    for index, raw in enumerate(raw_actions):
        if not isinstance(raw, dict):
            raise ActionValidationError(f"actions[{index}] must be an object")
        action_type = raw.get("type")
        if action_type not in ALLOWED_ACTIONS:
            raise ActionValidationError(
                f"actions[{index}].type is not allowed; only mouse-only actions are accepted"
            )

        if action_type == "move":
            data = _coordinates(raw)
            data["durationMs"] = _duration(raw, 150)
            total_pause_ms += data["durationMs"]
        elif action_type in {"click", "double_click"}:
            data = _coordinates(raw)
            data["button"] = _button(raw)
            data["durationMs"] = _duration(raw, 80)
            total_pause_ms += data["durationMs"]
        elif action_type == "drag":
            data = _coordinates(raw, "fromX", "fromY")
            data.update(_coordinates(raw, "toX", "toY"))
            data["button"] = _button(raw)
            data["durationMs"] = _duration(raw, 300)
            total_pause_ms += data["durationMs"]
        elif action_type == "scroll":
            data = _coordinates(raw)
            data["delta"] = _number(
                raw.get("delta"), "delta", minimum=-MAX_SCROLL_DELTA, maximum=MAX_SCROLL_DELTA
            )
            if data["delta"] == 0:
                raise ActionValidationError("delta must not be zero")
        else:  # wait
            data = {
                "durationMs": _number(
                    raw.get("durationMs"), "durationMs", minimum=0, maximum=MAX_WAIT_MS
                )
            }
            total_pause_ms += data["durationMs"]
        actions.append(Action(action_type, data))

    if total_pause_ms > 30_000:
        raise ActionValidationError("combined move/wait duration may not exceed 30000ms")
    return actions
