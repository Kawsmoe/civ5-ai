"""Actions the agent can take in the game.

Each action is a Lua function in lua/actions.lua (installed into the game
as the global table _AI) that checks legality and returns a string starting
with "ok:" or "error:". That string goes back to the model as-is.
"""
import time
from pathlib import Path

from .tuner import TunerError

LUA = (Path(__file__).parent / "lua" / "actions.lua").read_text()


def _lua_arg(v):
    """Python value -> Lua literal. Strings from the model are always quoted and
    escaped, so they can't break out of the string and run as code."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    s = "".join(c if c >= " " else f"\\{ord(c):03d}" for c in s)  # newlines etc. as \ddd escapes
    return f'"{s}"'


class Actions:
    def __init__(self, tuner):
        self.t = tuner
        self.t.run(LUA)

    def _call(self, fn, *args):
        lines = self.t.run(f"print(_AI.{fn}({', '.join(map(_lua_arg, args))}))")
        # take our result, not log lines the game's UI may print meanwhile
        results = [line for line in lines if line.startswith(("ok", "error"))]
        return results[-1] if results else "error: no result"

    def _turn_status(self):
        """(game turn, whether our turn is active), robust to stray output lines."""
        lines = self.t.run("print('TURN\\t' .. Game.GetGameTurn() .. '\\t' .. "
                           "tostring(Players[Game.GetActivePlayer()]:IsTurnActive()))")
        for line in reversed(lines):
            if line.startswith("TURN\t"):
                _, turn, active = line.split("\t")
                return int(turn), active == "true"
        raise TunerError(f"could not read the turn: {lines}")

    def found_city(self, unit_id):
        return self._call("found_city", int(unit_id))

    def move_unit(self, unit_id, x, y):
        return self._call("move_unit", int(unit_id), int(x), int(y))

    def fortify(self, unit_id):
        return self._call("fortify", int(unit_id))

    def sleep(self, unit_id):
        return self._call("sleep", int(unit_id))

    def skip(self, unit_id):
        return self._call("skip", int(unit_id))

    def automate(self, unit_id, kind):
        return self._call("automate", int(unit_id), kind)

    def build_improvement(self, unit_id, build, x=-1, y=-1):
        return self._call("build_improvement", int(unit_id), str(build).upper(), int(x), int(y))

    def set_research(self, tech):
        return self._call("set_research", tech)

    def set_production(self, city_id, item):
        return self._call("set_production", int(city_id), item)

    def _turn(self):
        return self._turn_status()[0]

    def adopt_policy(self, policy):
        return self._call("adopt_policy", policy)

    def found_pantheon(self, belief):
        return self._call("found_pantheon", belief)

    def _holy_city(self):
        """Where the religion is being founded or enhanced.

        The game passes the city to its religion popup, which keeps it in the
        globals g_iCityX/g_iCityY of its own Lua state; fall back to the capital.
        """
        def xy(lines):
            for line in reversed(lines):
                if line.startswith("XY\t"):
                    _, x, y = line.split("\t")
                    return int(x), int(y)
            return -1, -1
        try:
            x, y = xy(self.t.run("print('XY\\t' .. g_iCityX .. '\\t' .. g_iCityY)", state="ChooseReligionPopup"))
            if x >= 0:
                return x, y
        except (TunerError, KeyError):
            pass
        return xy(self.t.run("local c = Players[Game.GetActivePlayer()]:GetCapitalCity() "
                             "print('XY\\t' .. c:GetX() .. '\\t' .. c:GetY())"))

    def found_religion(self, religion, founder_belief, follower_belief,
                       pantheon_belief="", bonus_belief=""):
        x, y = self._holy_city()
        return self._call("found_religion", religion, founder_belief, follower_belief,
                          pantheon_belief, bonus_belief, x, y)

    def enhance_religion(self, follower_belief, enhancer_belief):
        x, y = self._holy_city()
        return self._call("enhance_religion", follower_belief, enhancer_belief, x, y)

    def choose_ideology(self, ideology):
        return self._call("choose_ideology", ideology)

    def free_tech(self, tech):
        return self._call("free_tech", tech)

    def promote(self, unit_id, promotion):
        return self._call("promote", int(unit_id), promotion)

    def attack(self, unit_id, x, y):
        return self._call("attack", int(unit_id), int(x), int(y))

    def city_attack(self, city_id, x, y):
        return self._call("city_attack", int(city_id), int(x), int(y))

    def unit_mission(self, unit_id, mission):
        return self._call("unit_mission", int(unit_id), mission)

    def buy(self, city_id, item, currency="GOLD"):
        return self._call("buy", int(city_id), item, str(currency).upper())

    def declare_war(self, player_id):
        return self._call("declare_war", int(player_id))

    def diplo_vote(self, player_id):
        return self._call("diplo_vote", int(player_id))

    def league_propose(self, kind, id, choice=-1):
        return self._call("league_propose", str(kind).upper(), int(id), int(choice))

    def league_vote(self, kind, resolution_id, choice, votes=0):
        return self._call("league_vote", str(kind).upper(), int(resolution_id), int(choice), int(votes))

    def league_abstain(self):
        return self._call("league_abstain")

    def move_spy(self, spy_id, player_id=-1, city_id=-1, as_diplomat=False):
        return self._call("move_spy", int(spy_id), int(player_id), int(city_id), bool(as_diplomat))

    def stage_coup(self, spy_id):
        return self._call("stage_coup", int(spy_id))

    def steal_tech(self, player_id, tech):
        return self._call("steal_tech", int(player_id), tech)

    def trade_route(self, unit_id, x, y):
        return self._call("trade_route", int(unit_id), int(x), int(y))

    def choose_great_person(self, kind, unit_type):
        return self._call("choose_great_person", str(kind).upper(), unit_type)

    def archaeology(self, choice):
        # the game passes the archaeologist to its popup, which keeps it in the
        # global g_iUnitIndex of its own Lua state
        try:
            unit_index = int(self.t.run("print(g_iUnitIndex)", state="ChooseArchaeologyPopup")[0])
        except (TunerError, ValueError, KeyError, IndexError):
            unit_index = -1
        if unit_index < 0:
            return "error: could not find the archaeologist for this choice"
        return self._call("archaeology", str(choice).upper(), unit_index)

    def end_turn(self):
        # The game's end-turn blocker only refreshes on its next UI update, so
        # right after e.g. choosing production it can still say PRODUCTION.
        # Retry briefly before reporting the blocker to the model.
        # The end-turn control can also be dropped silently if the game is
        # still busy with the previous command, so confirm it took effect.
        self.turn_before_end = self._turn()
        for _ in range(8):
            if self._turn_over():  # game ended the turn (possibly on its own)
                return "ok: turn ended"
            result = self._call("end_turn")
            if "needs orders" in result:
                return result
            if result.startswith("ok"):
                deadline = time.time() + 2
                while time.time() < deadline:
                    if self._turn_over():
                        return result
                    time.sleep(0.25)
            else:
                time.sleep(0.5)
        return result if not result.startswith("ok") else "error: the game did not end the turn"

    def _turn_over(self):
        turn, active = self._turn_status()
        return turn > self.turn_before_end or not active

    def wait_for_my_turn(self, timeout=600, on_wait=None, every=3):
        """After end_turn: block until the AIs finish and our next turn starts.

        on_wait() is called every few seconds meanwhile: the AIs' turns can stop
        on a screen that needs us (a leader greeting us, a popup), and our turn
        won't start until it is dealt with.
        """
        start = getattr(self, "turn_before_end", None)
        if start is None:
            start = self._turn()
        deadline = time.time() + timeout
        last_check = 0.0
        while time.time() < deadline:
            turn, active = self._turn_status()
            if turn > start and active:
                return turn
            if on_wait and time.time() - last_check >= every:
                on_wait()
                last_check = time.time()
            time.sleep(1)
        raise TimeoutError("our turn did not come back")
