-- Actions the agent can take, installed as the global table _AI in the
-- InGame Lua state. Each function checks legality first and returns a short
-- string starting with "ok:" or "error:", which is shown to the model as-is.
-- actions.py installs this once per connection and calls e.g.
--   print(_AI.found_city(8192))
--
--   Units       found_city, move_unit, fortify, sleep, skip, automate, promote,
--               build_improvement,
--               attack, unit_mission, trade_route
--   Empire      set_research, free_tech, set_production, buy, city_attack,
--               adopt_policy, choose_ideology, end_turn
--   Religion    found_pantheon (also Reformation), found_religion, enhance_religion
--   Diplomacy   declare_war, diplo_vote, league_propose, league_vote, league_abstain
--   Espionage   move_spy, stage_coup, steal_tech
--   Choices     choose_great_person, archaeology
--
-- Where the game's own UI goes through Network.Send* or a selection message,
-- we use the same call, so the game handles it exactly like a player's click.

_AI = {}

-- Helpers -------------------------------------------------------------------

local function me() return Players[Game.GetActivePlayer()] end

local function unit(uid)
	-- GetUnitByID looks up by slot and ignores the rest of the id, so check it
	local u = me():GetUnitByID(uid)
	if u == nil or u:GetID() ~= uid then return nil, "error: no unit with id " .. tostring(uid) end
	return u
end

local function name(u) return GameInfo.Units[u:GetUnitType()].Type .. " " .. u:GetID() end

