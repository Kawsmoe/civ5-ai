-- Snapshot of the active player's game state for the agent.
--
-- Runs in the InGame Lua state (state.py sends it through the tuner) and
-- prints one tab-separated record per line. The first field is the tag:
--
--   Empire          P    turn, civ, gold, gold/turn, science, culture, faith, happiness,
--                        end-turn blocker, current research, research turns left
--                   T    researchable tech, turns
--                   L    culture stored, next policy cost, free policies, choice due
--                   A    adopted policy or branch
--                   O    BRANCH|POLICY that can be adopted now (when a choice is due)
--                   R    faith, faith/turn, has pantheon, own religion, faith for next pantheon,
--                        religions left to found, faith for next prophet, free techs
--                   RB   belief choice: kind, type, description (when due)
--                   RR   religion that can be founded (when due)
--                   IO   ideology choice (when due)
--   Cities          C    id, name, x, y, pop, food surplus, production, producing,
--                        production turns left, turns to grow
--                   CX   id, hp, max hp, defense, religious majority
--                   CT   city id, terrain counts in its 3-tile radius, river tiles, coastal
--                   CR   city id, resource, class, x, y, improved (resources in its radius)
--                   B    city id, UNIT|BUILDING, type, turns
--                   BUY  city id, GOLD|FAITH, type, cost (only what we can afford now)
--   Units           U    id, type, x, y, moves, max moves, hp, activity, automated, combat
--                   UX   id, strength, ranged strength, xp, xp needed, promotion ready,
--                        destination "x,y" of an earlier move order ("" if none)
--                   UP   unit id, promotion it can take now
--                   UM   unit id, special mission it can do here now
--                   NB   unit id, x, y, terrain (adjacent tiles it can step onto now)
--                   S    unit id, x, y, found value, distance, site info (settle sites near a settler)
--                   UB   unit id, build type, turns (what an idle worker can build where it stands)
--                   WT   unit id, x, y, resource, build type, distance (unimproved resources it can improve)
--                   TR   unit id, x, y, city, connection type, gold, science, food, production
--   Map             E    x, y, owner, unit type, hp, strength, ranged strength (hostile units near us)
--                   RT   UNIT|MELEE|NEAR|CITY, attacker id, target x, target y, forecast,
--                        damage dealt, damage taken (game's own estimate)
--                        (UNIT/CITY: ranged target in range; MELEE: adjacent; NEAR: within 3)
--                   TH   city id, city name, enemy x, y, enemy unit type, distance (enemies near cities)
--                   POI  RUINS|BARBARIAN_CAMP, x, y, nearest unit id, distance
--                   NS   x, y, found value, distance to nearest city, that city, site info
--                        (best spots for new cities around the empire)
--   Other players   K    player id, MAJOR|MINOR, name, at war, can declare war, score, influence
--                   ME   our military might, techs, policies, branches finished, tourism
--                   CV   rival civ: id, name, score, cities, pop, military might, era, techs,
--                        policies, branches, tourism, religion, attitude to us, friends,
--                        they denounced us, we denounced them, nearest dist, their city, our city
--                   CO   rival id, reason for its opinion of us
--                   CW   rival id, world wonder built
--                   RW   player a, player b, AT_WAR|FRIENDS|DENOUNCED
--                   ND   unit id, visible enemies within 2 tiles
--                   SPY  spy id, name, rank, state, city owner id, city id
--                   SC   city owner id, city id, city name, owner name, potential
--   Choices due     ST   player id, tech we can steal from them
--                   GP   FAITH|FREE|MAYA, great person type
--                   LG   league id, votes left, proposals left, IN_SESSION|BETWEEN
--                   LP   ENACT|REPEAL, resolution type/id, choice id, description
--                   LV   ENACT|REPEAL, resolution id, choice id, description
--                   DV   player id, name (diplomatic victory vote candidates)
--                   AR   archaeology choice text
--
-- The parser needs C before a city's other records, U before a unit's, and
-- LG before LP/LV. The game's Lua has no io library; everything goes through print.

local iPlayer = Game.GetActivePlayer()
local p = Players[iPlayer]
local team = Teams[p:GetTeam()]
local block = p:GetEndTurnBlockingType()
local DENOM = GameDefines.MOVE_DENOMINATOR

-- Helpers -------------------------------------------------------------------

local function emit(...)
	local t = {...}
	for i = 1, select("#", ...) do t[i] = tostring(t[i]) end
	print(table.concat(t, "\t"))
end

local function text(key)
	if key == nil or key == "" then return "" end
	local ok, s = pcall(Locale.ConvertTextKey, key)
	return ok and s or key
end

local function blocking(name)
	return block == EndTurnBlockingTypes["ENDTURN_BLOCKING_" .. name]
end

local function terrainName(plot)
	if plot:IsMountain() then return "mountain" end
	local t = GameInfo.Terrains[plot:GetTerrainType()]
	local s = t and t.Type:gsub("^TERRAIN_", ""):lower() or "?"
	if plot:IsHills() then s = s .. " hills" end
	local f = plot:GetFeatureType()
	if f >= 0 and GameInfo.Features[f] then s = s .. " " .. GameInfo.Features[f].Type:gsub("^FEATURE_", ""):lower() end
	return s
end

local RESOURCE_CLASS = {RESOURCECLASS_LUXURY = "luxury", RESOURCECLASS_RUSH = "strategic",
	RESOURCECLASS_MODERN = "strategic", RESOURCECLASS_BONUS = "bonus"}

-- visible resource on a plot: type, class (luxury/strategic/bonus), or nil
local function resourceAt(plot)
	local rid = plot:GetResourceType(team:GetID())
	if rid == nil or rid < 0 or GameInfo.Resources[rid] == nil then return nil end
	local r = GameInfo.Resources[rid]
	return r.Type:gsub("^RESOURCE_", ""), RESOURCE_CLASS[r.ResourceClassType] or "bonus"
end

local function plotsWithin(x, y, radius)
	local list = {}
	for dx = -radius, radius do
		for dy = -radius, radius do
			local plot = Map.GetPlot(x + dx, y + dy)
			if plot and Map.PlotDistance(x, y, plot:GetX(), plot:GetY()) <= radius then list[#list + 1] = plot end
		end
	end
	return list
end

-- what makes a city site good or bad, e.g. "fresh water, coast, hills; WINE, IRON, 2 bonus"
local function siteInfo(plot)
	local tags = {}
	if plot:IsFreshWater() then tags[#tags + 1] = "fresh water" end
	if plot:IsCoastalLand() then tags[#tags + 1] = "coast" end
	if plot:IsHills() then tags[#tags + 1] = "hills" end
	local named, bonus = {}, 0
	for _, near in ipairs(plotsWithin(plot:GetX(), plot:GetY(), 2)) do
		if near:IsRevealed(team:GetID(), false) then
			local res, class = resourceAt(near)
			if class == "bonus" then bonus = bonus + 1 elseif res then named[#named + 1] = res end
		end
	end
	if bonus > 0 then named[#named + 1] = bonus .. " bonus" end
	return table.concat(tags, ", ") .. "; " .. (#named > 0 and table.concat(named, ", ") or "no resources")
end

local function beliefText(id)
	local b = GameInfo.Beliefs[id]
	return b.Type, text(b.ShortDescription) .. ": " .. text(b.Description)
end

local blockNames = {}
for k, v in pairs(EndTurnBlockingTypes) do
	if v >= 0 then blockNames[v] = k:gsub("^ENDTURN_BLOCKING_", "") end
end

-- Empire --------------------------------------------------------------------

local research = p:GetCurrentResearch()
emit("P", Game.GetGameTurn(), p:GetCivilizationShortDescription(), p:GetGold(),
	p:CalculateGoldRate(), p:GetScience(), p:GetTotalJONSCulturePerTurn(),
	p:GetTotalFaithPerTurn(), p:GetExcessHappiness(),
	blockNames[block] or "NONE",
	research >= 0 and GameInfo.Technologies[research].Type or "",
	research >= 0 and p:GetResearchTurnsLeft(research, true) or "")

for tech in GameInfo.Technologies() do
	if p:CanResearch(tech.ID) and not team:IsHasTech(tech.ID) then
		emit("T", tech.Type, p:GetResearchTurnsLeft(tech.ID, true))
	end
end

-- social policies
local choosing = p:GetJONSCulture() >= p:GetNextPolicyCost() or p:GetNumFreePolicies() > 0
emit("L", p:GetJONSCulture(), p:GetNextPolicyCost(), p:GetNumFreePolicies(), choosing)
for b in GameInfo.PolicyBranchTypes() do
	if p:IsPolicyBranchUnlocked(b.ID) then emit("A", b.Type)
	elseif choosing and p:CanUnlockPolicyBranch(b.ID) then emit("O", "BRANCH", b.Type) end
end
for pol in GameInfo.Policies() do
	if p:HasPolicy(pol.ID) then
		if not pol.Type:find("_FINISHER$") then emit("A", pol.Type) end
	elseif choosing and p:CanAdoptPolicy(pol.ID) then emit("O", "POLICY", pol.Type) end
end

-- faith and religion
local myReligion = p:HasCreatedReligion() and GameInfo.Religions[p:GetReligionCreatedByPlayer()].Type or ""
emit("R", p:GetFaith(), p:GetTotalFaithPerTurn(), p:HasCreatedPantheon(), myReligion,
	Game.GetMinimumFaithNextPantheon(), Game.GetNumReligionsStillToFound(),
	p:GetMinimumFaithNextGreatProphet(), p:GetNumFreeTechs())

local function beliefs(kind, list) for _, id in ipairs(list) do emit("RB", kind, beliefText(id)) end end
if blocking("FOUND_PANTHEON") then
	beliefs("PANTHEON", Game.GetAvailablePantheonBeliefs())
elseif blocking("ADD_REFORMATION_BELIEF") then
	beliefs("REFORMATION", Game.GetAvailableReformationBeliefs())
elseif blocking("FOUND_RELIGION") then
	local taken = {}
	for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
		local other = Players[i]
		if other:IsEverAlive() and other:HasCreatedReligion() then taken[other:GetReligionCreatedByPlayer()] = true end
	end
	for r in GameInfo.Religions() do
		if r.Type ~= "RELIGION_PANTHEON" and not taken[r.ID] then emit("RR", r.Type) end
	end
	if not p:HasCreatedPantheon() then beliefs("PANTHEON", Game.GetAvailablePantheonBeliefs()) end
	beliefs("FOUNDER", Game.GetAvailableFounderBeliefs())
	beliefs("FOLLOWER", Game.GetAvailableFollowerBeliefs())
	if p:IsTraitBonusReligiousBelief() then beliefs("BONUS", Game.GetAvailableBonusBeliefs()) end
elseif blocking("ENHANCE_RELIGION") then
	beliefs("FOLLOWER", Game.GetAvailableFollowerBeliefs())
	beliefs("ENHANCER", Game.GetAvailableEnhancerBeliefs())
end

if blocking("CHOOSE_IDEOLOGY") then
	for b in GameInfo.PolicyBranchTypes() do
		if b.PurchaseByLevel then emit("IO", b.Type) end
	end
end

-- Cities --------------------------------------------------------------------

local buyYields = {GOLD = YieldTypes.YIELD_GOLD, FAITH = YieldTypes.YIELD_FAITH}
for c in p:Cities() do
	local cid = c:GetID()
	emit("C", cid, c:GetName(), c:GetX(), c:GetY(), c:GetPopulation(),
		c:FoodDifference(), c:GetYieldRate(YieldTypes.YIELD_PRODUCTION),
		text(c:GetProductionNameKey()), c:IsProduction() and c:GetProductionTurnsLeft() or "",
		c:GetFoodTurnsLeft())
	local rel = c:GetReligiousMajority()
	emit("CX", cid, c:GetMaxHitPoints() - c:GetDamage(), c:GetMaxHitPoints(),
		math.floor(c:GetStrengthValue() / 100), rel >= 0 and GameInfo.Religions[rel].Type or "")
	-- the land the city can work (3-tile radius)
	local counts, order, river = {}, {}, 0
	for _, plot in ipairs(plotsWithin(c:GetX(), c:GetY(), 3)) do
		if plot:IsRevealed(team:GetID(), false) and not plot:IsCity() then
			local t = terrainName(plot)
			if not counts[t] then counts[t] = 0 order[#order + 1] = t end
			counts[t] = counts[t] + 1
			if plot:IsRiver() then river = river + 1 end
			local res, class = resourceAt(plot)
			if res then emit("CR", cid, res, class, plot:GetX(), plot:GetY(), plot:GetImprovementType() >= 0) end
		end
	end
	table.sort(order, function(a, b) return counts[a] > counts[b] end)
	local land = {}
	for i = 1, math.min(8, #order) do land[#land + 1] = order[i] .. " " .. counts[order[i]] end
	emit("CT", cid, table.concat(land, ", "), river, c:IsCoastal())
	for unit in GameInfo.Units() do
		if c:CanTrain(unit.ID) then emit("B", cid, "UNIT", unit.Type, c:GetUnitProductionTurnsLeft(unit.ID)) end
	end
	for b in GameInfo.Buildings() do
		if c:CanConstruct(b.ID) then emit("B", cid, "BUILDING", b.Type, c:GetBuildingProductionTurnsLeft(b.ID, 0)) end
	end
	for label, y in pairs(buyYields) do
		for unit in GameInfo.Units() do
			if c:IsCanPurchase(true, true, unit.ID, -1, -1, y) then
				emit("BUY", cid, label, unit.Type,
					label == "GOLD" and c:GetUnitPurchaseCost(unit.ID) or c:GetUnitFaithPurchaseCost(unit.ID, true))
			end
		end
		for b in GameInfo.Buildings() do
			if c:IsCanPurchase(true, true, -1, b.ID, -1, y) then
				emit("BUY", cid, label, b.Type,
					label == "GOLD" and c:GetBuildingPurchaseCost(b.ID) or c:GetBuildingFaithPurchaseCost(b.ID))
			end
		end
	end
end

-- Hostile units ---------------------------------------------------------------

-- Visible enemy units within `radius` of (x, y), each reported once.
local seenEnemy = {}
local function scanEnemies(x, y, radius)
	for dx = -radius, radius do
		for dy = -radius, radius do
			local plot = Map.GetPlot(x + dx, y + dy)
			if plot and plot:IsVisible(team:GetID(), false)
				and Map.PlotDistance(x, y, plot:GetX(), plot:GetY()) <= radius then
				for i = 0, plot:GetNumUnits() - 1 do
					local eu = plot:GetUnit(i)
					local owner = Players[eu:GetOwner()]
					local key = eu:GetOwner() .. ":" .. eu:GetID()
					if eu:GetOwner() ~= iPlayer and not seenEnemy[key]
						and (owner:IsBarbarian() or team:IsAtWar(owner:GetTeam())) then
						seenEnemy[key] = true
						emit("E", plot:GetX(), plot:GetY(),
							owner:IsBarbarian() and "Barbarians" or owner:GetCivilizationShortDescription(),
							GameInfo.Units[eu:GetUnitType()].Type, 100 - eu:GetDamage(),
							eu:GetBaseCombatStrength(), eu:GetBaseRangedCombatStrength())
					end
				end
			end
		end
	end
end

-- Units ---------------------------------------------------------------------

local SPECIAL_MISSIONS = {"MISSION_SPREAD_RELIGION", "MISSION_REMOVE_HERESY", "MISSION_FOUND_RELIGION",
	"MISSION_ENHANCE_RELIGION", "MISSION_GOLDEN_AGE", "MISSION_DISCOVER", "MISSION_HURRY",
	"MISSION_TRADE", "MISSION_CULTURE_BOMB", "MISSION_GIVE_POLICIES", "MISSION_ONE_SHOT_TOURISM",
	"MISSION_CREATE_GREAT_WORK", "MISSION_BUY_CITY_STATE", "MISSION_SELL_EXOTIC_GOODS",
	"MISSION_PILLAGE", "MISSION_HEAL"}

local connNames = {}
if TradeConnectionTypes then
	for k, v in pairs(TradeConnectionTypes) do connNames[v] = tostring(k):gsub("^TRADE_CONNECTION_", "") end
end

local function settleSites(u, x, y)
	local sites = {}
	local R = 8
	for dx = -R, R do
		for dy = -R, R do
			local plot = Map.GetPlot(x + dx, y + dy)
			if plot and plot:IsRevealed(team:GetID(), false) then
				local d = Map.PlotDistance(x, y, plot:GetX(), plot:GetY())
				if d <= R and p:CanFound(plot:GetX(), plot:GetY()) then
					local v = plot:GetFoundValue(iPlayer)
					if v > 0 then sites[#sites + 1] = {plot:GetX(), plot:GetY(), v, d} end
				end
			end
		end
	end
	table.sort(sites, function(a, b) return a[3] > b[3] end)
	for i = 1, math.min(5, #sites) do
		local sx, sy = sites[i][1], sites[i][2]
		emit("S", u:GetID(), sx, sy, sites[i][3], sites[i][4], siteInfo(Map.GetPlot(sx, sy)))
	end
end

local function tradeRoutes(u)
	local routes = {}
	for _, v in ipairs(p:GetPotentialInternationalTradeRouteDestinations(u)) do
		local plot = Map.GetPlot(v.X, v.Y)
		local city = plot and plot:GetPlotCity()
		local y = {}
		for j, yv in ipairs(v.Yields) do y[j - 1] = yv.Mine / 100 end  -- Yields[j] is yield type j-1, x100
		routes[#routes + 1] = {v.X, v.Y, city and city:GetName() or "?",
			connNames[v.TradeConnectionType] or v.TradeConnectionType,
			y[YieldTypes.YIELD_GOLD] or 0, y[YieldTypes.YIELD_SCIENCE] or 0,
			y[YieldTypes.YIELD_FOOD] or 0, y[YieldTypes.YIELD_PRODUCTION] or 0}
	end
	table.sort(routes, function(a, b) return a[5] + a[6] + a[7] + a[8] > b[5] + b[6] + b[7] + b[8] end)
	for i = 1, math.min(6, #routes) do emit("TR", u:GetID(), unpack(routes[i])) end
end

-- builds that make an improvement or route (not chopping/removing features)
local function realBuild(b)
	return b.ImprovementType ~= nil or b.RouteType ~= nil
end

-- UB: what a worker can build where it stands; WT: nearby unimproved resources it can improve
local function workerOptions(u)
	local here = u:GetPlot()
	for b in GameInfo.Builds() do
		if realBuild(b) and u:CanBuild(here, b.ID) then
			emit("UB", u:GetID(), b.Type, here:GetBuildTurnsLeft(b.ID, iPlayer, 0, 0))
		end
	end
	local targets = {}
	for _, plot in ipairs(plotsWithin(u:GetX(), u:GetY(), 6)) do
		if plot:GetOwner() == iPlayer and plot:GetImprovementType() < 0 and resourceAt(plot) then
			-- the improvement that actually works this resource (e.g. pasture for cattle, not farm)
			local rtype = GameInfo.Resources[plot:GetResourceType(team:GetID())].Type
			local pick
			for row in GameInfo.Improvement_ResourceTypes{ResourceType = rtype} do
				for b in GameInfo.Builds{ImprovementType = row.ImprovementType} do
					if not pick and u:CanBuild(plot, b.ID) then pick = b.Type end
				end
			end
			if pick then
				targets[#targets + 1] = {plot, (resourceAt(plot)), pick,
					Map.PlotDistance(u:GetX(), u:GetY(), plot:GetX(), plot:GetY())}
			end
		end
	end
	table.sort(targets, function(a, b) return a[4] < b[4] end)
	for i = 1, math.min(4, #targets) do
		local t = targets[i]
		emit("WT", u:GetID(), t[1]:GetX(), t[1]:GetY(), t[2], t[3], t[4])
	end
end

for u in p:Units() do
	local uid, x, y = u:GetID(), u:GetX(), u:GetY()
	local hasMoves = u:MovesLeft() > 0
	emit("U", uid, GameInfo.Units[u:GetUnitType()].Type, x, y,
		u:MovesLeft() / DENOM, u:MaxMoves() / DENOM, 100 - u:GetDamage(),
		u:GetActivityType(), u:IsAutomated(), u:IsCombatUnit())
	local ready = u:IsPromotionReady()
	-- where a unit on a multi-turn move order is heading ("" if none)
	local dest = ""
	if u:GetActivityType() == ActivityTypes.ACTIVITY_MISSION then
		local mp = u:LastMissionPlot()
		if mp and (mp:GetX() ~= x or mp:GetY() ~= y) then dest = mp:GetX() .. "," .. mp:GetY() end
	end
	emit("UX", uid, u:GetBaseCombatStrength(), u:GetBaseRangedCombatStrength(),
		u:GetExperience(), u:ExperienceNeeded(), ready, dest)
	if ready then
		for promo in GameInfo.UnitPromotions() do
			if u:CanPromote(promo.ID, -1) then emit("UP", uid, promo.Type) end
		end
	end
	if hasMoves then
		for _, m in ipairs(SPECIAL_MISSIONS) do
			if MissionTypes[m] and u:CanStartMission(MissionTypes[m], -1, -1) then emit("UM", uid, m) end
		end
	end
	if hasMoves and u:GetActivityType() == ActivityTypes.ACTIVITY_AWAKE and not u:IsAutomated() then
		for dir = 0, 5 do
			local adj = Map.PlotDirection(x, y, dir)
			if adj and u:CanMoveOrAttackInto(adj) then emit("NB", uid, adj:GetX(), adj:GetY(), terrainName(adj)) end
		end
	end
	if (GameInfo.Units[u:GetUnitType()].WorkRate or 0) > 0 and hasMoves and not u:IsAutomated()
		and u:GetActivityType() == ActivityTypes.ACTIVITY_AWAKE then
		workerOptions(u)
	end
	if u:IsFound() then settleSites(u, x, y) end
	if GameInfo.Units[u:GetUnitType()].Trade and hasMoves then tradeRoutes(u) end
	scanEnemies(x, y, 3)
end
for c in p:Cities() do scanEnemies(c:GetX(), c:GetY(), 3) end

-- Map: ranged targets and points of interest ------------------------------------

local PREDICTION = {}
for k, v in pairs(CombatPredictionTypes or {}) do
	PREDICTION[v] = (tostring(k):gsub("^COMBAT_PREDICTION_", ""):lower():gsub("_", " "))
end
local function forecast(u, eu)
	local ok, r = pcall(Game.GetCombatPrediction, u, eu)
	return ok and PREDICTION[r] or ""
end

-- expected damage dealt and taken if u attacks eu now, computed like the game's
-- combat preview (EnemyUnitPanel.lua): no randomness, capped at max hp
local function damage(u, eu)
	local ok, dealt, taken = pcall(function()
		local from, to = u:GetPlot(), eu:GetPlot()
		if u:GetBaseRangedCombatStrength() > 0 then
			return u:GetRangeCombatDamage(eu, nil, false), 0
		end
		local mine = u:GetMaxAttackStrength(from, to, eu)
		local theirs = eu:GetMaxDefenseStrength(to, u)
		return u:GetCombatDamage(mine, theirs, u:GetDamage(), false, false, false),
			eu:GetCombatDamage(theirs, mine, eu:GetDamage(), false, false, false)
	end)
	if not ok then return "", "" end
	local maxHP = GameDefines.MAX_HIT_POINTS or 100
	return math.min(dealt, maxHP), math.min(taken, maxHP)
end

for key in pairs(seenEnemy) do
	local owner, id = key:match("^(%-?%d+):(%-?%d+)$")
	local eu = Players[tonumber(owner)]:GetUnitByID(tonumber(id))
	if eu then
		local ex, ey = eu:GetX(), eu:GetY()
		local eplot = eu:GetPlot()
		for u in p:Units() do
			if u:MovesLeft() > 0 and u:IsCombatUnit() then
				local d = Map.PlotDistance(u:GetX(), u:GetY(), ex, ey)
				if u:GetBaseRangedCombatStrength() > 0 then
					if u:CanRangeStrikeAt(ex, ey) then emit("RT", "UNIT", u:GetID(), ex, ey, forecast(u, eu), damage(u, eu)) end
				elseif d == 1 and u:CanMoveOrAttackInto(eplot) then
					emit("RT", "MELEE", u:GetID(), ex, ey, forecast(u, eu), damage(u, eu))
				elseif d <= 3 then
					-- attack() closes in first; still worth knowing the odds
					emit("RT", "NEAR", u:GetID(), ex, ey, forecast(u, eu), damage(u, eu))
				end
			end
		end
		for c in p:Cities() do
			if c:CanRangeStrike() and c:CanRangeStrikeAt(ex, ey, true, true) then
				local ok, dmg = pcall(function() return c:RangeCombatDamage(eu, nil) end)
				emit("RT", "CITY", c:GetID(), ex, ey, "", ok and dmg or "", 0)
			end
			local d = Map.PlotDistance(c:GetX(), c:GetY(), ex, ey)
			if d <= 3 then emit("TH", c:GetID(), c:GetName(), ex, ey, GameInfo.Units[eu:GetUnitType()].Type, d) end
		end
	end
end

-- ND: unit id, visible enemy units within 2 tiles (danger)
for u in p:Units() do
	local n = 0
	for key in pairs(seenEnemy) do
		local owner, id = key:match("^(%-?%d+):(%-?%d+)$")
		local eu = Players[tonumber(owner)]:GetUnitByID(tonumber(id))
		if eu and Map.PlotDistance(u:GetX(), u:GetY(), eu:GetX(), eu:GetY()) <= 2 then n = n + 1 end
	end
	if n > 0 then emit("ND", u:GetID(), n) end
end

local campId = GameInfo.Improvements.IMPROVEMENT_BARBARIAN_CAMP and GameInfo.Improvements.IMPROVEMENT_BARBARIAN_CAMP.ID or -2
local seenPOI = {}
local function scanPOI(cx, cy)
	local R = 10
	for dx = -R, R do
		for dy = -R, R do
			local plot = Map.GetPlot(cx + dx, cy + dy)
			if plot and plot:IsRevealed(team:GetID(), false) then
				local kind = plot:IsGoody() and "RUINS" or (plot:GetImprovementType() == campId and "BARBARIAN_CAMP") or nil
				local key = plot:GetX() .. ":" .. plot:GetY()
				if kind and not seenPOI[key] then
					seenPOI[key] = true
					local best, bestD = -1, 999
					for u in p:Units() do
						local d = Map.PlotDistance(u:GetX(), u:GetY(), plot:GetX(), plot:GetY())
						if d < bestD then best, bestD = u:GetID(), d end
					end
					emit("POI", kind, plot:GetX(), plot:GetY(), best, bestD)
				end
			end
		end
	end
end
for u in p:Units() do scanPOI(u:GetX(), u:GetY()) end
for c in p:Cities() do scanPOI(c:GetX(), c:GetY()) end

-- best places for new cities around the empire, for planning expansion
local candidates, seenSite = {}, {}
for c in p:Cities() do
	for _, plot in ipairs(plotsWithin(c:GetX(), c:GetY(), 10)) do
		local key = plot:GetX() .. ":" .. plot:GetY()
		if not seenSite[key] and plot:IsRevealed(team:GetID(), false) and p:CanFound(plot:GetX(), plot:GetY()) then
			seenSite[key] = true
			local v = plot:GetFoundValue(iPlayer)
			if v > 0 then candidates[#candidates + 1] = {plot = plot, value = v} end
		end
	end
end
table.sort(candidates, function(a, b) return a.value > b.value end)
for i = 1, math.min(5, #candidates) do
	local plot = candidates[i].plot
	local nearest, nearestD = "", 999
	for c in p:Cities() do
		local d = Map.PlotDistance(c:GetX(), c:GetY(), plot:GetX(), plot:GetY())
		if d < nearestD then nearest, nearestD = c:GetName(), d end
	end
	emit("NS", plot:GetX(), plot:GetY(), candidates[i].value, nearestD, nearest, siteInfo(plot))
end

-- Other players ---------------------------------------------------------------

for i = 0, GameDefines.MAX_CIV_PLAYERS - 1 do
	local other = Players[i]
	if i ~= iPlayer and other:IsAlive() and not other:IsBarbarian() and team:IsHasMet(other:GetTeam()) then
		local minor = other:IsMinorCiv()
		emit("K", i, minor and "MINOR" or "MAJOR", other:GetCivilizationShortDescription(),
			team:IsAtWar(other:GetTeam()), team:CanDeclareWar(other:GetTeam()),
			minor and "" or other:GetScore(),
			minor and other:GetMinorCivFriendshipWithMajor(iPlayer) or "")
	end
end

-- Rival civilizations: strength, attitude, relations, proximity, achievements.
local APPROACH = {}
for k, v in pairs(MajorCivApproachTypes or {}) do
	APPROACH[v] = (tostring(k):gsub("^MAJOR_CIV_APPROACH_", ""))
end

local function techsKnown(player)
	local ok, n = pcall(function() return Teams[player:GetTeam()]:GetTeamTechs():GetNumTechsKnown() end)
	return ok and n or ""
end

local function eraName(player)
	local era = GameInfo.Eras[player:GetCurrentEra()]
	return era and era.Type:gsub("^ERA_", ""):lower() or "?"
end

-- ME: our own numbers, to compare against: military might, techs, policies, branches finished, tourism
emit("ME", p:GetMilitaryMight(), techsKnown(p), p:GetNumPolicies(), p:GetNumPolicyBranchesFinished(), p:GetTourism())

local WONDERS = {}
for b in GameInfo.Buildings() do
	local class = GameInfo.BuildingClasses[b.BuildingClass]
	if class and class.MaxGlobalInstances == 1 then WONDERS[#WONDERS + 1] = b end
end

local majors = {}
for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
	local other = Players[i]
	if i ~= iPlayer and other:IsAlive() and team:IsHasMet(other:GetTeam()) then
		majors[#majors + 1] = i
		-- nearest of their cities we have seen, to any of our cities
		local nearD, theirCity, ourCity = 999, "", ""
		for tc in other:Cities() do
			if tc:Plot():IsRevealed(team:GetID(), false) then
				for c in p:Cities() do
					local d = Map.PlotDistance(c:GetX(), c:GetY(), tc:GetX(), tc:GetY())
					if d < nearD then nearD, theirCity, ourCity = d, tc:GetName(), c:GetName() end
				end
			end
		end
		local religion = other:HasCreatedReligion() and GameInfo.Religions[other:GetReligionCreatedByPlayer()].Type or ""
		-- CV: id, name, score, cities, population, military might, era, techs, policies, branches
		--     finished, tourism, religion, their attitude to us (our best guess), friends with us,
		--     they denounced us, we denounced them, nearest distance, their city, our city
		emit("CV", i, other:GetCivilizationShortDescription(), other:GetScore(), other:GetNumCities(),
			other:GetTotalPopulation(), other:GetMilitaryMight(), eraName(other), techsKnown(other),
			other:GetNumPolicies(), other:GetNumPolicyBranchesFinished(), other:GetTourism(), religion,
			APPROACH[p:GetApproachTowardsUsGuess(i)] or "?", other:IsDoF(iPlayer),
			other:IsDenouncedPlayer(iPlayer), p:IsDenouncedPlayer(i),
			nearD < 999 and nearD or "", theirCity, ourCity)
		-- CO: id, a reason the AI gives for its opinion of us (as shown in the game's diplomacy screen)
		local ok, opinions = pcall(function() return other:GetOpinionTable(iPlayer) end)
		if ok and type(opinions) == "table" then
			for _, line in ipairs(opinions) do emit("CO", i, text(tostring(line))) end
		end
		-- CW: id, world wonder they have built
		for tc in other:Cities() do
			for _, b in ipairs(WONDERS) do
				if tc:IsHasBuilding(b.ID) then emit("CW", i, (b.Type:gsub("^BUILDING_", ""))) end
			end
		end
	end
end

-- RW: player a, player b, AT_WAR|FRIENDS|DENOUNCED (relations between rivals we know)
for ai = 1, #majors do
	for bi = ai + 1, #majors do
		local a, b = Players[majors[ai]], Players[majors[bi]]
		if Teams[a:GetTeam()]:IsAtWar(b:GetTeam()) then emit("RW", majors[ai], majors[bi], "AT_WAR")
		elseif a:IsDoF(majors[bi]) then emit("RW", majors[ai], majors[bi], "FRIENDS")
		elseif a:IsDenouncedPlayer(majors[bi]) or b:IsDenouncedPlayer(majors[ai]) then emit("RW", majors[ai], majors[bi], "DENOUNCED")
		end
	end
end

local okSpies, spies = pcall(function() return p:GetEspionageSpies() end)
if okSpies and spies and #spies > 0 then
	for _, v in ipairs(spies) do
		emit("SPY", v.AgentID, text(v.Name), text(v.Rank), text(v.State), v.PlayerID or -1, v.CityID or -1)
	end
	local n = 0
	for _, v in ipairs(p:GetEspionageCityStatus()) do
		local owner = Players[v.PlayerID]
		local city = owner and owner:GetCityByID(v.CityID)
		if city and n < 25 then
			n = n + 1
			emit("SC", v.PlayerID, v.CityID, city:GetName(),
				v.PlayerID == iPlayer and "you" or owner:GetCivilizationShortDescription(), v.Potential or "")
		end
	end
end

-- Choices due this turn -------------------------------------------------------

if blocking("STEAL_TECH") then
	for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
		if i ~= iPlayer and p:GetNumTechsToSteal(i) > 0 then
			local theirTeam = Teams[Players[i]:GetTeam()]
			for tech in GameInfo.Technologies() do
				if theirTeam:IsHasTech(tech.ID) and not team:IsHasTech(tech.ID) and p:CanResearch(tech.ID) then
					emit("ST", i, tech.Type)
				end
			end
		end
	end
end

-- Buying a great person with faith has extra rules, as in the game's own popup.
local FAITH_GP_BRANCH = {UNIT_MERCHANT = "POLICY_BRANCH_COMMERCE", UNIT_SCIENTIST = "POLICY_BRANCH_RATIONALISM",
	UNIT_WRITER = "POLICY_BRANCH_AESTHETICS", UNIT_ARTIST = "POLICY_BRANCH_AESTHETICS",
	UNIT_MUSICIAN = "POLICY_BRANCH_AESTHETICS", UNIT_GREAT_GENERAL = "POLICY_BRANCH_HONOR",
	UNIT_GREAT_ADMIRAL = "POLICY_BRANCH_HONOR", UNIT_ENGINEER = "POLICY_BRANCH_TRADITION"}
local function greatPeople(kind)
	for info in GameInfo.Units{Special = "SPECIALUNIT_PEOPLE"} do
		if p:CanTrain(info.ID, true, true, true, false) then
			local ok = true
			if kind == "FAITH" then
				local branch = FAITH_GP_BRANCH[info.Type]
				if branch then ok = p:IsPolicyBranchFinished(GameInfo.PolicyBranchTypes[branch].ID) end
				if info.Type == "UNIT_PROPHET" then
					ok = p:HasCreatedPantheon() and (p:HasCreatedReligion() or Game.GetNumReligionsStillToFound() > 0)
				end
			end
			if ok then emit("GP", kind, info.Type) end
		end
	end
end
if blocking("FAITH_GREAT_PERSON") and p:GetNumFaithGreatPeople() > 0 then greatPeople("FAITH") end
if blocking("FREE_ITEMS") and p:GetNumFreeGreatPeople() > 0 then greatPeople("FREE") end
if blocking("MAYA_LONG_COUNT") and p:GetNumMayaBoosts() > 0 then greatPeople("MAYA") end

if Game.GetNumActiveLeagues() > 0 and (blocking("LEAGUE_CALL_FOR_PROPOSALS") or blocking("LEAGUE_CALL_FOR_VOTES")) then
	local league = Game.GetActiveLeague()
	emit("LG", league:GetID(), league:GetRemainingVotesForMember(iPlayer),
		league:GetRemainingProposalsForMember(iPlayer), league:IsInSession() and "IN_SESSION" or "BETWEEN")
	if blocking("LEAGUE_CALL_FOR_PROPOSALS") then
		for _, t in ipairs(league:GetInactiveResolutions()) do
			local decision = GameInfo.ResolutionDecisions[GameInfo.Resolutions[t.Type].ProposerDecision].ID
			for _, choice in ipairs(league:GetChoicesForDecision(decision, iPlayer)) do
				if league:CanProposeEnact(t.Type, iPlayer, choice) then
					emit("LP", "ENACT", t.Type, choice, text(league:GetResolutionName(t.Type, -1, choice, false)))
				end
			end
		end
		for _, t in ipairs(league:GetActiveResolutions()) do
			if league:CanProposeRepeal(t.ID, iPlayer) then
				emit("LP", "REPEAL", t.ID, -1, text(league:GetResolutionName(t.Type, t.ID, t.ProposerDecision or -1, false)))
			end
		end
	else
		local function voterChoices(kind, proposals)
			for _, v in ipairs(proposals) do
				local name = text(league:GetResolutionName(v.Type, v.ID, v.ProposerDecision or -1, false))
				local decision = GameInfo.ResolutionDecisions[GameInfo.Resolutions[v.Type].VoterDecision].ID
				for _, choice in ipairs(league:GetChoicesForDecision(decision, iPlayer)) do
					emit("LV", kind, v.ID, choice, name .. " -> " .. text(league:GetTextForChoice(decision, choice)))
				end
			end
		end
		voterChoices("ENACT", league:GetEnactProposals())
		voterChoices("REPEAL", league:GetRepealProposals())
	end
end

if blocking("DIPLO_VOTE") then
	for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do
		local other = Players[i]
		if other:IsAlive() and (i == iPlayer or team:IsHasMet(other:GetTeam())) then
			emit("DV", i, i == iPlayer and "yourself" or other:GetCivilizationShortDescription())
		end
	end
end

-- the game ignores archaeology choices that don't apply to the dig
if blocking("CHOOSE_ARCHAEOLOGY") then
	emit("AR", "LANDMARK: build a landmark tile improvement (culture and tourism; pleases its owner if a city-state)")
	emit("AR", "ARTIFACT: keep an artifact great work for your civ (needs an empty art slot)")
	emit("AR", "ARTIFACT_OTHER: an artifact credited to the other civ involved (needs an empty art slot)")
	emit("AR", "CULTURE: a burst of culture (written artifacts only)")
	emit("AR", "WRITING: keep a written great work (written artifacts; needs an empty writing slot)")
end
