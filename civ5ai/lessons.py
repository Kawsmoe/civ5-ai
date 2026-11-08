"""Lessons the model writes about its own play, kept across games.

The model's weights never change, so this is how it "learns": every few turns
(and when a run ends) the agent shows it hard facts about how those turns went,
it rewrites a short list of lessons, and that list goes into its prompt from
then on. lessons.md is plain Markdown: read it, edit it or delete it freely.

Each lesson is tagged with what it applies to: "[general] ..." for every game,
or a victory type ("[science] ...", "[domination] ...", ...) for games going for
that victory. A turn shows only the general lessons and the ones for the victory
the plan names, so a domination game doesn't teach a science game to build an
army. Untagged lines count as general.
"""
import re
from collections import Counter
from datetime import date
from pathlib import Path

LESSONS_FILE = Path(__file__).resolve().parent.parent / "lessons.md"
MAX_LESSONS = 15  # per review, and per tag in the file
MAX_LESSON_CHARS = 200
# ideas from other Civ games that small models mix in; a lesson using them is wrong for Civ V
NOT_CIV5 = ("amenit", "district", "builder charge", "loyalty", "housing", "governor")
GENERAL = "general"
VICTORIES = ("domination", "science", "culture", "diplomatic")
# word starts the model may use for each victory ("scientific", "conquest", "tourism", ...)
_VICTORY_WORDS = {"domination": ("domin", "conque", "militar"), "science": ("scien", "space"),
                  "culture": ("cultur", "touris"), "diplomatic": ("diplom",)}
_TAG = re.compile(r"^\[([^\]]*)\]\s*")

REVIEW_SYSTEM = """You are reviewing your own play of Civilization V (Brave New World) to get better at it. You keep a short list of lessons that you will see every turn in this and future games.

Good lessons are short, concrete and general: they say what to do or avoid and when, and they would still help on a different map, with a different civ. Bad lessons mention specific coordinates or unit ids, repeat the game's basic rules, or are vague ("play better").

Most lessons should be about strategy: expansion, what to build and research, growth, happiness, economy, combat, diplomacy. Failed tool calls mostly show interface mistakes; turn them into at most three lessons, and only when they change how you play. This is Civilization V: don't use ideas from other Civ games (amenities, districts, builder charges, loyalty, housing).

Start every lesson with a tag saying which games it applies to: [general] if it helps whatever victory you go for (growth, happiness, workers, defence, the interface), or the victory it serves - [domination], [science], [culture] or [diplomatic] - if it is a choice that suits that victory and could hurt another (e.g. "build an army before expanding" is [domination], "build libraries in every city" is [science]). When unsure, use the victory tag: a lesson wrongly marked [general] misleads every other kind of game.

Some lessons show evidence from earlier play: how your score compared with your rivals' while the lesson was in use, and while it was held out (left out of your prompt on purpose, as a test), plus results of finished games. Use it: drop or rewrite a lesson whose evidence is clearly bad over many turns (e.g. score vs rivals keeps falling while it is used but not while held out), keep ones whose evidence is good. Evidence from fewer than about 30 turns is noise; don't act on it alone.

Base lessons on the facts you are given, not on guesses. Keep lessons that still hold, rewrite ones the facts contradict, drop ones that turned out wrong or useless, and add what these turns taught you. Then call save_lessons with the complete new list."""

SAVE_TOOL = {"type": "function", "function": {
    "name": "save_lessons",
    "description": f"Save the complete updated list of lessons (at most {MAX_LESSONS}).",
    "parameters": {"type": "object", "required": ["lessons"], "properties": {
        "lessons": {"type": "array", "items": {"type": "string"},
                    "description": "Each lesson one short sentence starting with its tag, "
                                   "e.g. \"[general] ...\" or \"[science] ...\"."}}}}}


def victory_word(word):
    """The victory type a word names ("Scientific" -> "science"), or None."""
    word = (word or "").lower()
    return next((v for v, starts in _VICTORY_WORDS.items() if word.startswith(starts)), None)


def split_tag(lesson):
    """("science", "Build libraries.") from "[science] Build libraries."; untagged -> general."""
    m = _TAG.match(lesson)
    if not m:
        return GENERAL, lesson
    return victory_word(m.group(1).strip()) or GENERAL, lesson[m.end():]


def victory_of(plan):
    """The victory the plan goes for ("Target: science victory. ..." -> "science"), or None."""
    if not plan:
        return None
    m = re.search(r"target\W*(?:an?\s+|the\s+)?(\w+)", plan, re.I)
    if m and victory_word(m.group(1)):
        return victory_word(m.group(1))
    m = re.search(r"(\w+)\s+victory", plan, re.I)
    return victory_word(m.group(1)) if m else None


def relevant(lessons, victory):
    """The lessons for a game going for this victory: general ones plus that victory's."""
    return [x for x in lessons if split_tag(x)[0] in (GENERAL, victory)]


def reviewable(lessons, victory, held_out=()):
    """The lessons a review may rewrite: those for this game, minus the ones held out this run."""
    return [x for x in relevant(lessons, victory) if x not in held_out]


def merge(old, new, victory, held_out=()):
    """The full list after a review that saw only reviewable(old, victory, held_out) and
    returned new: lessons for other victories and held-out lessons are kept as they were."""
    shown = reviewable(old, victory, held_out)
    return list(new) + [x for x in old if x not in shown]


