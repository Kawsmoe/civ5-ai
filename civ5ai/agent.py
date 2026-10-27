"""The turn loop: show the model the game state, run its tool calls, end the turn.

Each turn:
  1. close leftover popups and read the game state (state.py)
  2. send the state to the model; it answers with tool calls, which we run
     (actions.py, diplomacy.py) and answer with each "ok:"/"error:" result
  3. repeat until the model calls end_turn; if it hits the action cap,
     simple defaults finish the turn instead
  4. wait for the AI players, then start again
"""
import json
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from . import diplomacy
from .actions import Actions
from .popups import close_popups
from .prompt import SYSTEM
from .state import get_state, needs_orders, summarize
from .tools import TOOLS
from .tuner import TunerError

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen2.5:14b"
# system prompt + tool definitions alone are ~5.5k tokens; leave room for state and replies
MODEL_OPTIONS = {"temperature": 0.3, "num_ctx": 16384}
MAX_ACTIONS_PER_TURN = 15
MAX_SILENT_REPLIES = 2  # text-only replies in a row before falling back to defaults

PROJECT_DIR = Path(__file__).resolve().parent.parent
PLAN_FILE = PROJECT_DIR / "plan.txt"  # the model's strategy, kept across runs
LOG_DIR = PROJECT_DIR / "logs"

# End-turn blockers the agent can clear itself; anything else waits for the human.
HANDLED_BLOCKERS = {
    "NONE", "UNITS", "PRODUCTION", "RESEARCH", "STACKED_UNITS", "POLICY", "FREE_POLICY",
    "FREE_TECH", "UNIT_PROMOTION", "CITY_RANGE_ATTACK", "FOUND_PANTHEON", "FOUND_RELIGION",
    "ENHANCE_RELIGION", "ADD_REFORMATION_BELIEF", "CHOOSE_IDEOLOGY", "STEAL_TECH",
    "FAITH_GREAT_PERSON", "FREE_ITEMS", "MAYA_LONG_COUNT", "CHOOSE_ARCHAEOLOGY",
    "LEAGUE_CALL_FOR_PROPOSALS", "LEAGUE_CALL_FOR_VOTES", "DIPLO_VOTE", "MINOR_QUEST",
}