-- "8192 Berlin, 16385 Rome" for error messages
local function cityList()
	local t = {}
	for c in me():Cities() do t[#t + 1] = c:GetID() .. " " .. c:GetName() end
	return #t > 0 and table.concat(t, ", ") or "none"
end

local function getCity(cid)
	local c = me():GetCityByID(cid)
	if c == nil then return nil, "error: no city with id " .. tostring(cid) .. ". Your cities (id name): " .. cityList() end
	return c
end

-- a few things a city can build now, cheapest first, e.g. "UNIT_WARRIOR, BUILDING_MONUMENT"
local function buildOptions(c, n)
	local opts = {}
	for u in GameInfo.Units() do
		if c:CanTrain(u.ID) then opts[#opts + 1] = {u.Type, c:GetUnitProductionTurnsLeft(u.ID)} end
	end
	for b in GameInfo.Buildings() do
		if c:CanConstruct(b.ID) then opts[#opts + 1] = {b.Type, c:GetBuildingProductionTurnsLeft(b.ID, 0)} end
	end
	table.sort(opts, function(a, b) return a[2] < b[2] end)
	local t = {}
	for i = 1, math.min(n, #opts) do t[#t + 1] = opts[i][1] end
	return table.concat(t, ", ")
end

-- Units ---------------------------------------------------------------------

function _AI.found_city(uid)
	local u, err = unit(uid); if not u then return err end
	if not u:IsFound() then return "error: " .. name(u) .. " cannot found cities" end
	if not u:CanFound(u:GetPlot()) then
		return "error: cannot found a city at (" .. u:GetX() .. "," .. u:GetY() .. ") - too close to another city or bad terrain"
	end
	if u:MovesLeft() <= 0 then return "error: " .. name(u) .. " has no moves left this turn" end
	local plot = u:GetPlot()
	u:PushMission(MissionTypes.MISSION_FOUND)
	local city = plot:GetPlotCity()
	if city then
		-- tell the model the new city's id right away; it can't guess it
		return "ok: founded " .. city:GetName() .. " (city id " .. city:GetID() .. ") at (" .. plot:GetX() .. "," .. plot:GetY()
			.. "). Choose its production now: set_production(city_id=" .. city:GetID() .. ", item=...) with e.g. "
			.. buildOptions(city, 6)
	end
	return "ok: founding city at (" .. plot:GetX() .. "," .. plot:GetY() .. ")"
end

-- the first enemy combat unit on a plot, or nil
local function enemyOn(plot)
	for i = 0, plot:GetNumUnits() - 1 do
		local eu = plot:GetUnit(i)
		if eu:GetOwner() ~= Game.GetActivePlayer() and eu:IsCombatUnit() then return eu end
	end
	return nil
end

function _AI.move_unit(uid, x, y)
	local u, err = unit(uid); if not u then return err end
	local plot = Map.GetPlot(x, y)
	if plot == nil then return "error: (" .. x .. "," .. y .. ") is off the map" end
	if u:GetX() == x and u:GetY() == y then return "error: unit is already at (" .. x .. "," .. y .. ")" end
	if enemyOn(plot) then return "error: an enemy unit is on (" .. x .. "," .. y .. "); use attack instead" end
	if u:MovesLeft() <= 0 then
		-- out of moves (often because an earlier move order used them at the
		-- start of the turn): replace the order; the game carries it out next turn
		u:PushMission(MissionTypes.MISSION_MOVE_TO, x, y)
		return "ok: " .. name(u) .. " has no moves left this turn; it will head to (" .. x .. "," .. y .. ") from next turn"
	end
	-- GeneratePath is not implemented in this build ("NYI"), so push the move
	-- and check whether the unit actually took a step
	local x0, y0 = u:GetX(), u:GetY()
	u:PushMission(MissionTypes.MISSION_MOVE_TO, x, y)
	local arrived = u:GetX() == x and u:GetY() == y
	if not arrived and u:GetX() == x0 and u:GetY() == y0 then
		u:PopMission()  -- don't leave a move queued that couldn't start
		local why = ""
		if not plot:IsRevealed(Players[Game.GetActivePlayer()]:GetTeam(), false) then
			why = " - that tile is unexplored; pick a closer explored tile"
		elseif plot:IsMountain() then why = " - it is a mountain"
		elseif plot:IsWater() and u:GetDomainType() == DomainTypes.DOMAIN_LAND then why = " - it is water"
		elseif plot:IsImpassable() then why = " - it is impassable"
		elseif plot:GetNumUnits() > 0 then why = " - the tile is occupied"
		else why = " - no path from here (water, mountains or units in the way)"
		end
		return "error: " .. name(u) .. " cannot reach (" .. x .. "," .. y .. ")" .. why
			.. ". Use one of the tiles listed under the unit as 'can step to'"
	end
	return "ok: " .. name(u) .. " now at (" .. u:GetX() .. "," .. u:GetY() .. ")"
		.. (arrived and "" or ", still heading to (" .. x .. "," .. y .. ") on later turns")
end

local function mission(uid, missionName, label)
	local u, err = unit(uid); if not u then return err end
	local m = MissionTypes[missionName]
	if not u:CanStartMission(m, -1, -1) then
		return "error: " .. name(u) .. " cannot " .. label .. " here"
	end
	u:PushMission(m)
	return "ok: " .. name(u) .. " will " .. label
end

function _AI.fortify(uid) return mission(uid, "MISSION_FORTIFY", "fortify") end
function _AI.sleep(uid) return mission(uid, "MISSION_SLEEP", "sleep until something happens") end
function _AI.skip(uid) return mission(uid, "MISSION_SKIP", "skip this turn") end

function _AI.automate(uid, kind)
	local u, err = unit(uid); if not u then return err end
	local row = GameInfo.Automates["AUTOMATE_" .. string.upper(kind)]
	if row == nil then return "error: automate kind must be 'explore' or 'build'" end
	if not u:CanDoCommand(CommandTypes.COMMAND_AUTOMATE, row.ID) then
		return "error: " .. name(u) .. " cannot automate " .. kind
	end
	u:DoCommand(CommandTypes.COMMAND_AUTOMATE, row.ID)
	return "ok: " .. name(u) .. " automated (" .. kind .. ")"
end

-- Research, production, policies, ending the turn -------------------------------

function _AI.set_research(techType)
	local p = me()
	local tech = GameInfo.Technologies[techType]
	if tech == nil then return "error: unknown tech " .. tostring(techType) end
	if Teams[p:GetTeam()]:IsHasTech(tech.ID) then return "error: already know " .. techType end
	if not p:CanResearch(tech.ID) then return "error: cannot research " .. techType .. " yet (missing prerequisites)" end
	Network.SendResearch(tech.ID, 0, -1, false)
	return "ok: researching " .. techType
end

function _AI.set_production(cid, itemType)
	local city, err = getCity(cid); if not city then return err end
	local order, id
	if GameInfo.Units[itemType] then
		order, id = OrderTypes.ORDER_TRAIN, GameInfo.Units[itemType].ID
		if not city:CanTrain(id) then return "error: " .. city:GetName() .. " cannot build " .. itemType end
	elseif GameInfo.Buildings[itemType] then
		order, id = OrderTypes.ORDER_CONSTRUCT, GameInfo.Buildings[itemType].ID
		if not city:CanConstruct(id) then return "error: " .. city:GetName() .. " cannot build " .. itemType end
	else
		return "error: unknown unit or building " .. tostring(itemType)
	end
	-- replace whatever is queued; progress on the old item is kept by the game
	city:ClearOrderQueue()
	city:PushOrder(order, id, -1, false, false, true)
	return "ok: " .. city:GetName() .. " now building " .. itemType
end

function _AI.end_turn()
	local p = me()
	local block = p:GetEndTurnBlockingType()
	-- the UNITS blocker can lag behind (e.g. a unit just used its last move),
	-- so trust it only if the game still has a unit waiting for orders
	if block == EndTurnBlockingTypes.ENDTURN_BLOCKING_UNITS then
		local ready = p:GetFirstReadyUnit()
		if ready then return "error: cannot end turn yet, " .. name(ready) .. " needs orders" end
		Game.DoControl(ControlTypes.CONTROL_FORCEENDTURN)
		return "ok: turn ended"
	end
	-- say exactly what is missing, with the ids and options needed to fix it
	if block == EndTurnBlockingTypes.ENDTURN_BLOCKING_PRODUCTION then
		for c in p:Cities() do
			if not c:IsProduction() then
				return "error: cannot end turn yet, " .. c:GetName() .. " (city id " .. c:GetID() .. ") has nothing to build. "
					.. "Use set_production(city_id=" .. c:GetID() .. ", item=...) with e.g. " .. buildOptions(c, 6)
			end
		end
	end
	if block == EndTurnBlockingTypes.ENDTURN_BLOCKING_RESEARCH then
		local techs = {}
		for tech in GameInfo.Technologies() do
			if p:CanResearch(tech.ID) and not Teams[p:GetTeam()]:IsHasTech(tech.ID) then techs[#techs + 1] = tech.Type end
		end
		return "error: cannot end turn yet, choose research with set_research(tech=...): " .. table.concat(techs, ", ")
	end
	-- a city that could fire, or a city-state quest notice, is optional
	if block ~= EndTurnBlockingTypes.NO_ENDTURN_BLOCKING_TYPE
		and block ~= EndTurnBlockingTypes.ENDTURN_BLOCKING_CITY_RANGE_ATTACK
		and block ~= EndTurnBlockingTypes.ENDTURN_BLOCKING_MINOR_QUEST then
		for k, v in pairs(EndTurnBlockingTypes) do
			if v == block then return "error: cannot end turn yet, must handle " .. k:gsub("^ENDTURN_BLOCKING_", "") end
		end
	end
	-- CONTROL_ENDTURN is silently ignored while UI.CanEndTurn() is false
	-- (e.g. a popup is open), so force it; the blockers are checked above
	Game.DoControl(ControlTypes.CONTROL_FORCEENDTURN)
	return "ok: turn ended"
end

-- typeName is a branch (POLICY_BRANCH_TRADITION) or a policy (POLICY_ARISTOCRACY)
function _AI.adopt_policy(typeName)
	local p = me()
	local branch, policy = GameInfo.PolicyBranchTypes[typeName], GameInfo.Policies[typeName]
	if branch then
		if p:IsPolicyBranchUnlocked(branch.ID) then return "error: " .. typeName .. " is already open" end
		if not p:CanUnlockPolicyBranch(branch.ID) then return "error: cannot open " .. typeName .. " now (not enough culture, wrong era, or blocked by another branch)" end
		Network.SendUpdatePolicies(branch.ID, false, true)
		return "ok: opened " .. typeName
	elseif policy then
		if p:HasPolicy(policy.ID) then return "error: already have " .. typeName end
		if not p:CanAdoptPolicy(policy.ID) then return "error: cannot adopt " .. typeName .. " now (not enough culture, branch not open, or prerequisite missing)" end
		Network.SendUpdatePolicies(policy.ID, true, true)
		return "ok: adopted " .. typeName
	end
	return "error: unknown policy or branch " .. tostring(typeName)
end

-- Religion ------------------------------------------------------------------

local function belief(typeName)
	local b = GameInfo.Beliefs[typeName or ""]
	return b and b.ID or nil
end

local function available(list, id)
	for _, v in ipairs(list) do if v == id then return true end end
	return false
end

-- also used for the Reformation belief, which the game adds the same way
function _AI.found_pantheon(beliefType)
	local p = me()
	local id = belief(beliefType)
	if not id then return "error: unknown belief " .. tostring(beliefType) end
	local reform = p:GetEndTurnBlockingType() == EndTurnBlockingTypes.ENDTURN_BLOCKING_ADD_REFORMATION_BELIEF
	local list = reform and Game.GetAvailableReformationBeliefs() or Game.GetAvailablePantheonBeliefs()
	if not available(list, id) then return "error: " .. beliefType .. " is not available right now" end
	Network.SendFoundPantheon(Game.GetActivePlayer(), id)
	return "ok: adopted " .. beliefType
end

-- x, y: the holy city (where the Great Prophet founded it)
function _AI.found_religion(religionType, founder, follower, pantheon, bonus, x, y)
	local p = me()
	local religion = GameInfo.Religions[religionType or ""]
	if religion == nil or religion.Type == "RELIGION_PANTHEON" then return "error: unknown religion " .. tostring(religionType) end
	local f, fo = belief(founder), belief(follower)
	if not (f and available(Game.GetAvailableFounderBeliefs(), f)) then return "error: founder belief " .. tostring(founder) .. " is not available" end
	if not (fo and available(Game.GetAvailableFollowerBeliefs(), fo)) then return "error: follower belief " .. tostring(follower) .. " is not available" end
	-- the game expects the beliefs packed in order: [pantheon], founder, follower, [bonus]
	local send = {}
	if not p:HasCreatedPantheon() then
		local pa = belief(pantheon)
		if not (pa and available(Game.GetAvailablePantheonBeliefs(), pa)) then return "error: you have no pantheon yet, so also pick an available pantheon belief" end
		send[#send + 1] = pa
	end
	send[#send + 1] = f
	send[#send + 1] = fo
	if p:IsTraitBonusReligiousBelief() then
		local bo = belief(bonus)
		if not (bo and available(Game.GetAvailableBonusBeliefs(), bo)) then return "error: you also get a bonus belief; pick an available one" end
		send[#send + 1] = bo
	end
	for i = #send + 1, 4 do send[i] = BeliefTypes.NO_BELIEF end
	Network.SendFoundReligion(Game.GetActivePlayer(), religion.ID, nil, send[1], send[2], send[3], send[4], x, y)
	return "ok: founded " .. religionType
end

function _AI.enhance_religion(follower, enhancer, x, y)
	local p = me()
	if not p:HasCreatedReligion() then return "error: you have not founded a religion" end
	local fo, en = belief(follower), belief(enhancer)
	if not (fo and available(Game.GetAvailableFollowerBeliefs(), fo)) then return "error: follower belief " .. tostring(follower) .. " is not available" end
	if not (en and available(Game.GetAvailableEnhancerBeliefs(), en)) then return "error: enhancer belief " .. tostring(enhancer) .. " is not available" end
	Network.SendEnhanceReligion(Game.GetActivePlayer(), p:GetReligionCreatedByPlayer(), nil, fo, en, x, y)
	return "ok: enhanced religion with " .. follower .. " and " .. enhancer
end

-- Ideology, free tech -----------------------------------------------------

function _AI.choose_ideology(branchType)
	local b = GameInfo.PolicyBranchTypes[branchType or ""]
	if b == nil or not b.PurchaseByLevel then return "error: " .. tostring(branchType) .. " is not an ideology" end
	Network.SendIdeologyChoice(Game.GetActivePlayer(), b.ID)
	return "ok: adopted ideology " .. branchType
end

function _AI.free_tech(techType)
	local p = me()
	local tech = GameInfo.Technologies[techType or ""]
	if tech == nil then return "error: unknown tech " .. tostring(techType) end
	if p:GetNumFreeTechs() <= 0 then return "error: you have no free tech to pick" end
	if not p:CanResearch(tech.ID) then return "error: cannot take " .. techType .. " yet (missing prerequisites)" end
	Network.SendResearch(tech.ID, p:GetNumFreeTechs(), -1, false)
	return "ok: got " .. techType .. " for free"
end

-- More units: promotions, combat, special missions --------------------------------

function _AI.promote(uid, promoType)
	local u, err = unit(uid); if not u then return err end
	local promo = GameInfo.UnitPromotions[promoType or ""]
	if promo == nil then return "error: unknown promotion " .. tostring(promoType) end
	if not u:CanPromote(promo.ID, -1) then return "error: " .. name(u) .. " cannot take " .. promoType .. " now" end
	if type(u.Promote) ~= "function" then return "error: promotions are not supported by this game build" end
	u:Promote(promo.ID, -1)
	return "ok: " .. name(u) .. " promoted with " .. promoType
end

local function describeTarget(x, y)
	local plot = Map.GetPlot(x, y)
	if plot == nil then return "nothing left there" end
	local city = plot:GetPlotCity()
	if city and city:GetOwner() ~= Game.GetActivePlayer() then
		return city:GetName() .. " hp " .. (city:GetMaxHitPoints() - city:GetDamage())
	end
	for i = 0, plot:GetNumUnits() - 1 do
		local eu = plot:GetUnit(i)
		if eu:GetOwner() ~= Game.GetActivePlayer() and eu:IsCombatUnit() then
			return GameInfo.Units[eu:GetUnitType()].Type .. " hp " .. (100 - eu:GetDamage())
		end
	end
	return "nothing left there"
end

local PREDICTION = {}
for k, v in pairs(CombatPredictionTypes or {}) do
	PREDICTION[v] = (tostring(k):gsub("^COMBAT_PREDICTION_", ""):lower():gsub("_", " "))
end

-- the game's own forecast for u attacking eu, e.g. "major victory"
local function prediction(u, eu)
	if eu == nil then return nil end
	local ok, r = pcall(Game.GetCombatPrediction, u, eu)
	return ok and PREDICTION[r] or nil
end

local CAMP = GameInfo.Improvements.IMPROVEMENT_BARBARIAN_CAMP

-- the free land tile next to (x, y) closest to unit u, to attack from
local function attackPosition(u, x, y)
	local best, bestD
	for dir = 0, 5 do
		local adj = Map.PlotDirection(x, y, dir)
		if adj and adj:GetNumUnits() == 0 and not adj:IsWater() and not adj:IsMountain() and not adj:IsImpassable() then
			local d = Map.PlotDistance(u:GetX(), u:GetY(), adj:GetX(), adj:GetY())
			if best == nil or d < bestD then best, bestD = adj, d end
		end
	end
	return best
end

function _AI.attack(uid, x, y)
	local u, err = unit(uid); if not u then return err end
	if u:MovesLeft() <= 0 then return "error: " .. name(u) .. " has no moves left this turn" end
	local plot = Map.GetPlot(x, y)
	if plot == nil then return "error: (" .. x .. "," .. y .. ") is off the map" end
	local eu = enemyOn(plot)
	local before = describeTarget(x, y)
	if before == "nothing left there" then
		-- an empty barbarian camp is cleared just by walking in
		if CAMP and plot:GetImprovementType() == CAMP.ID then return _AI.move_unit(uid, x, y) end
		return "error: no enemy unit or city at (" .. x .. "," .. y .. ")"
	end

	if u:GetBaseRangedCombatStrength() > 0 then
		if not u:CanRangeStrikeAt(x, y) then return "error: (" .. x .. "," .. y .. ") is out of range or not visible for " .. name(u) end
		local odds = prediction(u, eu)
		u:PushMission(MissionTypes.MISSION_RANGE_ATTACK, x, y)
		return "ok: " .. name(u) .. " fired" .. (odds and " (forecast: " .. odds .. ")" or "")
			.. ". Target before: " .. before .. "; after: " .. describeTarget(x, y)
	end

	if not u:IsCombatUnit() then return "error: " .. name(u) .. " cannot attack" end
	if Map.PlotDistance(u:GetX(), u:GetY(), x, y) > 1 then
		-- close in first, like right-clicking a target a few tiles away
		local spot = attackPosition(u, x, y)
		if spot == nil then return "error: no free land tile next to (" .. x .. "," .. y .. ") to attack from" end
		local moved = _AI.move_unit(uid, spot:GetX(), spot:GetY())
		if not moved:find("^ok") then return moved end
		if Map.PlotDistance(u:GetX(), u:GetY(), x, y) > 1 or u:MovesLeft() <= 0 then
			return moved .. ". Not next to the target with moves left yet; attack again next turn"
		end
	end
	local odds = prediction(u, eu)
	local x0, y0, moves0 = u:GetX(), u:GetY(), u:MovesLeft()
	u:PushMission(MissionTypes.MISSION_MOVE_TO, x, y)
	local after = describeTarget(x, y)
	if after == before and u:GetX() == x0 and u:GetY() == y0 and u:MovesLeft() == moves0 then
		u:PopMission()
		return "error: the attack on (" .. x .. "," .. y .. ") did not happen"
	end
	return "ok: " .. name(u) .. " attacked" .. (odds and " (forecast: " .. odds .. ")" or "")
		.. ". Target before: " .. before .. "; after: " .. after
		.. ". " .. name(u) .. " hp " .. (100 - u:GetDamage()) .. " at (" .. u:GetX() .. "," .. u:GetY() .. ")"
end

function _AI.city_attack(cid, x, y)
	local city, err = getCity(cid); if not city then return err end
	local plot = Map.GetPlot(x, y)
	if plot == nil then return "error: (" .. x .. "," .. y .. ") is off the map" end
	if not city:CanRangeStrike() then return "error: " .. city:GetName() .. " cannot fire this turn (already fired, or no defenses yet)" end
	if not city:CanRangeStrikeAt(x, y, true, true) then return "error: " .. city:GetName() .. " cannot strike (" .. x .. "," .. y .. ") - out of range or nothing to hit" end
	if plot:IsFighting() then return "error: a fight is already happening at (" .. x .. "," .. y .. "); try again" end
	local before = describeTarget(x, y)
	-- same steps as the game's own city strike (CityBannerManager.lua / WorldView.lua)
	UI.ClearSelectionList()
	UI.SelectCity(city)
	Game.SelectedCitiesGameNetMessage(GameMessageTypes.GAMEMESSAGE_DO_TASK, TaskTypes.TASK_RANGED_ATTACK, x, y)
	UI.ClearSelectedCities()
	UI.SetInterfaceMode(InterfaceModeTypes.INTERFACEMODE_SELECTION)
	return "ok: " .. city:GetName() .. " fired at (" .. x .. "," .. y .. "). Target before: " .. before
		.. " (the result shows in next state)"
end

function _AI.unit_mission(uid, missionName)
	local u, err = unit(uid); if not u then return err end
	local m = MissionTypes[missionName or ""]
	if m == nil then return "error: unknown mission " .. tostring(missionName) end
	if not u:CanStartMission(m, -1, -1) then
		return "error: " .. name(u) .. " cannot do " .. missionName .. " here (it may need to be in or next to a city first)"
	end
	u:PushMission(m)
	return "ok: " .. name(u) .. " did " .. missionName
end

-- Purchasing --------------------------------------------------------------

function _AI.buy(cid, itemType, currency)
	local city, err = getCity(cid); if not city then return err end
	local y = currency == "FAITH" and YieldTypes.YIELD_FAITH or YieldTypes.YIELD_GOLD
	local cannot = "error: " .. city:GetName() .. " cannot buy " .. tostring(itemType) .. " with " .. tostring(currency) .. " (too expensive or not allowed)"
	if GameInfo.Units[itemType or ""] then
		local id = GameInfo.Units[itemType].ID
		if not city:IsCanPurchase(true, true, id, -1, -1, y) then return cannot end
		Game.CityPurchaseUnit(city, id, y)
	elseif GameInfo.Buildings[itemType or ""] then
		local id = GameInfo.Buildings[itemType].ID
		if not city:IsCanPurchase(true, true, -1, id, -1, y) then return cannot end
		Game.CityPurchaseBuilding(city, id, y)
	else
		return "error: unknown unit or building " .. tostring(itemType)
	end
	return "ok: bought " .. itemType .. " in " .. city:GetName() .. " with " .. currency
end

-- Diplomacy -----------------------------------------------------------------

function _AI.declare_war(playerId)
	local other = Players[playerId]
	if other == nil or not other:IsAlive() then return "error: no such player " .. tostring(playerId) end
	local myTeam = Teams[me():GetTeam()]
	if myTeam:IsAtWar(other:GetTeam()) then return "error: already at war with " .. other:GetCivilizationShortDescription() end
	if not myTeam:CanDeclareWar(other:GetTeam()) then
		return "error: cannot declare war on " .. other:GetCivilizationShortDescription() .. " now (peace treaty or agreement in effect)"
	end
	Network.SendChangeWar(other:GetTeam(), true)
	return "ok: declared war on " .. other:GetCivilizationShortDescription()
end

function _AI.diplo_vote(playerId)
	if Players[playerId] == nil then return "error: no such player " .. tostring(playerId) end
	Network.SendDiploVote(playerId)
	return "ok: voted for player " .. playerId
end

-- World Congress --------------------------------------------------------------

local function league()
	if Game.GetNumActiveLeagues() == 0 then return nil end
	return Game.GetActiveLeague()
end

function _AI.league_propose(kind, id, choice)
	local l = league(); if not l then return "error: there is no World Congress yet" end
	local iPlayer = Game.GetActivePlayer()
	if l:GetRemainingProposalsForMember(iPlayer) <= 0 then return "error: you have no proposals left" end
	if kind == "ENACT" then
		if not l:CanProposeEnact(id, iPlayer, choice) then return "error: cannot propose that resolution" end
		Network.SendLeagueProposeEnact(l:GetID(), id, iPlayer, choice)
	elseif kind == "REPEAL" then
		if not l:CanProposeRepeal(id, iPlayer) then return "error: cannot propose repealing that resolution" end
		Network.SendLeagueProposeRepeal(l:GetID(), id, iPlayer)
	else
		return "error: kind must be ENACT or REPEAL"
	end
	return "ok: proposed"
end

function _AI.league_vote(kind, resolutionId, choice, votes)
	local l = league(); if not l then return "error: there is no World Congress yet" end
	local iPlayer = Game.GetActivePlayer()
	local left = l:GetRemainingVotesForMember(iPlayer)
	if votes == nil or votes <= 0 or votes > left then votes = left end
	if votes <= 0 then return "error: you have no votes left" end
	if kind == "ENACT" then
		Network.SendLeagueVoteEnact(l:GetID(), resolutionId, iPlayer, votes, choice)
	elseif kind == "REPEAL" then
		Network.SendLeagueVoteRepeal(l:GetID(), resolutionId, iPlayer, votes, choice)
	else
		return "error: kind must be ENACT or REPEAL"
	end
	return "ok: cast " .. votes .. " votes"
end

function _AI.league_abstain()
	local l = league(); if not l then return "error: there is no World Congress yet" end
	local iPlayer = Game.GetActivePlayer()
	Network.SendLeagueVoteAbstain(l:GetID(), iPlayer, l:GetRemainingVotesForMember(iPlayer))
	return "ok: abstained with remaining votes"
end

-- Espionage -----------------------------------------------------------------

function _AI.move_spy(spyId, ownerId, cityId, asDiplomat)
	-- ownerId/cityId -1 pulls the spy back to the hideout
	Network.SendMoveSpy(Game.GetActivePlayer(), spyId, ownerId, cityId, asDiplomat == true)
	return "ok: spy " .. spyId .. (ownerId < 0 and " recalled" or " moving to city " .. cityId .. " of player " .. ownerId)
end

function _AI.stage_coup(spyId)
	Network.SendStageCoup(Game.GetActivePlayer(), spyId)
	return "ok: spy " .. spyId .. " is attempting a coup"
end

function _AI.steal_tech(playerId, techType)
	local p = me()
	local tech = GameInfo.Technologies[techType or ""]
	if tech == nil then return "error: unknown tech " .. tostring(techType) end
	if p:GetNumTechsToSteal(playerId) <= 0 then return "error: you cannot steal from player " .. tostring(playerId) end
	if not Teams[Players[playerId]:GetTeam()]:IsHasTech(tech.ID) then return "error: they don't have " .. techType end
	Network.SendResearch(tech.ID, 0, playerId, false)
	return "ok: stole " .. techType
end

-- Trade routes --------------------------------------------------------------

function _AI.trade_route(uid, x, y)
	local u, err = unit(uid); if not u then return err end
	if not GameInfo.Units[u:GetUnitType()].Trade then return "error: " .. name(u) .. " is not a caravan or cargo ship" end
	for _, v in ipairs(me():GetPotentialInternationalTradeRouteDestinations(u)) do
		if v.X == x and v.Y == y then
			local plot = Map.GetPlot(x, y)
			u:PushMission(MissionTypes.MISSION_ESTABLISH_TRADE_ROUTE, plot:GetPlotIndex(), v.TradeConnectionType)
			return "ok: " .. name(u) .. " started a trade route to (" .. x .. "," .. y .. ")"
		end
	end
	return "error: (" .. x .. "," .. y .. ") is not a trade route destination for " .. name(u)
end

-- Great person and archaeology choices ----------------------------------------

function _AI.choose_great_person(kind, unitType)
	local p = me()
	local info = GameInfo.Units[unitType or ""]
	if info == nil then return "error: unknown unit " .. tostring(unitType) end
	if kind == "FAITH" then
		if p:GetNumFaithGreatPeople() <= 0 then return "error: no faith great person to choose" end
		Network.SendFaithGreatPersonChoice(Game.GetActivePlayer(), info.ID)
	elseif kind == "FREE" then
		if p:GetNumFreeGreatPeople() <= 0 then return "error: no free great person to choose" end
		Network.SendGreatPersonChoice(Game.GetActivePlayer(), info.ID)
	elseif kind == "MAYA" then
		if p:GetNumMayaBoosts() <= 0 then return "error: no Maya long count bonus to choose" end
		Network.SendMayaBonusChoice(Game.GetActivePlayer(), info.ID)
	else
		return "error: kind must be FAITH, FREE or MAYA"
	end
	return "ok: chose " .. unitType
end

local ARCHAEOLOGY = {LANDMARK = 1, ARTIFACT = 2, ARTIFACT_OTHER = 3, CULTURE = 4, WRITING = 5}

-- unitIndex: the archaeologist (from the game's archaeology popup)
function _AI.archaeology(choice, unitIndex)
	local c = ARCHAEOLOGY[choice or ""]
	if c == nil then return "error: choice must be LANDMARK, ARTIFACT, ARTIFACT_OTHER, CULTURE or WRITING" end
	Network.SendArchaeologyChoice(Game.GetActivePlayer(), unitIndex, c)
	return "ok: chose " .. choice
end

-- Workers -------------------------------------------------------------------

local function hasTech(techType)
	local tech = techType and GameInfo.Technologies[techType]
	return tech == nil or Teams[me():GetTeam()]:IsHasTech(tech.ID)
end

-- the build that improves the resource on a plot, and the tech still missing for it (or nil):
-- e.g. "BUILD_PLANTATION", "TECH_CALENDAR". Also used by state.lua.
function _AI.resource_need(plot)
	local rid = plot:GetResourceType(me():GetTeam())
	if rid == nil or rid < 0 or GameInfo.Resources[rid] == nil then return nil end
	for row in GameInfo.Improvement_ResourceTypes{ResourceType = GameInfo.Resources[rid].Type} do
		for b in GameInfo.Builds{ImprovementType = row.ImprovementType} do
			local missing = not hasTech(b.PrereqTech) and b.PrereqTech or nil
			local f = plot:GetFeatureType()
			if not missing and f >= 0 and GameInfo.Features[f] then
				for bf in GameInfo.BuildFeatures{BuildType = b.Type, FeatureType = GameInfo.Features[f].Type} do
					if not hasTech(bf.PrereqTech) then missing = bf.PrereqTech end
				end
			end
			return b.Type, missing
		end
	end
	return nil
end

-- why build b can't go on plot, in words the model can act on
local function whyCannotBuild(plot, b)
	if plot:GetOwner() ~= Game.GetActivePlayer() and b.ImprovementType then return "the tile is outside your borders" end
	if not hasTech(b.PrereqTech) then return b.Type .. " needs " .. b.PrereqTech end
	local f = plot:GetFeatureType()
	if f >= 0 and GameInfo.Features[f] then
		for bf in GameInfo.BuildFeatures{BuildType = b.Type, FeatureType = GameInfo.Features[f].Type} do
			if not hasTech(bf.PrereqTech) then
				return "the " .. GameInfo.Features[f].Type:gsub("^FEATURE_", ""):lower() .. " must be cleared first, which needs " .. bf.PrereqTech
			end
		end
	end
	if b.ImprovementType and plot:GetImprovementType() >= 0 then return "the tile already has an improvement" end
	local need, missing = _AI.resource_need(plot)
	if need and need ~= b.Type then
		return "this resource needs " .. need .. (missing and (", which needs " .. missing) or "") .. ", not " .. b.Type
	end
	return b.Type .. " can't be built on this terrain"
end

-- build an improvement (BUILD_FARM, BUILD_MINE, BUILD_ROAD...) on the worker's
-- tile, or on (x, y): the worker walks there and starts building on arrival
function _AI.build_improvement(uid, buildType, x, y)
	local u, err = unit(uid); if not u then return err end
	local b = GameInfo.Builds[buildType or ""]
	if b == nil then return "error: unknown build " .. tostring(buildType) .. " (use a BUILD_ name listed for the worker)" end
	if (GameInfo.Units[u:GetUnitType()].WorkRate or 0) <= 0 then return "error: " .. name(u) .. " cannot build improvements; only Workers can" end
	local plot = (x and y and x >= 0) and Map.GetPlot(x, y) or u:GetPlot()
	if plot == nil then return "error: (" .. tostring(x) .. "," .. tostring(y) .. ") is off the map" end
	local where = "(" .. plot:GetX() .. "," .. plot:GetY() .. ")"
	if not u:CanBuild(plot, b.ID) then
		return "error: cannot build " .. buildType .. " at " .. where .. ": " .. whyCannotBuild(plot, b)
	end
	-- the game only knows the build time once a worker stands on the tile (INT_MAX otherwise)
	local turns = plot:GetBuildTurnsLeft(b.ID, Game.GetActivePlayer(), 0, 0)
	if turns > 1000 then turns = "?" end
	if plot:GetX() == u:GetX() and plot:GetY() == u:GetY() then
		u:PushMission(MissionTypes.MISSION_BUILD, b.ID, -1, 0, 0)
		return "ok: " .. name(u) .. " is building " .. buildType .. " at " .. where .. " (about " .. turns .. " turns)"
	end
	local moved = _AI.move_unit(uid, plot:GetX(), plot:GetY())
	if not moved:find("^ok") then return moved end
	u:PushMission(MissionTypes.MISSION_BUILD, b.ID, -1, 0, 1)  -- 1 = append after the move (the binding wants ints, not booleans)
	return moved .. "; it will build " .. buildType .. " there on arrival (about " .. turns .. " turns of work)"
end
