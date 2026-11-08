"""Learning from play: lesson evidence and hold-outs (ledger.py), final reviews, training data (dataset.py)."""
import json
import random
import tempfile
import unittest
from pathlib import Path

from civ5ai import dataset, lessons
from civ5ai.actions import Actions
from civ5ai.ledger import Ledger
from tests.test_lessons import state

LESSONS = ["[general] Shoot with cities.", "[general] Build a worker early.", "[general] Keep happiness up.",
           "[science] Build libraries.", "[general] Settle on rivers.", "[domination] Build an army."]


def snap(turn, score, rival_avg):
    return {**lessons.snapshot(state(turn, score)), "rival_avg_score": rival_avg}


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.dir.name) / "stats.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_hold_out_picks_least_tested_and_needs_enough_lessons(self):
        self.assertEqual(self.ledger.choose_held_out("r1", LESSONS[:3]), [])
        self.ledger.entry(LESSONS[0])["held_out"]["turns"] = 50
        picked = self.ledger.choose_held_out("r1", LESSONS, n=5, rng=random.Random(1))
        self.assertNotIn(LESSONS[0], picked)
        self.assertEqual(len(picked), 5)
        self.assertEqual(Ledger(self.ledger.path).data["runs"]["r1"]["held_out"], picked)  # saved

    def test_periods_credit_used_and_held_out_sides(self):
        applied = lessons.relevant(LESSONS, "science")
        # gap goes from -10 to 0 over 10 turns: +10
        self.ledger.add_period("r1", applied, ["[general] Settle on rivers."], snap(0, 40, 50), snap(10, 60, 60), 3)
        used = self.ledger.data["lessons"]["build libraries."]["used"]
        held = self.ledger.data["lessons"]["settle on rivers."]["held_out"]
        self.assertEqual((used["turns"], used["gap_change"], used["failures"]), (10, 10, 3))
        self.assertEqual(held["turns"], 10)
        self.assertNotIn("build an army.", self.ledger.data["lessons"])  # didn't apply to a science game
        self.assertIn("used 10 turns, score vs rivals +10.0 per 10 turns", self.ledger.evidence(LESSONS[3]))
        self.assertIn("held out 10 turns", self.ledger.evidence(LESSONS[4]))
        self.assertEqual(self.ledger.evidence("[general] Never seen."), "")

    def test_finished_games_show_in_evidence(self):
        self.ledger.add_period("r1", [LESSONS[0]], [], snap(0, 40, 50), snap(10, 60, 60), 0)
        self.ledger.finish_run("r1", {"over": True, "won": True, "rank": 1, "players": 4})
        self.ledger.add_period("r2", [LESSONS[0]], [], snap(0, 40, 50), snap(10, 60, 60), 0)
        self.ledger.finish_run("r2", {"stopped": True, "rank": 3, "players": 4})  # not finished: not counted
        self.assertIn("1 finished game(s), 1 won, average place in the top 25%", self.ledger.evidence(LESSONS[0]))

    def test_rewording_keeps_stats_only_for_same_words(self):
        self.ledger.add_period("r1", ["[general] Shoot  with Cities."], [], snap(0, 1, 1), snap(5, 1, 1), 0)
        self.assertTrue(self.ledger.evidence("[science] shoot with cities."))


class HeldOutLessonsTest(unittest.TestCase):
    def test_held_out_lessons_are_hidden_from_turns_and_reviews_but_kept(self):
        held = ["[general] Settle on rivers."]
        self.assertNotIn("rivers", lessons.for_prompt(LESSONS, "science", held))
        text = lessons.Period(state(0, 10)).describe(state(10, 20), "Target: science victory.", LESSONS, held_out=held,
                                                    evidence=lambda x: "used 40 turns" if "libraries" in x else "")
        self.assertNotIn("rivers", text)
        self.assertIn("4. [science] Build libraries.\n     evidence: used 40 turns", text)
        merged = lessons.merge(LESSONS, ["[general] Shoot with cities."], "science", held)
        self.assertIn("[general] Settle on rivers.", merged)
        self.assertIn("[domination] Build an army.", merged)
        self.assertNotIn("[science] Build libraries.", merged)


class FinalReviewTest(unittest.TestCase):
    def test_game_over_and_whole_run(self):
        start = snap(0, 10, 12)
        s = state(200, 900)
        s["rivals"] = {2: {"score": 950}, 3: {"score": 400}}
        text = lessons.Period(state(190, 880)).describe(
            s, "Target: science victory.", LESSONS, run_start=start,
            outcome={"over": True, "won": False, "victory": "VICTORY_DOMINATION", "winner": "Rome"})
        self.assertIn("Whole run: turns 0 to 200; score 10 -> 900", text)
        self.assertIn("THE GAME IS OVER: you LOST (domination victory by Rome)", text)
        self.assertEqual(lessons.standing(s), (2, 3))

    def test_stopped_run_gives_standing(self):
        s = state(50, 100)
        s["rivals"] = {2: {"score": 150}}
        text = lessons.Period(state(40, 90)).describe(s, "", [], run_start=snap(0, 5, 5))
        self.assertIn("you are in place 2 of 2 by score", text)


class GameOverTest(unittest.TestCase):
    class Tuner:
        def __init__(self, lines):
            self.lines = lines

        def run(self, lua, state="InGame", timeout=5):
            return self.lines

    def check(self, lines):
        a = Actions.__new__(Actions)
        a.t = self.Tuner(lines)
        return a.game_over()

    def test_parses_win_loss_and_elimination(self):
        self.assertIsNone(self.check([]))
        self.assertEqual(self.check(["GO\t1\t1\tVICTORY_SPACE_RACE\tSweden"]),
                         {"over": True, "won": True, "victory": "VICTORY_SPACE_RACE", "winner": "Sweden"})
        self.assertFalse(self.check(["GO\t3\t1\tVICTORY_DOMINATION\tRome"])["won"])
        self.assertEqual(self.check(["DEAD"])["won"], False)


