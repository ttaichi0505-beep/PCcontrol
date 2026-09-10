import time
import unittest

from neai_protocol import Action
from neai_runtime import ControlRuntime


class FakeCursor:
    def __init__(self):
        self.executed = []

    def execute(self, action: Action):
        self.executed.append(action.type)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.cursor = FakeCursor()
        self.runtime = ControlRuntime(cursor=self.cursor)

    def tearDown(self):
        self.runtime.close()

    def test_rejects_plan_until_explicitly_armed(self):
        with self.assertRaises(PermissionError):
            self.runtime.submit_plan({"actions": [{"type": "wait", "durationMs": 0}]})

    def test_runs_armed_plan(self):
        self.runtime.arm()
        self.runtime.submit_plan({"actions": [{"type": "move", "x": 1, "y": 2}]})
        for _ in range(20):
            if self.cursor.executed:
                break
            time.sleep(0.01)
        self.assertEqual(self.cursor.executed, ["move"])
        self.assertEqual(self.runtime.status()["lastPlan"]["state"], "completed")

    def test_intent_input_round_trip(self):
        saved = self.runtime.submit_intent("open the browser")
        received = self.runtime.next_intent()
        self.assertEqual(received.id, saved.id)
        self.assertEqual(received.text, "open the browser")
