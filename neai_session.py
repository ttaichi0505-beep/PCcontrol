"""Shared desktop session: one screen view plus live cursor state for human and NeAI."""

from __future__ import annotations

import threading
import time
from typing import Any

from neai_mouse import CursorController
from neai_screen import ScreenCapture


class SharedSession:
    """Keeps the virtual desktop and cursor in sync for a shared observe-act loop."""

    MIN_CAPTURE_INTERVAL_SEC = 0.08

    def __init__(
        self,
        cursor: CursorController,
        screen: ScreenCapture | None = None,
        clock=time.time,
    ) -> None:
        self.cursor = cursor
        self.screen = screen or ScreenCapture()
        self._clock = clock
        self._lock = threading.RLock()
        self._frame_seq = 0
        self._last_capture_at = 0.0
        self._last_frame_meta: dict[str, Any] | None = None

    def invalidate(self) -> None:
        """Hint that the next observer should refresh the shared screen."""
        with self._lock:
            self._last_capture_at = 0.0

    def capture_frame(self, scale: float = 1.0) -> dict[str, Any]:
        with self._lock:
            now = self._clock()
            if now - self._last_capture_at < self.MIN_CAPTURE_INTERVAL_SEC and self._last_frame_meta:
                return dict(self._last_frame_meta)
            frame = self.screen.capture(scale=scale)
            self._frame_seq += 1
            self._last_capture_at = now
            self._last_frame_meta = {
                "seq": self._frame_seq,
                "capturedAt": now,
                "width": frame.width,
                "height": frame.height,
                "scale": frame.scale,
                "bounds": frame.bounds.__dict__,
                "png": frame.png,
            }
            return dict(self._last_frame_meta)

    def snapshot(self, *, scale: float = 1.0, include_image: bool = False) -> dict[str, Any]:
        frame = self.capture_frame(scale=scale)
        cursor = self.cursor.position()
        payload: dict[str, Any] = {
            "mode": "shared_desktop",
            "frameSeq": frame["seq"],
            "capturedAt": frame["capturedAt"],
            "screen": {
                "width": frame["width"],
                "height": frame["height"],
                "scale": frame["scale"],
                "bounds": frame["bounds"],
                "imageUrl": f"/api/screen?scale={frame['scale']}",
            },
            "cursor": {"x": cursor["x"], "y": cursor["y"]},
            "coordinateSpace": "shared_screen_pixels",
        }
        if include_image:
            payload["screen"]["pngBase64"] = __import__("base64").b64encode(frame["png"]).decode("ascii")
        return payload

    def frame_png(self, scale: float = 1.0) -> tuple[bytes, dict[str, Any]]:
        frame = self.capture_frame(scale=scale)
        meta = {
            "seq": frame["seq"],
            "width": frame["width"],
            "height": frame["height"],
            "scale": frame["scale"],
        }
        return frame["png"], meta
