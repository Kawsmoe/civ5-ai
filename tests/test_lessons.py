"""lessons.md: saving, loading, capping, and the review prompt."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from civ5ai import lessons
from civ5ai.agent import extract_text_tool_calls


def state(turn, score, cities=1, gold=10):
    return {"turn": turn, "me": {"score": score, "techs": 3, "policies": 0}, "rivals": {},
            "cities": {i: {"pop": 2} for i in range(cities)}, "units": {},
            "gold": gold, "gold_rate": 2, "happiness": 5, "science": 4, "culture": 1, "faith": 0}


class LessonsFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(lessons, "LESSONS_FILE", Path(self.dir.name) / "lessons.md")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.dir.cleanup()

    def test_round_trip_dedupes_and_caps(self):
        self.assertEqual(lessons.load(), [])
        many = ["Research Calendar early when the capital has jungle luxuries."] * 2 + [f"lesson {i}" for i in range(30)]
        kept = lessons.save(many, "turn 10")
        self.assertEqual(len(kept), lessons.MAX_LESSONS)
        self.assertEqual(kept[0], many[0])
        self.assertEqual(kept.count(many[0]), 1)
        self.assertEqual(lessons.load(), kept)

    def test_hand_edited_file_is_read(self):
        lessons.LESSONS_FILE.write_text("# my notes\n\n* Keep a warrior home.\n- Shoot with cities.\nnot a lesson\n")
        self.assertEqual(lessons.load(), ["Keep a warrior home.", "Shoot with cities."])


class ReviewPromptTest(unittest.TestCase):
    def test_describes_changes_failures_and_losses(self):
        period = lessons.Period(state(10, 50))
        period.failure("build_improvement", "error: cannot build BUILD_FARM at (1,2): needs TECH_BRONZE_WORKING")
        period.failure("build_improvement", "error: another")
        period.silent_replies = 2
        period.lost.append("UNIT_WARRIOR near (3,4) around turn 15")
        text = period.describe(state(20, 80, cities=2), "Expand.", ["Shoot with cities."])
        for expected in ["Turns 10 to 20.", "score: 50 -> 80", "cities: 1 -> 2", "UNIT_WARRIOR near (3,4)",
                         "build_improvement x2: error: cannot build BUILD_FARM", "called no tools: 2",
                         "1. Shoot with cities."]:
            self.assertIn(expected, text)
        self.assertNotIn("gold:", text)  # unchanged numbers are left out

    def test_save_lessons_written_as_text_is_picked_up(self):
        calls = extract_text_tool_calls('{"name": "save_lessons", "arguments": {"lessons": ["a", "b"]}}',
                                        tools=[lessons.SAVE_TOOL])
        self.assertEqual(calls[0]["function"]["arguments"]["lessons"], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
