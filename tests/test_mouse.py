import unittest

from neai_mouse import CursorController, ScreenBounds
from neai_protocol import Action


class FakeNative:
    def __init__(self):
        self.events = []

    def bounds(self):
        return ScreenBounds(0, 0, 1920, 1080)

    def get_cursor_pos(self):
        for event in reversed(self.events):
            if event[0] == "move":
                return event[1], event[2]
        return 0, 0

    def set_cursor_pos(self, x, y):
        self.events.append(("move", x, y))

    def mouse_event(self, flags, data=0):
        self.events.append(("mouse", flags, data))


class MouseTests(unittest.TestCase):
    def test_click_moves_visible_cursor_before_button_events(self):
        native = FakeNative()
        mouse = CursorController(native=native, sleep=lambda _: None)
        mouse.execute(Action("click", {"x": 100, "y": 200, "button": "left", "durationMs": 0}))
        self.assertEqual(native.events[0], ("move", 100, 200))
        self.assertEqual(native.events[1][0], "mouse")

    def test_scroll_moves_cursor_to_target_first(self):
        native = FakeNative()
        mouse = CursorController(native=native, sleep=lambda _: None)
        mouse.execute(Action("scroll", {"x": 500, "y": 600, "delta": -120}))
        moves = [event for event in native.events if event[0] == "move"]
        self.assertEqual(moves[-1], ("move", 500, 600))
        self.assertEqual(native.events[-1][0], "mouse")

    def test_timed_move_interpolates_from_current_cursor(self):
        native = FakeNative()
        native.events.append(("move", 10, 20))
        mouse = CursorController(native=native, sleep=lambda _: None)
        mouse.move_to(110, 220, duration_ms=32)
        moves = [event for event in native.events if event[0] == "move"]
        self.assertGreater(len(moves), 1)
        self.assertEqual(moves[-1], ("move", 110, 220))

    def test_rejects_coordinate_outside_virtual_desktop(self):
        mouse = CursorController(native=FakeNative(), sleep=lambda _: None)
        with self.assertRaises(ValueError):
            mouse.move_to(1920, 5)