def standing(s):
    """(your place by score, number of players) among you and the civs you have met."""
    me = (s.get("me") or {}).get("score")
    scores = [r["score"] for r in s["rivals"].values() if isinstance(r["score"], (int, float))]
    if not isinstance(me, (int, float)):
        return None, len(scores) + 1
    return 1 + sum(1 for x in scores if x > me), len(scores) + 1


_LISTED = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*(\[[^\]]+\].+)$")


def from_reply(reply, extract_calls):
    """The lessons in a review reply: a save_lessons call (real or written as JSON), or else
    a list of tagged lines ("- [general] ...") written as plain text. None if there are none."""
    content = reply.get("content") or ""
    for call in reply.get("tool_calls") or extract_calls(content, tools=[SAVE_TOOL]):
        if call["function"]["name"] == "save_lessons":
            new = (call["function"].get("arguments") or {}).get("lessons")
            if isinstance(new, list) and new:
                return new
    listed = [m.group(1) for m in map(_LISTED.match, content.splitlines()) if m]
    return listed or None


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
    """Write lessons.md: tagged, tidied, de-duplicated and capped (per tag)."""
    seen, kept, per_tag = set(), [], Counter()
    for lesson in lessons:
        tag, text = split_tag(" ".join(str(lesson).split()))
        text = text[:MAX_LESSON_CHARS]
        if (text and text.lower() not in seen and per_tag[tag] < MAX_LESSONS
                and not any(w in text.lower() for w in NOT_CIV5)):
            seen.add(text.lower())
            per_tag[tag] += 1
            kept.append(f"[{tag}] {text}")
    header = ("# Lessons\n\n"
              "Written by the model about its own play. Each turn it sees the [general] lessons and the ones\n"
              "tagged with the victory its plan goes for ([domination], [science], [culture], [diplomatic]).\n"
              "Untagged lines count as [general]. Edit or delete freely.\n"
              f"Last updated {date.today().isoformat()}" + (f" ({note})" if note else "") + ".\n\n")
    LESSONS_FILE.write_text(header + "".join(f"- {lesson}\n" for lesson in kept), encoding="utf-8")
    return kept


def for_prompt(lessons, victory=None, held_out=()):
    """The lessons section of a turn prompt: only those for this game's victory, minus held-out ones."""
    shown = reviewable(lessons, victory, held_out)
    if not shown:
        return ""
    return ("Lessons from your past play (follow them unless the situation clearly differs):\n"
            + "\n".join(f"- {split_tag(lesson)[1]}" for lesson in shown))


def review_footer(lessons, victory, evidence=None):
    """The end of a review prompt: the lessons to rewrite (with their evidence) and how to tag them."""
    out = ["Current lessons:" if lessons else "Current lessons: none yet."]
    for i, lesson in enumerate(lessons, 1):
        out.append(f"  {i}. {lesson}")
        ev = evidence(lesson) if evidence else ""
        if ev:
            out.append(f"     evidence: {ev}")
    if victory:
        out.append(f"\nThis game goes for a {victory} victory: tag each lesson [general] or [{victory}]. "
                   "Lessons for other victories are kept separately; don't repeat them.")
    else:
        out.append("\nThe plan names no victory yet: tag lessons [general] unless one clearly belongs "
                   "to a victory ([domination], [science], [culture] or [diplomatic]).")
    out.append(f"Update the lessons (at most {MAX_LESSONS}) and call save_lessons with the full list.")
    return "\n".join(out)


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

    def describe(self, s, plan, lessons, held_out=(), evidence=None, outcome=None, run_start=None):
        """The review prompt: hard facts, then the current lessons for this game's victory.

        outcome (a dict from the agent) and run_start (the snapshot when the run began)
        are given for the final review of a run, so it can judge the whole game."""
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
        if run_start or outcome:
            out.extend(_whole_run(s, end, run_start, outcome))
        out.append(f"Your plan: {plan or 'none'}")
        victory = victory_of(plan)
        out.append(review_footer(reviewable(lessons, victory, held_out), victory, evidence))
        return "\n".join(out)


def _whole_run(s, end, run_start, outcome):
    """Final-review lines: how the whole run went and how the game ended."""
    out = []
    if run_start:
        def gap(x):
            return (x["score"] - x["rival_avg_score"]
                    if None not in (x["score"], x["rival_avg_score"]) else None)
        g0, g1 = gap(run_start), gap(end)
        out.append(f"Whole run: turns {run_start['turn']} to {end['turn']}; score {run_start['score']} -> "
                   f"{end['score']}" + (f"; your score minus rivals' average {g0:+} -> {g1:+}"
                                        if None not in (g0, g1) else "")
                   + f"; cities {run_start['cities']} -> {end['cities']}.")
    rank, players = standing(s)
    if outcome and outcome.get("over"):
        out.append("THE GAME IS OVER: " + ("you WON" if outcome.get("won") else "you LOST")
                   + (f" ({outcome['victory'].replace('VICTORY_', '').lower()} victory"
                      + (f" by {outcome['winner']})" if outcome.get("winner") else ")")
                      if outcome.get("victory") else "")
                   + ". This is the most important fact: keep lessons that led here if you won, "
                     "and rewrite the ones that didn't stop the loss if you lost.")
    elif rank:
        out.append(f"The run stopped before the game ended; you are in place {rank} of {players} by score.")
    return out