def extract_text_tool_calls(content):
    """Tool calls the model wrote as text instead of real calls.

    qwen sometimes puts {"name": ..., "arguments": {...}} JSON (often inside
    <tool_call> tags or ``` fences) in its message. Run those rather than ignore them.
    """
    known = {t["function"]["name"] for t in TOOLS}
    calls, decoder, i = [], json.JSONDecoder(), 0
    while (i := content.find("{", i)) != -1:
        try:
            obj, end = decoder.raw_decode(content, i)
        except ValueError:
            i += 1
            continue
        i = end
        if isinstance(obj, dict) and obj.get("name") in known:
            args = obj.get("arguments", obj.get("parameters", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            calls.append({"function": {"name": obj["name"], "arguments": args if isinstance(args, dict) else {}}})
    return calls


def chat(model, messages, tools=TOOLS):
    """One Ollama chat call with our tools; returns the reply message."""
    body = json.dumps({"model": model, "messages": messages, "tools": tools,
                       "stream": False, "options": MODEL_OPTIONS}).encode()
    req = urllib.request.Request(OLLAMA_URL, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())["message"]


class Agent:
    def __init__(self, tuner, model=DEFAULT_MODEL, log_path=None):
        self.attach(tuner)
        self.model = model
        LOG_DIR.mkdir(exist_ok=True)
        self.log_path = log_path or LOG_DIR / f"game-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
        self.log = open(self.log_path, "a", encoding="utf-8")
        self.last_turn_actions = []
        self.plan = PLAN_FILE.read_text(encoding="utf-8") if PLAN_FILE.exists() else ""
        self.human_message = ""
        self.changed_turn = {}  # "research" or city id -> turn we last changed it
        self.known_units = {}  # id -> (type, x, y) as of the last state we saw
        self.lost_units = {}   # id -> (type, x, y, turn lost), so stale ids get a clear answer

    def attach(self, tuner):
        """Use a (new) tuner connection; reinstalls the in-game actions."""
        self.t = tuner
        self.a = Actions(tuner)

    def record(self, **entry):
        """Append one event to the JSONL game log."""
        entry["time"] = datetime.now().isoformat(timespec="seconds")
        self.log.write(json.dumps(entry) + "\n")
        self.log.flush()

    # -- running tool calls ------------------------------------------------

    def do(self, name, args, s):
        """Run one tool call from the model and return its result string."""
        try:
            return self._do(name, args, s)
        except (TypeError, ValueError, KeyError) as e:
            return f"error: bad arguments for {name}: {e}"
        except TunerError as e:
            return f"error: game rejected {name}: {e}"

    def _do(self, name, args, s):
        if name == "update_plan":
            self.plan = f"(written turn {s['turn']}) {args.get('plan', '').strip()}"
            PLAN_FILE.write_text(self.plan, encoding="utf-8")
            return "ok: plan saved"
        if name == "respond_to_leader":
            return diplomacy.respond(self.t, args.get("option", 0))
        if name == "end_turn":
            close_popups(self.t, keep_choices=False)
            fired = self.fire_city_shots()
            if fired:
                print("  (auto) " + "; ".join(fired))
        fn = getattr(self.a, name, None)
        if fn is None:
            return f"error: unknown tool {name}"
        args = dict(args)
        replace = args.pop("replace", False) in (True, "true")
        if name == "set_research":
            # stop flip-flopping (which wastes progress), but allow a deliberate change
            if s["research"] and not replace and self.recently_changed("research", s):
                return (f"error: you changed research to {s['research']} very recently; "
                        "pass replace=true if you really want to switch again")
        if name == "set_production":
            city = s["cities"].get(int(args.get("city_id", -1)))
            if city and city["producing"] and not replace and self.recently_changed(city["id"], s):
                return (f"error: you changed {city['name']}'s production very recently; "
                        "pass replace=true if you really want to switch again")
            if str(args.get("item", "")).upper() == "UNIT_WORKER" and self.enough_workers(s):
                return (f"error: you already have {self.worker_count(s)} Workers for {len(s['cities'])} "
                        "city/cities, which is enough. Give the existing Workers jobs "
                        "(build_improvement or automate 'build') and build something else.")
        result = fn(**args)
        if result.startswith("ok") and name in ("set_research", "set_production"):
            self.changed_turn["research" if name == "set_research" else int(args["city_id"])] = s["turn"]
        return result

    def fire_city_shots(self):
        """Fire every city that can still shoot this turn; a free shot is never wasted.

        Aims at the most damaged enemy in range so shots finish units off.
        """
        s = get_state(self.t)
        hp = {(e["x"], e["y"]): e["hp"] or 100 for e in s["enemies"]}
        targets = {}
        for t in s["ranged_targets"]:
            if t["kind"] == "CITY":
                targets.setdefault(t["id"], []).append((hp.get((t["x"], t["y"]), 100), t["x"], t["y"]))
        results = []
        for city_id, options in targets.items():
            _, x, y = min(options)
            r = self.a.city_attack(city_id, x, y)
            self.record(turn=s["turn"], tool="city_attack", args={"city_id": city_id, "x": x, "y": y},
                        result=r, auto=True)
            results.append(r)
        return results

    def recently_changed(self, key, s, turns=3):
        return s["turn"] - self.changed_turn.get(key, -99) < turns

    @staticmethod
    def worker_count(s):
        return sum(1 for u in s["units"].values() if u["type"] == "UNIT_WORKER")

    def enough_workers(self, s):
        return self.worker_count(s) >= 2 * max(1, len(s["cities"]))

    @staticmethod
    def unit_roster(s):
        units = ", ".join(f"{u['id']} {u['type']}" for u in s["units"].values()) or "none"
        settlers = [u for u in s["units"].values() if u["type"] == "UNIT_SETTLER"]
        note = "" if settlers else " You have no Settler right now; city ids are not unit ids."
        return f"Your units are: {units}.{note}"

    def track_units(self, s):
        """Note which units disappeared since the last state; return them {id: (type, x, y)}."""
        current = {u["id"]: (u["type"], u["x"], u["y"]) for u in s["units"].values()}
        gone = {uid: info for uid, info in self.known_units.items() if uid not in current}
        for uid, info in gone.items():
            self.lost_units[uid] = (*info, s["turn"])
        self.known_units = current
        return gone

    def unknown_unit_message(self, args, s):
        """Explain a 'no unit with id' error, especially for units that died."""
        try:
            uid = int(args.get("unit_id"))
        except (TypeError, ValueError):
            uid = None
        if uid in self.lost_units:
            utype, x, y, turn = self.lost_units[uid]
            why = ("used up founding a city" if utype == "UNIT_SETTLER"
                   else "killed, captured, disbanded or upgraded")
            return (f"error: unit {uid} ({utype}) was lost around turn {turn} near ({x},{y}) - {why}. "
                    f"It no longer exists; don't use its id again. {self.unit_roster(s)}")
        return None

    def describe(self, s):
        """State summary plus any leader currently talking to us."""
        d = diplomacy.get_diplomacy(self.t)
        return summarize(s) + ("\n" + diplomacy.summarize(d) if d else "")

    def handle_screens_while_waiting(self):
        """During the AIs' turns: answer leaders who talk to us and clear popups."""
        d = diplomacy.get_diplomacy(self.t)
        if d:
            print("\n  (leader screen while the AIs move)" + diplomacy.summarize(d))
            r = self.answer_leader(d)
            print(f"  respond_to_leader -> {r}")
            return
        # a leader screen we can't read (e.g. a plain greeting): leave it the way "Return" does
        closed = close_popups(self.t, keep_choices=False)
        if closed:
            print(f"  closed while waiting: {', '.join(closed)}")

    def answer_leader(self, d):
        """Let the model answer a leader screen in a short separate chat; decline if it doesn't."""
        rivals = [line for line in summarize(get_state(self.t)).splitlines()
                  if line.startswith(("  player", "    Attitude", "    Why"))]
        prompt = (diplomacy.summarize(d)
                  + "\n\nWhat you know about the civs you've met:\n" + "\n".join(rivals)
                  + "\n\nYour plan: " + (self.plan or "none")
                  + "\n\nAnswer with respond_to_leader.")
        tool = [t for t in TOOLS if t["function"]["name"] == "respond_to_leader"]
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
        try:
            reply = chat(self.model, messages, tools=tool)
            calls = reply.get("tool_calls") or extract_text_tool_calls(reply.get("content") or "")
            for call in calls:
                if call["function"]["name"] == "respond_to_leader":
                    option = (call["function"].get("arguments") or {}).get("option")
                    r = diplomacy.respond(self.t, option)
                    self.record(tool="respond_to_leader", args={"option": option}, result=r, while_waiting=True)
                    if r.startswith("ok"):
                        return r
        except (TunerError, OSError, ValueError, KeyError) as e:
            self.record(error=f"answering leader: {e!r}")
        # default: the last option is the decline / "never mind" / return one
        r = diplomacy.respond(self.t, max(d["options"]))
        self.record(tool="respond_to_leader", args={"option": max(d["options"])}, result=r, auto=True)
        return r

    def wait_for_human(self, blocker):
        print(f"  !! game needs {blocker}, which the agent can't handle yet - "
              "please do it in the game window; waiting...")
        while get_state(self.t)["blocking"] == blocker:
            time.sleep(2)

    def fallback(self, s):
        """Finish the turn with simple defaults when the model ran out of actions."""
        done = []
        if not s["research"] and s["techs"]:
            done.append(self.a.set_research(min(s["techs"], key=lambda t: t["turns"])["type"]))
        if s["policy_due"] and s["policy_options"]:
            done.append(self.a.adopt_policy(s["policy_options"][0]["type"]))
        if s["free_techs"] and s["techs"]:
            done.append(self.a.free_tech(max(s["techs"], key=lambda t: t["turns"])["type"]))
        if s["ideology_options"]:
            done.append(self.a.choose_ideology(s["ideology_options"][0]))

        first = {kind: options[0]["type"] for kind, options in s["beliefs"].items()}
        if s["blocking"] in ("FOUND_PANTHEON", "ADD_REFORMATION_BELIEF"):
            done.append(self.a.found_pantheon(first.get("PANTHEON") or first.get("REFORMATION")))
        elif s["blocking"] == "FOUND_RELIGION" and s["religion_options"]:
            done.append(self.a.found_religion(s["religion_options"][0], first.get("FOUNDER"),
                                              first.get("FOLLOWER"), first.get("PANTHEON", ""),
                                              first.get("BONUS", "")))
        elif s["blocking"] == "ENHANCE_RELIGION":
            done.append(self.a.enhance_religion(first.get("FOLLOWER"), first.get("ENHANCER")))

        for u in s["units"].values():
            if u["promotions"]:
                done.append(self.a.promote(u["id"], u["promotions"][0]))
        if s["steal_options"]:
            o = s["steal_options"][0]
            done.append(self.a.steal_tech(o["player"], o["tech"]))
        if s["great_person_options"]:
            o = s["great_person_options"][0]
            done.append(self.a.choose_great_person(o["kind"], o["type"]))
        if s["archaeology_options"]:
            # not every choice applies to every dig; try them until one takes
            for choice in ("LANDMARK", "ARTIFACT", "WRITING", "CULTURE"):
                done.append(self.a.archaeology(choice))
                if get_state(self.t)["blocking"] != "CHOOSE_ARCHAEOLOGY":
                    break
        if s["diplo_vote_options"]:
            me = next((o for o in s["diplo_vote_options"] if o["name"] == "yourself"),
                      s["diplo_vote_options"][0])
            done.append(self.a.diplo_vote(me["player"]))

        league = s["league"]
        if league and league["propose"] and league["proposals"]:
            o = league["propose"][0]
            done.append(self.a.league_propose(o["kind"], o["id"], o["choice"]))
        if league and league["vote"] and league["votes"]:
            done.append(self.a.league_abstain())

        d = diplomacy.get_diplomacy(self.t)
        if d:
            # decline by default: the last option is the refusal/"never mind" one
            done.append(diplomacy.respond(self.t, max(d["options"])))

        skip = {"UNIT_WORKER"} if self.enough_workers(s) else set()
        for c in s["cities"].values():
            options = [b for b in c["can_build"] if b["type"] not in skip]
            if not c["producing"] and options:
                done.append(self.a.set_production(c["id"], min(options, key=lambda b: b["turns"])["type"]))
        for u in s["units"].values():
            if needs_orders(u):
                r = self.a.fortify(u["id"])
                done.append(r if r.startswith("ok") else self.a.skip(u["id"]))
        return done

    # -- the turn ------------------------------------------------------------

    def build_prompt(self, s, lost):
        text = self.describe(s)
        if lost:
            text += "\n\nLOST since last turn (these units no longer exist): " + "; ".join(
                f"{utype} {uid} near ({x},{y})" for uid, (utype, x, y) in lost.items())
        if self.plan:
            text += ("\n\nYour plan so far (check it against the state above; "
                     f"rewrite it with update_plan if it no longer fits): {self.plan}")
            # any unit-sized id in the plan that isn't a current unit or city (also
            # catches units lost before this run started)
            live = {str(i) for i in list(s["units"]) + list(s["cities"])}
            stale = sorted({m for m in re.findall(r"\b\d{4,6}\b", self.plan) if m not in live})
            if stale:
                text += (f"\nWARNING: your plan mentions unit(s) {', '.join(stale)}, which no longer "
                         "exist. Rewrite the plan with update_plan using your current units.")
        else:
            text += "\n\nYour plan: none yet - write one with update_plan"
        if self.human_message:
            text += ("\n\nMESSAGE FROM THE HUMAN PLAYER (follow it, and update your plan "
                     f"if it changes your strategy): {self.human_message}")
            self.human_message = ""
        if self.last_turn_actions:
            text += "\n\nLast turn you did: " + "; ".join(self.last_turn_actions)
        return text

    def play_turn(self):
        closed = close_popups(self.t)
        if closed:
            print(f"  closed popups: {', '.join(closed)}")
        s = get_state(self.t)
        if s["blocking"] not in HANDLED_BLOCKERS:
            self.wait_for_human(s["blocking"])
            s = get_state(self.t)
        lost = self.track_units(s)
        text = self.build_prompt(s, lost)
        print(f"\n===== Turn {s['turn']} =====\n{text}\n")
        self.record(turn=s["turn"], state=text)

        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]
        actions, ended = [], False
        failed = set()  # (tool, args) that already failed this turn
        silent = 0  # replies in a row with no tool call
        while len(actions) < MAX_ACTIONS_PER_TURN and not ended:
            reply = chat(self.model, messages)
            calls = reply.get("tool_calls") or extract_text_tool_calls(reply.get("content") or "")
            # keep the transcript short: a long essay that did nothing just eats context
            content = (reply.get("content") or "").strip()
            if content:
                print(f"  model: {content[:300]}")
            messages.append({**reply, "content": content[:500]})
            if not calls:
                silent += 1
                actions.append("(no tool call)")
                if silent >= MAX_SILENT_REPLIES:
                    print("  model keeps answering without calling tools; finishing the turn with defaults")
                    break
                # nudge briefly; re-sending the whole state grows the context until the
                # system prompt falls out of Ollama's window and the model loops
                todo = summarize(get_state(self.t)).split("TO DO THIS TURN")[-1].strip(" :")
                messages.append({"role": "user", "content":
                                 "You wrote text but called no tools, so nothing happened in the game. "
                                 "Respond ONLY with tool calls now. Still to do: " + todo})
                continue
            silent = 0
            for call in calls:
                name, args = call["function"]["name"], call["function"].get("arguments") or {}
                key = (name, json.dumps(args, sort_keys=True))
                if key in failed and name != "end_turn":
                    # small models loop on a failing call; refuse instead of re-running it
                    result = ("error: you already tried exactly this and it failed. "
                              "Do something different, or call end_turn if nothing else is required.")
                else:
                    result = self.do(name, args, s)
                    if result.startswith("error"):
                        failed.add(key)
                        if "no unit with id" in result:
                            result = self.unknown_unit_message(args, s) or result + ". " + self.unit_roster(s)
                if result.startswith("ok"):
                    failed.clear()  # the game changed, so earlier failures may work now
                    if name in ("move_unit", "attack"):
                        # moving can discover things (natural wonders, ruins) that open popups
                        close_popups(self.t)
                if result.startswith("ok") and name in ("set_research", "set_production", "found_city", "attack"):
                    s = get_state(self.t)  # keep the guards and roster in sync
                    if name == "attack":
                        for uid, (utype, x, y) in self.track_units(s).items():
                            result += f". {utype} {uid} was lost in this fight and no longer exists"
                print(f"  {name}({', '.join(f'{k}={v}' for k, v in args.items())}) -> {result}")
                self.record(turn=s["turn"], tool=name, args=args, result=result)
                messages.append({"role": "tool", "content": result, "tool_name": name})
                actions.append(f"{name}({', '.join(str(v) for v in args.values())}) {result.split(':')[0]}")
                if name == "end_turn" and result.startswith("ok"):
                    ended = True
                    break

        if not ended:
            print("  action cap reached; finishing the turn with defaults")
            for r in self.fallback(get_state(self.t)):
                print(f"  fallback -> {r}")
            close_popups(self.t, keep_choices=False)
            for r in self.fire_city_shots():
                print(f"  fallback -> {r}")
            r = self.a.end_turn()
            print(f"  end_turn -> {r}")
            if not r.startswith("ok"):
                self.wait_for_human(get_state(self.t)["blocking"])
        # only what worked; replaying failures back to the model invites repeats
        self.last_turn_actions = [x for x in actions if x.endswith(" ok") and not x.startswith("end_turn")]
        new_turn = self.a.wait_for_my_turn(on_wait=self.handle_screens_while_waiting)
        self.record(turn=s["turn"], ended=True, next_turn=new_turn)
