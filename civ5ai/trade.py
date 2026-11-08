"""Us proposing deals and friendship to AI leaders.

diplomacy.py answers leaders who talk to us; this goes the other way. It drives
the same screens a player would: open the leader (DoBeginDiploWithHuman, as the
diplomacy list does), press Trade (LeaderHeadRoot's OnTrade), put the items in
the scratch deal, press Propose (DiploTrade's OnPropose), read the answer, and
close the screens again. Whether they accepted is read from the number of
active deals, so it doesn't depend on the wording of their reply.

What can be traded with whom is in the state (DT records, lua/state.lua); the
model picks from that list.
"""
import re
import time

from . import diplomacy
from .tuner import TunerError

# items that are the same thing given by both sides; asking for one adds both
MUTUAL = ("RESEARCH_AGREEMENT", "DEFENSIVE_PACT")
SIMPLE = ("OPEN_BORDERS", "EMBASSY") + MUTUAL
MAX_PROPOSALS_PER_CIV = 2  # per turn: AIs don't change their mind within a turn

SPEECH = """
local ok, s = pcall(function() return Controls.DiscussionText:GetText() end)
if not ok or not s then ok, s = pcall(function() return Controls.LeaderSpeech:GetText() end) end
print("SPEECH\\t" .. tostring(ok and s or ""))
"""


def parse_item(text):
    """'RESOURCE_IRON 2' / 'iron x2' / 'GOLD 100' / 'open borders' -> (KEY, amount or None)."""
    words = str(text).strip().upper().replace("-", " ").split()
    if not words:
        raise ValueError("empty item")
    amount = None
    if re.fullmatch(r"X?\d+", words[-1]):
        amount = int(words.pop().lstrip("X"))
    key = "_".join(words)
    if key in ("GOLD", "GOLD_PER_TURN", "GPT"):
        if not amount or amount <= 0:
            raise ValueError(f"{text!r}: say how much gold, e.g. 'GOLD 100' or 'GOLD_PER_TURN 3'")
        return ("GOLD_PER_TURN" if key == "GPT" else key), amount
    if key in ("ALLOW_EMBASSY",):
        key = "EMBASSY"
    if key in SIMPLE:
        return key, None
    if not key.startswith("RESOURCE_"):
        key = "RESOURCE_" + key
    return key, amount or 1


def deal_spec(give, get):
    """The give/get lists as the 'you|KEY|amount;them|KEY|amount' string _AI.build_deal takes."""
    parts, seen = [], set()
    for side, items in (("you", give), ("them", get)):
        for item in items or []:
            key, amount = parse_item(item)
            sides = ("you", "them") if key in MUTUAL else (side,)
            for s in sides:
                if (s, key) not in seen:
                    seen.add((s, key))
                    parts.append(f"{s}|{key}|{amount or ''}")
    if not parts:
        raise ValueError("the deal is empty: list what you give and/or what you want")
    return ";".join(parts)


def _lua_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


