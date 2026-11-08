"""Evidence for lessons: how play went while each lesson was in use, and while it was held out.

lessons.md says what the model believes; lesson_stats.json records what happened.
After every review period, each lesson that applied to the game gets that period's
numbers added to its "used" or "held_out" side:

  turns       turns in periods where it applied
  gap_turns   turns of those where the score gap to rivals could be measured
  gap_change  sum of (your score - rivals' average score) change over those turns
  failures    failed tool calls in those periods

At the start of each run a lesson or two is held out (left out of the prompt) so
that, over many runs, "used" can be compared with "held out". With one game at a
time this is a rough signal, and the review prompt says so.

Each run also records its outcome (won/lost, rank) once known, and every lesson
used in it gets that outcome in its "runs" list.
"""
import json
import random
from datetime import date
from pathlib import Path

from . import lessons as lessons_mod

STATS_FILE = Path(__file__).resolve().parent.parent / "lesson_stats.json"
MIN_LESSONS_TO_HOLD_OUT = 5  # with fewer, leaving one out costs too much


def key(lesson):
    """Stats follow the lesson's words, not its tag or spacing."""
    return " ".join(lessons_mod.split_tag(lesson)[1].lower().split())


def _side():
    return {"periods": 0, "turns": 0, "gap_turns": 0, "gap_change": 0.0, "failures": 0}


class Ledger:
    def __init__(self, path=None):
        self.path = Path(path or STATS_FILE)
        self.data = {"lessons": {}, "runs": {}}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                pass  # a broken file is rebuilt from scratch rather than stopping the game
        self.data.setdefault("lessons", {})
        self.data.setdefault("runs", {})

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")

    def entry(self, lesson):
        e = self.data["lessons"].setdefault(key(lesson), {
            "text": lesson, "added": date.today().isoformat(), "used": _side(), "held_out": _side(), "runs": []})
        e["text"] = lesson
        return e

    # --- hold-out ---------------------------------------------------------------------

    def choose_held_out(self, run, lessons, n=1, rng=random):
        """Pick lessons to leave out for this run: the ones with the least held-out evidence."""
        if n <= 0 or len(lessons) < MIN_LESSONS_TO_HOLD_OUT:
            picked = []
        else:
            least = sorted(lessons, key=lambda x: (self.entry(x)["held_out"]["turns"], rng.random()))
            picked = least[:n]
        self.data["runs"].setdefault(run, {"started": date.today().isoformat()})["held_out"] = picked
        self.save()
        return picked

    # --- evidence ---------------------------------------------------------------------

    def add_period(self, run, applied, held_out, start, end, failures):
        """Credit one review period to the lessons that applied (general + this game's victory)."""
        turns = end["turn"] - start["turn"]
        if turns <= 0:
            return
        gap = None
        if None not in (start["score"], start["rival_avg_score"], end["score"], end["rival_avg_score"]):
            gap = (end["score"] - end["rival_avg_score"]) - (start["score"] - start["rival_avg_score"])
        held = {key(x) for x in held_out}
        for lesson in applied:
            side = self.entry(lesson)["held_out" if key(lesson) in held else "used"]
            side["periods"] += 1
            side["turns"] += turns
            side["failures"] += failures
            if gap is not None:
                side["gap_turns"] += turns
                side["gap_change"] += gap
            if key(lesson) not in held:
                runs = self.entry(lesson)["runs"]
                if not any(r.get("run") == run for r in runs):
                    runs.append({"run": run})
        self.save()

    def finish_run(self, run, outcome):
        """Record a run's outcome on the run and on every lesson used in it."""
        self.data["runs"].setdefault(run, {})["outcome"] = outcome
        for e in self.data["lessons"].values():
            for r in e["runs"]:
                if r.get("run") == run:
                    r.update(outcome)
        self.save()

    def evidence(self, lesson):
        """One line for the review prompt, or "" if there is nothing yet."""
        e = self.data["lessons"].get(key(lesson))
        if not e:
            return ""

        def rate(side):
            if not side["gap_turns"]:
                return f"{side['turns']} turns"
            per10 = side["gap_change"] / side["gap_turns"] * 10
            return f"{side['turns']} turns, score vs rivals {per10:+.1f} per 10 turns"

        parts = []
        if e["used"]["turns"]:
            parts.append("used " + rate(e["used"]))
        if e["held_out"]["turns"]:
            parts.append("held out " + rate(e["held_out"]))
        done = [r for r in e["runs"] if "won" in r]
        if done:
            won = sum(1 for r in done if r["won"])
            ranks = [r["rank"] / r["players"] for r in done if r.get("rank") and r.get("players")]
            parts.append(f"{len(done)} finished game(s), {won} won"
                         + (f", average place in the top {100 * sum(ranks) / len(ranks):.0f}%" if ranks else ""))
        return "; ".join(parts)
