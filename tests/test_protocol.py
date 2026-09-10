import unittest

from neai_protocol import ActionValidationError, validate_plan


class ProtocolTests(unittest.TestCase):
    def test_normalizes_a_mouse_only_plan(self):
        actions = validate_plan({"actions": [{"type": "click", "x": 12.4, "y": 30, "button": "left"}]})
        self.assertEqual(actions[0].as_dict(), {"type": "click", "x": 12, "y": 30, "button": "left", "durationMs": 80})

    def test_rejects_keyboard_and_process_actions(self):
        for action_type in ("type", "key", "hotkey", "shell", "window"):
            with self.subTest(action_type=action_type):
                with self.assertRaises(ActionValidationError):
                    validate_plan({"actions": [{"type": action_type, "text": "unsafe"}]})

    def test_requires_coordinates_for_mouse_effects(self):
        with self.assertRaises(ActionValidationError):
            validate_plan({"actions": [{"type": "click", "x": 10}]})

    def test_limits_plan_size(self):
        with self.assertRaises(ActionValidationError):
            validate_plan({"actions": [{"type": "wait", "durationMs": 0}] * 101})
