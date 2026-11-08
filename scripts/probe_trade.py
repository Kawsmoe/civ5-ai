"""Check that the game functions trade.py relies on exist, without proposing anything.

Run with the game loaded and the agent stopped (only one FireTuner connection):
    py scripts/probe_trade.py
Then, to see the Trade lines the model gets:
    py scripts/probe_trade.py --state
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from civ5ai.state import get_state, summarize  # noqa: E402
from civ5ai.tuner import Tuner  # noqa: E402

IN_GAME = """
local function has(name, v) print(name .. "\\t" .. (v ~= nil and "yes" or "MISSING")) end
local deal = UI.GetScratchDeal()
has("UI.GetScratchDeal", UI.GetScratchDeal)
has("UI.GetNumCurrentDeals", UI.GetNumCurrentDeals)
has("UI.GetLeaderHeadRootUp", UI.GetLeaderHeadRootUp)
has("UI.RequestLeaveLeader", UI.RequestLeaveLeader)
has("Game.GetDealDuration", Game.GetDealDuration)
has("Game.DoFromUIDiploEvent", Game.DoFromUIDiploEvent)
has("FROM_UI_DIPLO_EVENT_HUMAN_DISCUSSION_WORK_WITH_US",
    FromUIDiploEventTypes and FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DISCUSSION_WORK_WITH_US)
has("Player:DoBeginDiploWithHuman", Players[0].DoBeginDiploWithHuman)
has("Player:IsDoF", Players[0].IsDoF)
for _, m in ipairs({"ClearItems", "SetFromPlayer", "SetToPlayer", "IsPossibleToTradeItem", "AddGoldTrade",
		"AddGoldPerTurnTrade", "AddResourceTrade", "AddOpenBorders", "AddAllowEmbassy", "AddResearchAgreement",
		"AddDefensivePact", "GetNumItems"}) do
	has("Deal:" .. m, deal and deal[m])
end
for _, k in ipairs({"TRADE_ITEM_GOLD", "TRADE_ITEM_GOLD_PER_TURN", "TRADE_ITEM_RESOURCES", "TRADE_ITEM_OPEN_BORDERS",
		"TRADE_ITEM_ALLOW_EMBASSY", "TRADE_ITEM_RESEARCH_AGREEMENT", "TRADE_ITEM_DEFENSIVE_PACT"}) do
	has(k, TradeableItems[k])
end
"""

SCREEN = 'print("{name}\\t" .. (type({fn}) == "function" and "yes" or "MISSING"))'


def main():
    with Tuner() as t:
        for line in t.run(IN_GAME):
            print(line)
        for state, fn in (("LeaderHeadRoot", "OnTrade"), ("LeaderHeadRoot", "OnReturn"),
                          ("DiploTrade", "OnPropose"), ("DiploTrade", "OnBack")):
            if state not in t.list_states():
                print(f"{state}.{fn}\tMISSING (no {state} Lua state)")
                continue
            for line in t.run(SCREEN.format(name=f"{state}.{fn}", fn=fn), state=state):
                print(line)
        if "--state" in sys.argv:
            text = summarize(get_state(t))
            print("\n".join(l for l in text.splitlines() if "Trade (" in l or "declare_friendship" in l)
                  or "(no Trade lines: no AI civ met yet, or the DT records failed)")


if __name__ == "__main__":
    main()
