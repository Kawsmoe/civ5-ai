"""Close informational popups that the game leaves on screen.

Each popup is its own Lua state with its own ContextPtr, so we run a small
closer in every popup state. Popups close themselves through one of a few
global functions (OnCloseButtonClicked, OnClose, ClosePopup, ...); if none
exists we dequeue or hide the context directly.

Decision popups (pantheon, ideology, votes, leaders talking to us...) are
left open at the start of a turn so the agent can answer them, then closed
with keep_choices=False before the turn ends.
"""
import re

from .tuner import TunerError

POPUP = re.compile(r"Popup|AdvisorModal|LeaderHeadRoot|DiscussionDialog|DiploTrade")
KEEP_OPEN = re.compile(r"^Choose|DiploVotePopup|LeagueProjectPopup|LeaderHeadRoot|DiscussionDialog|DiploTrade|"
                       r"VoteResultsPopup|GreatWorkPopup")

CLOSER = """
if ContextPtr == nil or ContextPtr:IsHidden() then return end
-- no _G in the game's Lua, so name the candidates directly (nil if undefined)
local fns = {OnCloseButtonClicked, OnClose, ClosePopup, Close, OnContinue, OnBack, OnReturn}
for i = 1, 7 do
	if type(fns[i]) == "function" then pcall(fns[i]) break end
end
if not ContextPtr:IsHidden() then pcall(function() UIManager:DequeuePopup(ContextPtr) end) end
if not ContextPtr:IsHidden() then ContextPtr:SetHide(true) end
print("closed")
"""


def close_popups(tuner, keep_choices=True):
    """Close every open informational popup; return the names closed.

    keep_choices leaves decision popups open (the religion popup also holds
    the holy city's coordinates); pass False once the turn's choices are made.
    """
    closed = []
    for sid, name in tuner.state_list:
        if not POPUP.search(name) or (keep_choices and KEEP_OPEN.search(name)):
            continue
        try:
            if tuner.run(CLOSER, state=sid, timeout=2) == ["closed"]:
                closed.append(name)
        except TunerError:
            pass  # a popup's own close handler failed; nothing more to do
    return closed


if __name__ == "__main__":
    from .tuner import Tuner
    with Tuner() as t:
        print("closed:", close_popups(t) or "nothing open")
