"""Lessons the model writes about its own play, kept across games.

The model's weights never change, so this is how it "learns": every few turns
(and when a run ends) the agent shows it hard facts about how those turns went,
it rewrites a short list of lessons, and that list goes into its prompt from
then on. lessons.md is plain Markdown: read it, edit it or delete it freely.
"""
from collections import Counter
from datetime import date
from pathlib import Path

LESSONS_FILE = Path(__file__).resolve().parent.parent / "lessons.md"
MAX_LESSONS = 15
MAX_LESSON_CHARS = 200
# ideas from other Civ games that small models mix in; a lesson using them is wrong for Civ V
NOT_CIV5 = ("amenit", "district", "builder charge", "loyalty", "housing", "governor")

REVIEW_SYSTEM = """You are reviewing your own play of Civilization V (Brave New World) to get better at it. You keep a short list of lessons that you will see every turn in this and future games.

Good lessons are short, concrete and general: they say what to do or avoid and when, and they would still help on a different map, with a different civ. Bad lessons mention specific coordinates or unit ids, repeat the game's basic rules, or are vague ("play better").

Most lessons should be about strategy: expansion, what to build and research, growth, happiness, economy, combat, diplomacy. Failed tool calls mostly show interface mistakes; turn them into at most three lessons, and only when they change how you play. This is Civilization V: don't use ideas from other Civ games (amenities, districts, builder charges, loyalty, housing).

Base lessons on the facts you are given, not on guesses. Keep lessons that still hold, rewrite ones the facts contradict, drop ones that turned out wrong or useless, and add what these turns taught you. Then call save_lessons with the complete new list."""

SAVE_TOOL = {"type": "function", "function": {
    "name": "save_lessons",
    "description": f"Save the complete updated list of lessons (at most {MAX_LESSONS}).",
    "parameters": {"type": "object", "required": ["lessons"], "properties": {
        "lessons": {"type": "array", "items": {"type": "string"},
                    "description": "Each lesson one short sentence."}}}}}


def load():
    """The current lessons, as a list of strings ([] if there are none yet)."""
    if not LESSONS_FILE.exists():
        return []
    lessons = []
    for line in LESSONS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(("- ", "* ")):
            lessons.append(line[2:].strip())
    return lessons


def save(lessons, note=""):
    """Write lessons.md: tidied, de-duplicated and capped."""
    seen, kept = set(), []
    for lesson in lessons:
        lesson = " ".join(str(lesson).split())[:MAX_LESSON_CHARS]
        if lesson and lesson.lower() not in seen and not any(w in lesson.lower() for w in NOT_CIV5):
            seen.add(lesson.lower())
            kept.append(lesson)
    kept = kept[:MAX_LESSONS]
    header = ("# Lessons\n\n"
              "Written by the model about its own play and shown to it every turn. Edit or delete freely.\n"
              f"Last updated {date.today().isoformat()}" + (f" ({note})" if note else "") + ".\n\n")
    LESSONS_FILE.write_text(header + "".join(f"- {lesson}\n" for lesson in kept), encoding="utf-8")
    return kept


def for_prompt(lessons):
    if not lessons:
        return ""
    return ("Lessons from your past play (follow them unless the situation clearly differs):\n"
            + "\n".join(f"- {lesson}" for lesson in lessons))


def snapshot(s):
    """The numbers a review compares between the start and end of a period."""
    rivals = [r["score"] for r in s["rivals"].values() if isinstance(r["score"], (int, float))]
    me = s.get("me") or {}
    return {
        "turn": s["turn"],
        "score": me.get("score"),
        "rival_avg_score": round(sum(rivals) / len(rivals)) if rivals else None,
        "cities": len(s["cities"]),
        "population": sum(c["pop"] or 0 for c in s["cities"].values()),
        "military_units": sum(1 for u in s["units"].values() if u["combat"]),
        "civilian_units": sum(1 for u in s["units"].values() if not u["combat"]),
        "techs": me.get("techs"),
        "policies": me.get("policies"),
        "gold": s["gold"],
        "gold_per_turn": s["gold_rate"],
        "happiness": s["happiness"],
        "science": s["science"],
        "culture": s["culture"],
        "faith": s["faith"],
    }


class Period:
    """What happened since the last review: failures, idle replies, losses."""

    def __init__(self, s):
        self.start = snapshot(s)
        self.failures = Counter()
        self.examples = {}  # tool -> a sample error message
        self.silent_replies = 0
        self.lost = []

    def failure(self, tool, result):
        self.failures[tool] += 1
        self.examples.setdefault(tool, result[:200])

    def describe(self, s, plan, lessons):
        """The review prompt: hard facts, then the current lessons."""
        end = snapshot(s)
        rows = []
        for key, before in self.start.items():
            after = end.get(key)
            if key != "turn" and before != after:
                rows.append(f"  {key.replace('_', ' ')}: {before} -> {after}")
        out = [f"Turns {self.start['turn']} to {end['turn']}.", "What changed:"]
        out.extend(rows or ["  nothing measurable"])
        if self.lost:
            out.append("Units lost: " + ", ".join(self.lost))
        if self.failures:
            out.append("Actions that failed (count, example error):")
            out.extend(f"  {tool} x{n}: {self.examples[tool]}" for tool, n in self.failures.most_common(6))
        if self.silent_replies:
            out.append(f"Replies where you wrote text but called no tools: {self.silent_replies}")
        out.append(f"Your plan: {plan or 'none'}")
        out.append("Current lessons:" if lessons else "Current lessons: none yet.")
        out.extend(f"  {i}. {lesson}" for i, lesson in enumerate(lessons, 1))
        out.append(f"\nUpdate the lessons (at most {MAX_LESSONS}) and call save_lessons with the full list.")
        return "\n".join(out)
