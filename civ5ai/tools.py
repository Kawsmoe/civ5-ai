"""Tool definitions offered to the model (Ollama /api/chat "tools" format).

Each tool name matches a method on actions.Actions, except update_plan and
respond_to_leader, which the agent handles itself.
"""


def tool(name, description, **params):
    """Build one function-calling tool. Parameters are required unless marked optional."""
    required = [k for k, v in params.items() if not v.pop("optional", False)]
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": params, "required": required}}}


def _int(description=None):
    return {"type": "integer", **({"description": description} if description else {})}


def _str(description=None, enum=None, optional=False):
    p = {"type": "string"}
    if description:
        p["description"] = description
    if enum:
        p["enum"] = enum
    if optional:
        p["optional"] = True
    return p


def _unit():
    return _int("unit id from the state")


def _city():
    return _int("city id from the state")


def _replace(what):
    return {"type": "boolean", "optional": True, "description": f"true to {what}"}


TOOLS = [
    # Units
    tool("found_city", "Found a city with a settler on the tile it is standing on.", unit_id=_unit()),
    tool("move_unit", "Move a unit toward a tile. Long moves continue on later turns.",
         unit_id=_unit(), x=_int(), y=_int()),
    tool("fortify", "Fortify a military unit in place (stays until something changes).", unit_id=_unit()),
    tool("sleep", "Put a unit to sleep until something happens nearby.", unit_id=_unit()),
    tool("skip", "Skip this unit's turn.", unit_id=_unit()),
    tool("automate", "Let the game control a unit: 'explore' for scouts, 'build' for workers.",
         unit_id=_unit(), kind=_str(enum=["explore", "build"])),
    tool("build_improvement", "Have a Worker build an improvement or road, e.g. BUILD_FARM, BUILD_MINE, BUILD_PASTURE, "
         "BUILD_ROAD. Without x,y it builds where it stands; with x,y it walks there first and builds on arrival.",
         unit_id=_unit(), build=_str(),
         x={"type": "integer", "optional": True}, y={"type": "integer", "optional": True}),
    tool("promote", "Give a unit one of the promotions listed for it.", unit_id=_unit(), promotion=_str()),
    tool("attack", "Attack the enemy unit or city on tile (x,y) with a unit. Melee units must be adjacent; "
         "ranged units must have it in range.", unit_id=_unit(), x=_int(), y=_int()),
    tool("unit_mission", "Use a unit's special action listed in the state, e.g. MISSION_SPREAD_RELIGION, "
         "MISSION_FOUND_RELIGION, MISSION_DISCOVER, MISSION_HURRY, MISSION_GOLDEN_AGE.",
         unit_id=_unit(), mission=_str()),
    tool("trade_route", "Send a Caravan or Cargo Ship on a trade route to one of its listed destinations.",
         unit_id=_unit(), x=_int(), y=_int()),

    # Cities, research, policies
    tool("set_research", "Choose the tech to research, e.g. TECH_POTTERY.", tech=_str(),
         replace=_replace("abandon research already underway")),
    tool("free_tech", "Take a free tech when one is due.", tech=_str()),
    tool("set_production", "Choose what a city builds, e.g. UNIT_SETTLER or BUILDING_MONUMENT.",
         city_id=_city(), item=_str(), replace=_replace("replace something already being built")),
    tool("buy", "Buy a unit or building in a city right now with gold or faith.",
         city_id=_city(), item=_str(), currency=_str(enum=["GOLD", "FAITH"])),
    tool("city_attack", "Have a city shoot an enemy unit in range.", city_id=_city(), x=_int(), y=_int()),
    tool("adopt_policy", "Spend culture on a social policy: open a branch (POLICY_BRANCH_...) "
         "or adopt a policy inside an open branch (POLICY_...).", policy=_str()),
    tool("choose_ideology", "Adopt an ideology when one is due, e.g. POLICY_BRANCH_FREEDOM.", ideology=_str()),

    # Religion
    tool("found_pantheon", "Pick your pantheon belief (or Reformation belief when that is due), "
         "e.g. BELIEF_GOD_OF_THE_SEA.", belief=_str()),
    tool("found_religion", "Found your religion once a Great Prophet has done MISSION_FOUND_RELIGION.",
         religion=_str("e.g. RELIGION_CHRISTIANITY"), founder_belief=_str(), follower_belief=_str(),
         pantheon_belief=_str("only if you have no pantheon yet", optional=True),
         bonus_belief=_str("only if the state lists BONUS beliefs", optional=True)),
    tool("enhance_religion", "Enhance your religion once a Great Prophet has done MISSION_ENHANCE_RELIGION.",
         follower_belief=_str(), enhancer_belief=_str()),

    # One-off choices
    tool("choose_great_person", "Pick a great person when a choice is due.",
         kind=_str(enum=["FAITH", "FREE", "MAYA"]), unit_type=_str()),
    tool("archaeology", "Make the choice for a finished archaeology dig.",
         choice=_str(enum=["LANDMARK", "ARTIFACT", "ARTIFACT_OTHER", "CULTURE", "WRITING"])),

    # Diplomacy, espionage, World Congress
    tool("respond_to_leader", "Answer a leader who is talking to you, using one of the numbered options shown.",
         option=_int()),
    tool("declare_war", "Declare war on a civ or city-state.", player_id=_int()),
    tool("move_spy", "Send a spy to a city (player_id and city_id from the state), or pass -1 for both to "
         "recall it. as_diplomat=true in another civ's capital makes it a diplomat instead of a thief.",
         spy_id=_int(), player_id=_int(), city_id=_int(),
         as_diplomat={"type": "boolean", "optional": True}),
    tool("stage_coup", "Have a spy in a city-state attempt a coup.", spy_id=_int()),
    tool("steal_tech", "Pick the tech a spy steals.", player_id=_int(), tech=_str()),
    tool("league_propose", "Propose a World Congress resolution from the listed options.",
         kind=_str(enum=["ENACT", "REPEAL"]), id=_int(), choice=_int()),
    tool("league_vote", "Vote on a World Congress proposal. votes = how many of your votes (0 = all remaining).",
         kind=_str(enum=["ENACT", "REPEAL"]), resolution_id=_int(), choice=_int(),
         votes={"type": "integer", "optional": True}),
    tool("league_abstain", "Abstain with all your remaining World Congress votes."),
    tool("diplo_vote", "Cast your diplomatic victory vote for a player.", player_id=_int()),

    # Turn
    tool("update_plan", "Write your strategy and short-term goals; shown back to you every turn.", plan=_str()),
    tool("end_turn", "End your turn once research, production and all units are handled."),
]
