"""Keeping Workers on task: what the agent remembers about worker jobs between turns.

Small models re-issue the same worker order every turn: they don't notice a job is
done (the plan still says "build a farm at (17,18)"), send two workers to one tile,
pull a worker off a half-built mine, or retry a build that failed last turn for a
reason that hasn't changed. This module:

  check()   refuses those orders with a message that says why and what to do instead
  after()   remembers orders "to build on arrival" and builds that failed
  resume()  starts the build itself when a worker arrives and sits idle (the game's
            queued build after a move doesn't always start)
  stale_plan_tiles()  tiles the plan still wants improved that already are
"""
import re

from .state import needs_orders

ROUTES = ("BUILD_ROAD", "BUILD_RAILROAD")
UNIT_ORDERS = ("build_improvement", "move_unit", "automate", "fortify", "sleep", "skip")
PENDING_TURNS = 10  # give up on a "build on arrival" after this long
FAILED_TURNS = {"DONE": 30, "default": 5}  # how long a failed build is remembered


def resource_at(s, x, y):
    for c in s["cities"].values():
        for r in c["resources"]:
            if (r["x"], r["y"]) == (x, y):
                return r
    return None


def other_jobs(s, u):
    """The worker's listed targets that nobody else has, as text for an error message."""
    taken = {(o["x"], o["y"]) for o in s["units"].values() if o.get("working") and o["id"] != u["id"]}
    free = [t for t in u.get("work_targets", []) if (t["x"], t["y"]) not in taken]
    if not free:
        return " No other resource is waiting near it: build a road, or automate it (automate 'build')."
    return " Other jobs for it: " + "; ".join(
        f"build_improvement {t['build']} at ({t['x']},{t['y']}) on {t['resource']}" for t in free[:3]) + "."


class WorkerJobs:
    def __init__(self):
        self.pending = {}  # unit id -> (build, x, y, turn ordered): "build on arrival" orders
        self.failed = {}   # (x, y, build) -> (turn, reason)

    def _target(self, args, u):
        x, y = args.get("x"), args.get("y")
        if x is None or y is None or int(x) < 0:
            return u["x"], u["y"]
        return int(x), int(y)

    def check(self, name, args, s, replace=False):
        """An answer to give instead of running the order, or None to run it."""
        if name not in UNIT_ORDERS:
            return None
        try:
            u = s["units"].get(int(args.get("unit_id")))
        except (TypeError, ValueError):
            return None
        if not u:
            return None
        build = str(args.get("build", "")).upper()
        if u.get("working") and not replace:
            w = u["working"]
            if name == "build_improvement" and build == w["build"] and self._target(args, u) == (u["x"], u["y"]):
                return (f"ok: worker {u['id']} is already building {w['build']} here ({w['turns']} turns left); "
                        "nothing to do - leave it")
            return (f"error: worker {u['id']} is BUSY building {w['build']} at ({u['x']},{u['y']}), "
                    f"{w['turns']} turns left. Leave it to finish; a new order abandons that work. "
                    "If you really want to, repeat the order with replace=true.")
        if name != "build_improvement":
            return None
        x, y = self._target(args, u)
        r = resource_at(s, x, y)
        if r and r.get("improved") and build not in ROUTES:
            return (f"error: ({x},{y}) {r['type']} is already IMPROVED ({r.get('improvement') or 'done'}): this job is "
                    "DONE. Take it out of your plan (update_plan)." + other_jobs(s, u))
        if r and r.get("in_progress") and r["in_progress"].get("unit") != u["id"]:
            w = r["in_progress"]
            return (f"error: ({x},{y}) is TAKEN: worker {w['unit']} is already building {w['build']} there "
                    f"({w['turns']} turns left)." + other_jobs(s, u))
        seen = self.failed.get((x, y, build))
        if seen:
            turn, reason = seen
            limit = FAILED_TURNS["DONE"] if "DONE" in reason else FAILED_TURNS["default"]
            if s["turn"] - turn <= limit:
                return (f"error: {build} at ({x},{y}) already failed on turn {turn}: {reason}. Nothing has "
                        "changed that would make it work; don't try it again." + other_jobs(s, u))
            del self.failed[(x, y, build)]
        return None

    def after(self, name, args, s, result):
        """Remember what an order did."""
        try:
            uid = int(args.get("unit_id"))
        except (TypeError, ValueError):
            return
        if name not in UNIT_ORDERS:
            return
        u = s["units"].get(uid) or {"x": -1, "y": -1}
        if name == "build_improvement":
            build = str(args.get("build", "")).upper()
            x, y = self._target(args, u)
            if result.startswith("ok") and "on arrival" in result:
                self.pending[uid] = (build, x, y, s["turn"])
                return
            if result.startswith("error") and "cannot build" in result:
                # the game's reason (outside borders, already improved, missing tech...), not reachability
                self.failed[(x, y, build)] = (s["turn"], result.split(": ", 2)[-1])
        if result.startswith("ok"):
            self.pending.pop(uid, None)  # any other successful order replaces the old job

    def resume(self, s, actions):
        """Start queued builds for workers that arrived and sit idle; returns what was done."""
        done = []
        for uid, (build, x, y, turn) in list(self.pending.items()):
            u = s["units"].get(uid)
            r = resource_at(s, x, y)
            if not u or s["turn"] - turn > PENDING_TURNS or u.get("working") or (r and r.get("improved")):
                self.pending.pop(uid, None)
                continue
            if not needs_orders(u):
                continue  # still walking (or fortified/asleep by someone's choice)
            result = actions.build_improvement(uid, build, x, y)
            done.append(f"worker {uid} resumed its job: {result}")
            if not result.startswith("ok") or "is building" in result:
                self.pending.pop(uid, None)
        return done

    @staticmethod
    def stale_plan_tiles(plan, s):
        """[(x, y, resource, improvement)] the plan names that are already improved."""
        out = []
        for x, y in {(int(a), int(b)) for a, b in re.findall(r"\((\d+)\s*,\s*(\d+)\)", plan or "")}:
            r = resource_at(s, x, y)
            if r and r.get("improved"):
                out.append((x, y, r["type"], r.get("improvement") or "an improvement"))
        return sorted(out)
