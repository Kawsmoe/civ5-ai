"""Unit tracking between turns, without the game or Ollama."""
import unittest

from civ5ai.agent import Agent


def state(turn, *units):
    return {"turn": turn, "units": {u[0]: {"id": u[0], "type": u[1], "x": u[2], "y": u[3]} for u in units}}


class UnitTrackingTest(unittest.TestCase):
    def setUp(self):
        self.agent = Agent.__new__(Agent)  # skip connecting to the game
        self.agent.known_units, self.agent.lost_units = {}, {}

    def test_lost_units_are_reported_once_and_remembered(self):
        a = self.agent
        self.assertEqual(a.track_units(state(29, (32768, "UNIT_SPEARMAN", 13, 71), (40961, "UNIT_WORKER", 19, 66))), {})
        lost = a.track_units(state(30, (40961, "UNIT_WORKER", 19, 66)))
        self.assertEqual(lost, {32768: ("UNIT_SPEARMAN", 13, 71)})
        self.assertEqual(a.track_units(state(31, (40961, "UNIT_WORKER", 19, 66))), {})

        msg = a.unknown_unit_message({"unit_id": 32768}, state(31, (40961, "UNIT_WORKER", 19, 66)))
        self.assertIn("UNIT_SPEARMAN", msg)
        self.assertIn("no longer exists", msg)
        self.assertIn("40961 UNIT_WORKER", msg)
        self.assertIsNone(a.unknown_unit_message({"unit_id": 99}, state(31)))


if __name__ == "__main__":
    unittest.main()


class ProductionGuardTest(unittest.TestCase):
    def setUp(self):
        self.agent = Agent.__new__(Agent)
        self.agent.changed_turn = {}

    def snapshot(self, turn, workers, producing="Worker"):
        units = {i: {"id": i, "type": "UNIT_WORKER"} for i in range(workers)}
        return {"turn": turn, "research": "TECH_POTTERY", "units": units,
                "cities": {8192: {"id": 8192, "name": "Berlin", "producing": producing}}}

    def test_switching_allowed_unless_just_changed(self):
        a, s = self.agent, self.snapshot(20, 1)
        self.assertFalse(a.recently_changed(8192, s))
        a.changed_turn[8192] = 19
        self.assertTrue(a.recently_changed(8192, s))
        self.assertFalse(a.recently_changed(8192, self.snapshot(23, 1)))

    def test_worker_limit(self):
        a = self.agent
        self.assertFalse(a.enough_workers(self.snapshot(20, 1)))
        self.assertTrue(a.enough_workers(self.snapshot(20, 2)))


class TextToolCallTest(unittest.TestCase):
    def test_extracts_calls_written_as_text(self):
        from civ5ai.agent import extract_text_tool_calls
        text = ('I will research pottery.\n<tool_call>\n{"name": "set_research", "arguments": {"tech": "TECH_POTTERY"}}\n'
                '</tool_call>\n```json\n{"name": "end_turn", "arguments": "{}"}\n```')
        calls = extract_text_tool_calls(text)
        self.assertEqual([c["function"]["name"] for c in calls], ["set_research", "end_turn"])
        self.assertEqual(calls[0]["function"]["arguments"], {"tech": "TECH_POTTERY"})

    def test_ignores_plain_text_and_unknown_names(self):
        from civ5ai.agent import extract_text_tool_calls
        self.assertEqual(extract_text_tool_calls("1. **Continue Research**: keep going {not json}"), [])
        self.assertEqual(extract_text_tool_calls('{"name": "launch_nukes", "arguments": {}}'), [])
