import unittest

from neai_mouse import ScreenBounds
from neai_protocol import Action
from neai_session import SharedSession


class FakeCursor:
    def __init__(self):
        self.x = 10
        self.y = 20

    def position(self):
        return {"x": self.x, "y": self.y, "bounds": ScreenBounds(0, 0, 100, 50).__dict__}

    def execute(self, action: Action):
        if action.type == "move":
            self.x = action.data["x"]
            self.y = action.data["y"]


class FakeScreen:
    calls = 0

    def capture(self, scale: float = 1.0):
        FakeScreen.calls += 1
        from neai_screen import ScreenFrame

        return ScreenFrame(
            png=b"\x89PNG",
            width=100,
            height=50,
            bounds=ScreenBounds(0, 0, 100, 50),
            scale=scale,
        )


class SessionTests(unittest.TestCase):
    def setUp(self):
        FakeScreen.calls = 0
        self.session = SharedSession(FakeCursor(), screen=FakeScreen(), clock=lambda: 1000.0)

    def test_snapshot_describes_shared_desktop(self):
        snapshot = self.session.snapshot(scale=0.5)
        self.assertEqual(snapshot["mode"], "shared_desktop")
        self.assertEqual(snapshot["screen"]["width"], 100)
        self.assertEqual(snapshot["cursor"], {"x": 10, "y": 20})
        self.assertEqual(snapshot["coordinateSpace"], "shared_screen_pixels")

    def test_capture_is_rate_limited(self):
        self.session.snapshot()
        self.session.snapshot()
        self.assertEqual(FakeScreen.calls, 1)
        self.session.invalidate()
        self.session.snapshot()
        self.assertEqual(FakeScreen.calls, 2)
