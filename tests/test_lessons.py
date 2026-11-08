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
        self.assertEqual(kept[0], "[general] " + many[0])
        self.assertEqual(kept.count(kept[0]), 1)
        self.assertEqual(lessons.load(), kept)

    def test_hand_edited_file_is_read(self):
        lessons.LESSONS_FILE.write_text("# my notes\n\n* Keep a warrior home.\n- Shoot with cities.\nnot a lesson\n")
        self.assertEqual(lessons.load(), ["Keep a warrior home.", "Shoot with cities."])

    def test_save_normalises_tags_and_caps_per_tag(self):
        kept = lessons.save(["Shoot with cities.", "[Scientific] Build libraries.", "[conquest] Build an army.",
                             "[nonsense] Keep a warrior home."]
                            + [f"[science] tip {i}" for i in range(20)])
        self.assertEqual(kept[:4], ["[general] Shoot with cities.", "[science] Build libraries.",
                                    "[domination] Build an army.", "[general] Keep a warrior home."])
        self.assertEqual(sum(lessons.split_tag(x)[0] == "science" for x in kept), lessons.MAX_LESSONS)
        self.assertEqual(lessons.load(), kept)


class VictoryTagTest(unittest.TestCase):
    ALL = ["[general] Shoot with cities.", "[domination] Build an army before expanding.",
           "[science] Build libraries.", "Untagged tip."]

    def test_victory_of_plan(self):
        self.assertEqual(lessons.victory_of("Target: science victory. Expand to 4 cities."), "science")
        self.assertEqual(lessons.victory_of("Target - a Domination win."), "domination")
        self.assertEqual(lessons.victory_of("Go for a cultural victory with wonders."), "culture")
        self.assertIsNone(lessons.victory_of("Expand and explore."))
        self.assertIsNone(lessons.victory_of(""))

    def test_prompt_shows_only_this_victory(self):
        text = lessons.for_prompt(self.ALL, "science")
        self.assertIn("- Build libraries.", text)
        self.assertIn("- Shoot with cities.", text)
        self.assertIn("- Untagged tip.", text)
        self.assertNotIn("army", text)
        self.assertNotIn("[", text)
        self.assertNotIn("libraries", lessons.for_prompt(self.ALL, None))

    def test_review_keeps_other_victories(self):
        shown = lessons.relevant(self.ALL, "science")
        self.assertNotIn("[domination] Build an army before expanding.", shown)
        merged = lessons.merge(self.ALL, ["[general] Shoot with cities.", "[science] Beeline Writing."], "science")
        self.assertEqual(merged, ["[general] Shoot with cities.", "[science] Beeline Writing.",
                                  "[domination] Build an army before expanding."])

    def test_review_prompt_hides_other_victories(self):
        text = lessons.Period(state(10, 50)).describe(state(20, 60), "Target: science victory.", self.ALL)
        self.assertIn("[science] Build libraries.", text)
        self.assertNotIn("army", text)
        self.assertIn("tag each lesson [general] or [science]", text)


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

    def test_lessons_listed_as_plain_text_are_picked_up(self):
        reply = {"content": "Here are my lessons:\n1. [general] Shoot with cities.\n- [science] Build libraries.\n"
                            "Some closing words [not a lesson]."}
        self.assertEqual(lessons.from_reply(reply, extract_text_tool_calls),
                         ["[general] Shoot with cities.", "[science] Build libraries."])
        self.assertIsNone(lessons.from_reply({"content": "I think I did well."}, extract_text_tool_calls))

    def test_save_lessons_written_as_text_is_picked_up(self):
        calls = extract_text_tool_calls('{"name": "save_lessons", "arguments": {"lessons": ["a", "b"]}}',
                                        tools=[lessons.SAVE_TOOL])
        self.assertEqual(calls[0]["function"]["arguments"]["lessons"], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
