"""AI leaders talking to us: discussion dialogs and trade offers.

These screens are their own Lua states (DiscussionDialog, DiploTrade,
SimpleDiploTrade). We read what is on screen there and answer by calling the
same global handlers the buttons use: OnButton1..8 in the discussion dialog,
OnPropose (accept) and OnBack (refuse) on the trade screen.
"""
from .tuner import TunerError

DISCUSSION = """
if ContextPtr:IsHidden() then return end
print("SPEECH\\t" .. Controls.LeaderSpeech:GetText())
for i = 1, 8 do
	local b = Controls["Button" .. i]
	if b and not b:IsHidden() and not b:IsDisabled() then
		print("OPTION\\t" .. i .. "\\t" .. Controls["Button" .. i .. "Label"]:GetText())
	end
end
"""

TRADE = """
if ContextPtr:IsHidden() then return end
local me = Game.GetActivePlayer()
local names = {}
for k, v in pairs(TradeableItems) do names[v] = tostring(k):gsub("^TRADE_ITEM_", "") end
local function who(id) return id == me and "you" or Players[id]:GetCivilizationShortDescription() end
print("SPEECH\\t" .. Controls.DiscussionText:GetText())
if not Controls.ProposeButton:IsHidden() then print("OPTION\\t1\\t" .. Controls.ProposeButton:GetText()) end
if not Controls.CancelButton:IsHidden() then print("OPTION\\t2\\t" .. Controls.CancelButton:GetText()) end
local deal = UI.GetScratchDeal()
deal:ResetIterator()
for i = 1, deal:GetNumItems() do
	local itemType, duration, finalTurn, data1, data2, data3, flag1, fromPlayer = deal:GetNextItem()
	local what = names[itemType] or tostring(itemType)
	if itemType == TradeableItems.TRADE_ITEM_GOLD or itemType == TradeableItems.TRADE_ITEM_GOLD_PER_TURN then
		what = what .. " " .. data1
	elseif itemType == TradeableItems.TRADE_ITEM_RESOURCES then
		what = what .. " " .. GameInfo.Resources[data1].Type .. " x" .. data2
	elseif itemType == TradeableItems.TRADE_ITEM_CITIES then
		local city = Map.GetPlot(data1, data2):GetPlotCity()
		what = what .. " " .. (city and city:GetName() or "?")
	end
	if duration and duration > 0 then what = what .. " for " .. duration .. " turns" end
	print("ITEM\\t" .. who(fromPlayer) .. " give(s) " .. what)
end
"""

SCREENS = [("DiscussionDialog", DISCUSSION), ("DiploTrade", TRADE), ("SimpleDiploTrade", TRADE)]


def get_diplomacy(tuner):
    """Return the open leader screen as {"screen", "speech", "options", "items"}, or None."""
    for screen, lua in SCREENS:
        if screen not in tuner.states:
            continue
        try:
            lines = tuner.run(lua, state=screen, timeout=3)
        except TunerError:
            continue  # screen not readable right now; treat as closed
        if not lines:
            continue
        d = {"screen": screen, "speech": "", "options": {}, "items": []}
        for line in lines:
            tag, _, rest = line.partition("\t")
            if tag == "SPEECH":
                d["speech"] = rest
            elif tag == "OPTION":
                n, _, label = rest.partition("\t")
                if n.isdigit():
                    d["options"][int(n)] = label
            elif tag == "ITEM":
                d["items"].append(rest)
        if d["options"]:
            return d
    return None


def summarize(d):
    out = ["\nA LEADER IS TALKING TO YOU (answer with respond_to_leader):", f'  "{d["speech"]}"']
    if d["items"]:
        out.append("  The deal on the table:")
        out.extend(f"    {item}" for item in d["items"])
    out.append("  Options: " + "; ".join(f"{n} = {label}" for n, label in d["options"].items()))
    return "\n".join(out)


def respond(tuner, option):
    d = get_diplomacy(tuner)
    if d is None:
        return "error: no leader is waiting for an answer"
    option = int(option)
    if option not in d["options"]:
        return f"error: option must be one of {sorted(d['options'])}"
    if d["screen"] == "DiscussionDialog":
        tuner.run(f"OnButton{option}()", state=d["screen"])
    else:
        tuner.run("OnPropose()" if option == 1 else "OnBack()", state=d["screen"])
    return f"ok: answered '{d['options'][option]}'"