class Trader:
    def __init__(self, tuner):
        self.t = tuner
        self.proposals = {}  # (turn, player) -> proposals made

    # --- screens ---------------------------------------------------------------------

    def _visible(self, state):
        try:
            return self.t.run("print(not ContextPtr:IsHidden())", state=state, timeout=3) == ["true"]
        except (TunerError, KeyError):
            return False

    def _wait(self, state, visible=True, seconds=6.0):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self._visible(state) == visible:
                return True
            time.sleep(0.3)
        return False

    def _speech(self):
        for state in ("DiploTrade", "LeaderHeadRoot", "DiscussionDialog"):
            if self._visible(state):
                try:
                    for line in self.t.run(SPEECH, state=state, timeout=3):
                        if line.startswith("SPEECH\t") and line[7:].strip():
                            return re.sub(r"\[[A-Z_]+\]", "", line[7:]).strip()
                except (TunerError, KeyError):
                    pass
        return ""

    def _in_game(self, lua):
        lines = self.t.run(lua, timeout=5)
        return lines[-1] if lines else ""

    def _close(self):
        """Back out of the trade screen and the leader screen, whatever state they are in."""
        for state, fn in (("DiploTrade", "OnBack()"), ("LeaderHeadRoot", "OnReturn()")):
            if self._visible(state):
                try:
                    self.t.run(fn, state=state, timeout=3)
                except (TunerError, KeyError):
                    pass
                self._wait(state, visible=False, seconds=3)
        try:
            self.t.run("if UI.GetLeaderHeadRootUp() then UI.SetLeaderHeadRootUp(false); UI.RequestLeaveLeader() end",
                       timeout=3)
        except TunerError:
            pass

    def _open_leader(self, player):
        """Open the leader screen of an AI player; returns (name, error)."""
        r = self._in_game(f"""
local them = Players[{player}]
local me = Players[Game.GetActivePlayer()]
if not them or them:IsMinorCiv() or not them:IsAlive() or them:IsHuman() or {player} == Game.GetActivePlayer() then
	print("error: player {player} is not an AI civilization you can talk to") return end
if not Teams[me:GetTeam()]:IsHasMet(them:GetTeam()) then print("error: you haven't met player {player}") return end
if Teams[me:GetTeam()]:IsAtWar(them:GetTeam()) then print("error: you are at war with " .. them:GetCivilizationShortDescription()) return end
if not me:IsTurnActive() or Game.IsProcessingMessages() then print("error: it isn't your turn right now") return end
them:DoBeginDiploWithHuman()
print("ok\\t" .. them:GetCivilizationShortDescription())""")
        if not r.startswith("ok"):
            return "", r or "error: couldn't open the leader screen"
        name = r.partition("\t")[2]
        if not self._wait("LeaderHeadRoot"):
            self._close()
            return name, f"error: {name}'s leader screen didn't open"
        return name, ""

    def _deals(self):
        try:
            r = self._in_game("print(UI.GetNumCurrentDeals(Game.GetActivePlayer()))")
            return int(r)
        except (TunerError, ValueError):
            return None

    def _check_turn(self, player):
        try:
            turn = int(self._in_game("print(Game.GetGameTurn())"))
        except (TunerError, ValueError):
            turn = -1
        n = self.proposals.get((turn, player), 0)
        if n >= MAX_PROPOSALS_PER_CIV:
            return (f"error: you already asked player {player} {n} times this turn; "
                    "they won't change their mind until next turn")
        self.proposals[(turn, player)] = n + 1
        return ""

    # --- actions ---------------------------------------------------------------------

    def propose(self, player, give, get):
        try:
            spec = deal_spec(give, get)
        except ValueError as e:
            return f"error: {e}"
        if diplomacy.get_diplomacy(self.t):
            return "error: a leader is waiting for your answer; use respond_to_leader first"
        err = self._check_turn(player)
        if err:
            return err
        before = self._deals()
        name, err = self._open_leader(player)
        if err:
            return err
        try:
            self.t.run("OnTrade()", state="LeaderHeadRoot", timeout=3)
            if not self._wait("DiploTrade"):
                return f"error: {name} wouldn't open the trade screen"
            built = self._in_game(f"print(_AI.build_deal({player}, {_lua_str(spec)}))")
            if not built.startswith("ok"):
                return built or "error: couldn't put the deal together"
            self.t.run("OnPropose()", state="DiploTrade", timeout=3)
            after, end = before, time.monotonic() + 4
            while time.monotonic() < end:
                time.sleep(0.5)
                after = self._deals()
                if before is not None and after is not None and after > before:
                    break
            speech = self._speech()
        except (TunerError, KeyError) as e:
            return f"error: the trade screen failed ({e})"
        finally:
            self._close()
        said = f" They said: \"{speech}\"" if speech else ""
        what = f"you give {', '.join(give) or 'nothing'}, you get {', '.join(get) or 'nothing'}"
        if before is not None and after is not None:
            if after > before:
                return f"ok: {name} accepted the deal ({what}).{said}"
            return (f"error: {name} refused the deal ({what}).{said} Offer them more, ask for less, "
                    "or try a different deal.")
        return f"ok: offer sent to {name} ({what}); check next turn's state to see if it went through.{said}"

    def declare_friendship(self, player):
        if diplomacy.get_diplomacy(self.t):
            return "error: a leader is waiting for your answer; use respond_to_leader first"
        err = self._check_turn(player)
        if err:
            return err
        name, err = self._open_leader(player)
        if err:
            return err
        try:
            r = self._in_game(f"""
local ev = FromUIDiploEventTypes and FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DISCUSSION_WORK_WITH_US
if not ev then print("error: this game version has no friendship request") return end
if Players[Game.GetActivePlayer()]:IsDoF({player}) then print("error: you are already friends") return end
Game.DoFromUIDiploEvent(ev, {player}, 0, 0)
print("ok")""")
            if not r.startswith("ok"):
                return r
            friends = False
            end = time.monotonic() + 4
            while time.monotonic() < end and not friends:
                time.sleep(0.5)
                friends = self._in_game(f"print(Players[Game.GetActivePlayer()]:IsDoF({player}))") == "true"
            speech = self._speech()
        except (TunerError, KeyError) as e:
            return f"error: the leader screen failed ({e})"
        finally:
            self._close()
        said = f" They said: \"{speech}\"" if speech else ""
        if friends:
            return f"ok: {name} declared friendship with you.{said}"
        return f"error: {name} declined friendship.{said} Improve relations first (trades, shared enemies, gifts)."