def turn_record(log, turn, score, rival, error=False, silent=False):
    msgs = [{"role": "user", "content": f"Turn {turn} state"}]
    if silent:
        msgs.append({"role": "assistant", "content": "thinking..."})
    msgs.append({"role": "assistant", "content": "", "thinking": "hidden",
                 "tool_calls": [{"function": {"name": "set_research", "arguments": {"tech": "TECH_POTTERY"}}}]})
    msgs.append({"role": "tool", "tool_name": "set_research", "content": "error: no" if error else "ok: researching"})
    msgs.append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "end_turn", "arguments": {}}}]})
    msgs.append({"role": "tool", "tool_name": "end_turn", "content": "ok: turn ended"})
    log.turn(turn, "qwen2.5:14b", snap(turn, score, rival), msgs)


class DatasetTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.log = dataset.TrainLog(self.dir.name, "game-1", "SYSTEM PROMPT")

    def tearDown(self):
        self.dir.cleanup()

    def test_keeps_clean_turns_with_good_outcomes(self):
        # gap (score - rivals): t0 -10, t1 -10, t2 -5, t3 -20 ... later turns to judge against
        for turn, score, rival, err, silent in [(0, 40, 50, False, False), (1, 40, 50, True, False),
                                                (2, 45, 50, False, True), (3, 30, 50, False, False),
                                                (10, 60, 50, False, False), (11, 60, 50, False, False),
                                                (12, 60, 50, False, False), (13, 40, 50, False, False)]:
            turn_record(self.log, turn, score, rival, err, silent)
        examples, report = dataset.build(self.dir.name, [{"name": "t"}], horizon=10, min_gain=0)
        # t0: -10 -> +10 = +20 kept; t1 errors; t2 silent; t3: -20 -> -10 = +10 kept; t10+ can't be judged
        self.assertEqual((report["kept"], report["errors"], report["silent"], report["no_outcome"]), (2, 1, 1, 4))
        ex = examples[0]
        self.assertEqual(ex["messages"][0], {"role": "system", "content": "SYSTEM PROMPT"})
        self.assertEqual(ex["messages"][2]["tool_calls"][0]["function"],
                         {"name": "set_research", "arguments": {"tech": "TECH_POTTERY"}})
        self.assertNotIn("thinking", json.dumps(ex))
        self.assertEqual(ex["messages"][3], {"role": "tool", "name": "set_research", "content": "ok: researching"})
        self.assertEqual(ex["tools"], [{"name": "t"}])

        none, report = dataset.build(self.dir.name, [], min_gain=None)
        self.assertEqual(report["kept"], 6)  # every clean, finished turn
        high, report = dataset.build(self.dir.name, [], horizon=10, min_gain=15)
        self.assertEqual((report["kept"], report["low_gain"]), (1, 1))


if __name__ == "__main__":
    unittest.main()


class AgentReviewTest(unittest.TestCase):
    """A review through the agent: credits evidence, keeps held-out lessons, records a finished game."""

    def setUp(self):
        from unittest import mock
        from civ5ai.agent import Agent
        self.dir = tempfile.TemporaryDirectory()
        d = Path(self.dir.name)
        self.patches = [mock.patch.object(lessons, "LESSONS_FILE", d / "lessons.md")]
        for p in self.patches:
            p.start()
        a = Agent.__new__(Agent)
        a.events, a.records = [], []
        a.event = lambda kind, text="", **data: a.events.append((kind, text, data))
        a.record = lambda **e: a.records.append(e)
        a.model, a.plan, a.run, a.lessons_every = "m", "Target: science victory.", "run-1", 10
        a.lessons, a.held_out = list(LESSONS), ["[general] Settle on rivers."]
        a.ledger = Ledger(d / "stats.json")
        a.period, a.run_start, a.game_result = lessons.Period(state(0, 40)), snap(0, 40, 50), None
        self.agent = a
        self.chat = mock.patch("civ5ai.agent.chat", lambda model, messages, tools=None: {
            "tool_calls": [{"function": {"name": "save_lessons", "arguments": {"lessons": [
                "[general] Shoot with cities.", "[science] Beeline Writing for libraries."]}}}]})
        self.chat.start()
        self.prompts = []

    def tearDown(self):
        self.chat.stop()
        for p in self.patches:
            p.stop()
        self.dir.cleanup()

    def test_game_over_review(self):
        a = self.agent
        s = state(20, 90)
        s["rivals"] = {2: {"score": 60}}
        a.finish_game(s, {"over": True, "won": True, "victory": "VICTORY_SPACE_RACE", "winner": "Sweden"})
        review = next(r["review"] for r in a.records if "review" in r)
        self.assertIn("THE GAME IS OVER: you WON (space_race victory by Sweden)", review)
        self.assertIn("Whole run: turns 0 to 20", review)
        self.assertNotIn("rivers", review)  # held out: not shown to the reviewer...
        self.assertIn("[general] Settle on rivers.", a.lessons)  # ...and not lost
        self.assertIn("[domination] Build an army.", a.lessons)  # other victories kept
        self.assertIn("[science] Beeline Writing for libraries.", a.lessons)
        self.assertEqual(a.ledger.data["runs"]["run-1"]["outcome"]["won"], True)
        self.assertEqual(a.ledger.data["lessons"]["settle on rivers."]["held_out"]["turns"], 20)
        self.assertIn("1 finished game(s), 1 won", a.ledger.evidence("[general] Shoot with cities."))
        self.assertEqual(a.game_result["victory"], "VICTORY_SPACE_RACE")
