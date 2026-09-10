"""Windows cursor driver. All UI effects are issued at the real pointer position."""

from __future__ import annotations

import ctypes
import os
import time
from dataclasses import dataclass
from typing import Protocol

from neai_protocol import Action


MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


@dataclass(frozen=True)
class ScreenBounds:
    left: int
    top: int
    width: int
    height: int

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.left + self.width and self.top <= y < self.top + self.height


class CursorNative(Protocol):
    def bounds(self) -> ScreenBounds: ...

    def get_cursor_pos(self) -> tuple[int, int]: ...

    def set_cursor_pos(self, x: int, y: int) -> None: ...

    def mouse_event(self, flags: int, data: int = 0) -> None: ...


class User32CursorNative:
    """Thin wrapper around user32; no application-specific automation APIs."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("NeAI Cursor Control requires Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.GetCursorPos.argtypes = (ctypes.POINTER(ctypes.wintypes.POINT),)
        self.user32.GetCursorPos.restype = ctypes.c_bool
        self.user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
        self.user32.SetCursorPos.restype = ctypes.c_bool
        self.user32.mouse_event.argtypes = (
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_int32,
            ctypes.c_size_t,
        )

    def bounds(self) -> ScreenBounds:
        return ScreenBounds(
            self.user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
            self.user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
            self.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
            self.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
        )

    def get_cursor_pos(self) -> tuple[int, int]:
        point = ctypes.wintypes.POINT()
        if not self.user32.GetCursorPos(ctypes.byref(point)):
            raise ctypes.WinError(ctypes.get_last_error())
        return point.x, point.y

    def set_cursor_pos(self, x: int, y: int) -> None:
        if not self.user32.SetCursorPos(x, y):
            raise ctypes.WinError(ctypes.get_last_error())

    def mouse_event(self, flags: int, data: int = 0) -> None:
        self.user32.mouse_event(flags, 0, 0, data, 0)


class CursorController:
    """Executes only physical cursor movement and mouse button/wheel events."""

    def __init__(self, native: CursorNative | None = None, sleep=time.sleep) -> None:
        self.native = native or User32CursorNative()
        self.sleep = sleep

    def _check_position(self, x: int, y: int) -> None:
        bounds = self.native.bounds()
        if not bounds.contains(x, y):
            raise ValueError(
                f"({x}, {y}) is outside the current virtual desktop "
                f"({bounds.left}, {bounds.top}, {bounds.width}x{bounds.height})"
            )

    def move_to(self, x: int, y: int, duration_ms: int = 0) -> None:
        self._check_position(x, y)
        # SetCursorPos moves the visible, actual Windows pointer. The small sequence
        # makes planned movement observable instead of teleporting for timed moves.
        if duration_ms <= 0:
            self.native.set_cursor_pos(x, y)
            return
        start_x, start_y = self.native.get_cursor_pos()
        steps = min(120, max(1, round(duration_ms / 16)))
        for step in range(1, steps + 1):
            fraction = step / steps
            self.native.set_cursor_pos(
                round(start_x + (x - start_x) * fraction),
                round(start_y + (y - start_y) * fraction),
            )
            if step < steps:
                self.sleep(duration_ms / steps / 1000)

    def _button(self, button: str, down: bool) -> None:
        self.native.mouse_event(BUTTON_FLAGS[button][0 if down else 1])

    def click(self, x: int, y: int, button: str, duration_ms: int, double: bool = False) -> None:
        self.move_to(x, y, duration_ms)
        repetitions = 2 if double else 1
        for index in range(repetitions):
            self._button(button, True)
            self.sleep(0.04)
            self._button(button, False)
            if index + 1 < repetitions:
                self.sleep(0.07)

    def drag(self, action: Action) -> None:
        data = action.data
        self.move_to(data["fromX"], data["fromY"], 80)
        self._button(data["button"], True)
        try:
            self.move_to(data["toX"], data["toY"], data["durationMs"])
        finally:
            self._button(data["button"], False)

    def scroll(self, x: int, y: int, delta: int) -> None:
        self.move_to(x, y, 80)
        self.native.mouse_event(MOUSEEVENTF_WHEEL, delta)

    def position(self) -> dict[str, int]:
        x, y = self.native.get_cursor_pos()
        bounds = self.native.bounds()
        return {"x": x, "y": y, "bounds": bounds.__dict__}

    def execute(self, action: Action) -> None:
        data = action.data
        if action.type == "move":
            self.move_to(data["x"], data["y"], data["durationMs"])
        elif action.type == "click":
            self.click(data["x"], data["y"], data["button"], data["durationMs"])
        elif action.type == "double_click":
            self.click(data["x"], data["y"], data["button"], data["durationMs"], double=True)
        elif action.type == "drag":
            self.drag(action)
        elif action.type == "scroll":
            self.scroll(data["x"], data["y"], data["delta"])
        elif action.type == "wait":
            self.sleep(data["durationMs"] / 1000)
        else:  # validated plans cannot reach this, retained as a final guard.
            raise ValueError(f"unsupported mouse-only action: {action.type}")
