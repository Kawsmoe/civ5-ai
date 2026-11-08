"""Read the active player's game state and summarize it for the LLM.

get_state(tuner) -> dict  (runs lua/state.lua in the game and parses it)
summarize(state) -> str   (compact text for the model's prompt)
"""
import re
from pathlib import Path

LUA = (Path(__file__).parent / "lua" / "state.lua").read_text()


def _num(s):
    if s == "":
        return None
    try:
        f = float(s)
        return int(f) if f.is_integer() else f
    except ValueError:
        return s


def parse(lines):
    state = {"techs": [], "cities": {}, "units": {}, "enemies": [],
             "policies": [], "policy_options": [], "beliefs": {}, "religion_options": [],
             "ideology_options": [], "ranged_targets": [], "civs": [], "spies": [],
             "spy_targets": [], "steal_options": [], "great_person_options": [],
             "league": None, "diplo_vote_options": [], "archaeology_options": [], "pois": [],
             "new_city_sites": [], "threats": [], "me": None, "rivals": {}, "rival_relations": [],
             "unexplored": None, "tech_goals": [], "city_states": {}, "happy": None, "luxuries": [],
             "victory": [], "total_capitals": None, "leader": "", "traits": [], "uniques": [],
             "trade": None, "trade_routes": [], "trade_in": []}
    for line in lines:
        tag, *f = line.split("\t")
        if tag == "P":
            keys = ["turn", "civ", "gold", "gold_rate", "science", "culture",
                    "faith", "happiness", "blocking", "research", "research_turns"]
            state.update({k: (v if k in ("civ", "blocking", "research") else _num(v))
                          for k, v in zip(keys, f)})
        elif tag == "CIV":
            state["leader"] = f[0]
            state["traits"].append({"name": f[1], "text": f[2] if len(f) > 2 else ""})
        elif tag == "CIVU":
            state["uniques"].append({"kind": f[0], "type": f[1], "replaces": f[2],
                                     "text": f[3] if len(f) > 3 else ""})
        elif tag == "T":
            state["techs"].append({"type": f[0], "turns": _num(f[1]), "unlocks": f[2] if len(f) > 2 else ""})
        elif tag == "TP":
            state["tech_goals"].append({"tech": f[0], "why": f[1], "path": f[2]})
        elif tag == "C":
            cid = int(f[0])
            state["cities"][cid] = {
                "id": cid, "name": f[1], "x": int(f[2]), "y": int(f[3]),
                "pop": _num(f[4]), "food": _num(f[5]), "production": _num(f[6]),
                "producing": f[7], "production_turns": _num(f[8]),
                "growth_turns": _num(f[9]), "can_build": [], "can_buy": [], "resources": [],
                "land": "", "river_tiles": 0, "coastal": False}
        elif tag == "B":
            state["cities"][int(f[0])]["can_build"].append(
                {"kind": f[1], "type": f[2], "turns": _num(f[3])})
        elif tag == "U":
            uid = int(f[0])
            state["units"][uid] = {
                "id": uid, "type": f[1], "x": int(f[2]), "y": int(f[3]),
                "moves": _num(f[4]), "max_moves": _num(f[5]), "hp": _num(f[6]),
                "activity": int(f[7]), "automated": f[8] == "true",
                "combat": f[9] == "true", "sites": [], "promotions": [], "missions": [],
                "routes": [], "homes": [], "steps": [], "builds": [], "work_targets": [], "enemies_near": 0,
                "great_person": "", "gp_builds": [], "gp_trade": None}
        elif tag == "S":
            state["units"][int(f[0])]["sites"].append(
                {"x": int(f[1]), "y": int(f[2]), "value": int(f[3]), "dist": int(f[4]),
                 "info": f[5] if len(f) > 5 else "", "found_in": _num(f[6]) if len(f) > 6 else None,
                 "near_city": f[7] if len(f) > 7 else "", "near_dist": _num(f[8]) if len(f) > 8 else None,
                 "risk": f[9] if len(f) > 9 else ""})
        elif tag == "CT":
            state["cities"][int(f[0])].update(
                {"land": f[1], "river_tiles": _num(f[2]), "coastal": f[3] == "true"})
        elif tag == "CR":
            state["cities"][int(f[0])]["resources"].append(
                {"type": f[1], "class": f[2], "x": int(f[3]), "y": int(f[4]), "improved": f[5] == "true",
                 "needs": f[6] if len(f) > 6 else "", "missing_tech": f[7] if len(f) > 7 else ""})
        elif tag == "NS":
            state["new_city_sites"].append(
                {"x": int(f[0]), "y": int(f[1]), "value": int(f[2]), "dist": int(f[3]),
                 "near": f[4], "info": f[5]})
        elif tag == "E":
            state["enemies"].append({"x": int(f[0]), "y": int(f[1]), "owner": f[2],
                                     "type": f[3], "hp": _num(f[4]),
                                     "strength": _num(f[5]) if len(f) > 5 else None,
                                     "ranged": _num(f[6]) if len(f) > 6 else None})
        elif tag == "ME":
            state["me"] = {"might": _num(f[0]), "techs": _num(f[1]), "policies": _num(f[2]),
                           "branches": _num(f[3]), "tourism": _num(f[4]),
                           "score": _num(f[5]) if len(f) > 5 else None}
        elif tag == "CV":
            state["rivals"][int(f[0])] = {
                "id": int(f[0]), "name": f[1], "score": _num(f[2]), "cities": _num(f[3]),
                "pop": _num(f[4]), "might": _num(f[5]), "era": f[6], "techs": _num(f[7]),
                "policies": _num(f[8]), "branches": _num(f[9]), "tourism": _num(f[10]),
                "religion": f[11], "attitude": f[12], "friends": f[13] == "true",
                "denounced_us": f[14] == "true", "we_denounced": f[15] == "true",
                "dist": _num(f[16]), "their_city": f[17], "our_city": f[18],
                "opinions": [], "wonders": [], "can_give": [], "can_get": []}
        elif tag == "CO":
            state["rivals"][int(f[0])]["opinions"].append(_clean(f[1], 90))
        elif tag == "CW":
            state["rivals"][int(f[0])]["wonders"].append(f[1])
        elif tag == "DT" and int(f[0]) in state["rivals"]:
            side = "can_give" if f[1] == "you" else "can_get"
            state["rivals"][int(f[0])][side].append({"item": f[2], "have": _num(f[3]) if len(f) > 3 else "",
                                                     "class": f[4] if len(f) > 4 else ""})
        elif tag == "RW":
            state["rival_relations"].append({"a": int(f[0]), "b": int(f[1]), "kind": f[2]})
        elif tag == "CS":
            state["city_states"][int(f[0])] = {
                "id": int(f[0]), "trait": f[1], "status": f[2], "influence": _num(f[3]), "ally": f[4],
                "protected": f[5] == "true", "can_pledge": f[6] == "true",
                "gift_influence": _num(f[7]), "gift_cost": _num(f[8]), "quests": ""}
        elif tag == "HP":
            keys = ["excess", "happiness", "unhappiness", "luxuries", "buildings", "policies", "religion",
                    "natural_wonders", "city_states", "world_congress", "u_cities", "u_population",
                    "u_occupied", "u_puppets", "u_specialists"]
            state["happy"] = {k: _num(v) for k, v in zip(keys, f)}
        elif tag == "LX":
            state["luxuries"].append({"type": f[0], "available": int(f[1]), "produced": int(f[2])})
        elif tag == "VC":
            state["victory"].append({
                "id": int(f[0]), "name": f[1], "techs": _num(f[2]), "apollo": _num(f[3]), "parts": _num(f[4]),
                "influential": _num(f[5]), "influence_needed": _num(f[6]), "capitals": _num(f[7]),
                "cs_allies": _num(f[8]), "delegates": _num(f[9])})
        elif tag == "VT":
            state["total_capitals"] = int(f[0])
        elif tag == "EX":
            state["unexplored"] = {"unseen": int(f[0]), "total": int(f[1])}
        elif tag == "ND":
            state["units"][int(f[0])]["enemies_near"] = int(f[1])
        elif tag == "L":
            state.update({"culture_stored": _num(f[0]), "policy_cost": _num(f[1]),
                          "free_policies": _num(f[2]), "policy_due": f[3] == "true"})
        elif tag == "A":
            state["policies"].append(f[0])
        elif tag == "O":
            state["policy_options"].append({"kind": f[0], "type": f[1]})
        elif tag == "R":
            state.update({"faith_stored": _num(f[0]), "faith_rate": _num(f[1]),
                          "has_pantheon": f[2] == "true", "religion": f[3],
                          "pantheon_cost": _num(f[4]), "religions_left": _num(f[5]),
                          "prophet_cost": _num(f[6]), "free_techs": _num(f[7])})
        elif tag == "RB":
            state["beliefs"].setdefault(f[0], []).append({"type": f[1], "text": _clean(f[2])})
        elif tag == "RR":
            state["religion_options"].append(f[0])
        elif tag == "IO":
            state["ideology_options"].append(f[0])
        elif tag == "CX":
            state["cities"][int(f[0])].update({"hp": _num(f[1]), "max_hp": _num(f[2]),
                                               "defense": _num(f[3]), "majority_religion": f[4]})
        elif tag == "BUY":
            state["cities"][int(f[0])]["can_buy"].append(
                {"currency": f[1], "type": f[2], "cost": _num(f[3])})
        elif tag == "UX":
            state["units"][int(f[0])].update({"strength": _num(f[1]), "ranged": _num(f[2]),
                                              "xp": _num(f[3]), "xp_needed": _num(f[4]),
                                              "promotion_ready": f[5] == "true",
                                              "destination": f[6] if len(f) > 6 else "",
                                              "activity_name": f[7] if len(f) > 7 else ""})
        elif tag == "UH":
            state["units"][int(f[0])]["heal"] = {"where": f[1], "city": f[2], "dist": _num(f[3])}
        elif tag == "UP":
            state["units"][int(f[0])]["promotions"].append(f[1])
        elif tag == "UM":
            state["units"][int(f[0])]["missions"].append(f[1])
        elif tag == "RT":
            state["ranged_targets"].append({"kind": f[0], "id": int(f[1]),
                                            "x": int(f[2]), "y": int(f[3]),
                                            "forecast": f[4] if len(f) > 4 else "",
                                            "dealt": _num(f[5]) if len(f) > 5 else None,
                                            "taken": _num(f[6]) if len(f) > 6 else None})
        elif tag == "K":
            state["civs"].append({"id": int(f[0]), "kind": f[1], "name": f[2],
                                  "at_war": f[3] == "true", "can_declare": f[4] == "true",
                                  "score": _num(f[5]), "influence": _num(f[6])})
        elif tag == "SPY":
            state["spies"].append({"id": int(f[0]), "name": f[1], "rank": f[2], "state": f[3],
                                   "owner": int(f[4]), "city": int(f[5])})
        elif tag == "SC":
            state["spy_targets"].append({"owner": int(f[0]), "city": int(f[1]), "name": f[2],
                                         "owner_name": f[3], "potential": _num(f[4])})
        elif tag == "TR":
            state["units"][int(f[0])]["routes"].append(
                {"x": int(f[1]), "y": int(f[2]), "city": f[3], "kind": f[4],
                 "gold": _num(f[5]), "science": _num(f[6]), "food": _num(f[7]), "production": _num(f[8]),
                 "risk": _num(f[9]) if len(f) > 9 else 0})
        elif tag == "TRH":
            state["units"][int(f[0])]["homes"].append({"x": int(f[1]), "y": int(f[2]), "city": f[3]})
        elif tag == "TRS":
            state["trade"] = {"used": _num(f[0]), "available": _num(f[1])}
        elif tag == "TRA":
            state["trade_routes"].append({"from": f[0], "to": f[1], "civ": f[2], "domain": f[3], "turns": _num(f[4]),
                                          "gold": _num(f[5]), "science": _num(f[6]), "food": _num(f[7]),
                                          "production": _num(f[8])})
        elif tag == "TRI":
            state["trade_in"].append({"civ": f[0], "from": f[1], "to": f[2], "gold": _num(f[3]),
                                      "science": _num(f[4])})
        elif tag == "ST":
            state["steal_options"].append({"player": int(f[0]), "tech": f[1]})
        elif tag == "GP":
            state["great_person_options"].append({"kind": f[0], "type": f[1]})
        elif tag == "LG":
            state["league"] = {"id": int(f[0]), "votes": _num(f[1]), "proposals": _num(f[2]),
                               "session": f[3], "propose": [], "vote": []}
        elif tag in ("LP", "LV"):
            state["league"]["propose" if tag == "LP" else "vote"].append(
                {"kind": f[0], "id": int(f[1]), "choice": int(f[2]), "text": _clean(f[3], 160)})
        elif tag == "DV":
            state["diplo_vote_options"].append({"player": int(f[0]), "name": f[1]})
        elif tag == "AR":
            state["archaeology_options"].append(f[0])
        elif tag == "NB":
            state["units"][int(f[0])]["steps"].append({"x": int(f[1]), "y": int(f[2]), "terrain": f[3]})
        elif tag == "UB":
            state["units"][int(f[0])]["builds"].append({"type": f[1], "turns": _num(f[2])})
        elif tag == "WT":
            state["units"][int(f[0])]["work_targets"].append(
                {"x": int(f[1]), "y": int(f[2]), "resource": f[3], "build": f[4], "dist": int(f[5])})
        elif tag == "GPU":
            state["units"][int(f[0])]["great_person"] = f[1]
        elif tag == "GPB":
            state["units"][int(f[0])]["gp_builds"].append(
                {"build": f[1], "x": int(f[2]), "y": int(f[3]), "dist": int(f[4])})
        elif tag == "GPT":
            state["units"][int(f[0])]["gp_trade"] = {"city": f[1], "x": int(f[2]), "y": int(f[3]), "dist": int(f[4])}
        elif tag == "TH":
            state["threats"].append({"city": int(f[0]), "city_name": f[1], "x": int(f[2]), "y": int(f[3]),
                                     "type": f[4], "dist": int(f[5])})
        elif tag == "POI":
            state["pois"].append({"kind": f[0], "x": int(f[1]), "y": int(f[2]),
                                  "unit": int(f[3]), "dist": int(f[4])})
    return state


def _clean(text, limit=110):
    """Strip the game's [ICON_...]/[COLOR_...] markup and shorten."""
    text = re.sub(r"\[[A-Z_]+\]", "", text).replace("  ", " ").strip()
    return text if len(text) <= limit else text[:limit - 3] + "..."


QUESTS = """
local me = Game.GetActivePlayer()
for i = GameDefines.MAX_MAJOR_CIVS, GameDefines.MAX_CIV_PLAYERS - 1 do
	local cs = Players[i]
	if cs and cs:IsAlive() and cs:IsMinorCiv() and Teams[Players[me]:GetTeam()]:IsHasMet(cs:GetTeam()) then
		local ok, text = pcall(GetActiveQuestToolTip, me, i)
		if ok and text and text ~= "" then print("Q\t" .. i .. "\t" .. text:gsub("%[NEWLINE%]", " | ")) end
	end
end
"""


def get_state(tuner):
    state = parse(tuner.run(LUA, timeout=15))
    if state["city_states"] and "DiploList" in tuner.states:
        try:
            for line in tuner.run(QUESTS, state="DiploList", timeout=5):
                tag, _, rest = line.partition("\t")
                cid, _, text = rest.partition("\t")
                if tag == "Q" and cid.isdigit() and int(cid) in state["city_states"]:
                    state["city_states"][int(cid)]["quests"] = _clean(text, 300)
        except Exception:  # quests are a nice-to-have; never fail the turn over them
            pass
    return state


def needs_orders(u):
    # activity 0 = ACTIVITY_AWAKE: not fortified, sleeping or mid-mission
    return u["moves"] > 0 and u["activity"] == 0 and not u["automated"]


def summarize(s):
    out = [
        f"Turn {s['turn']} - you are {s['civ']}.",
        f"Gold {s['gold']} ({s['gold_rate']:+}/turn), science +{s['science']}, "
        f"culture +{s['culture']}, faith +{s['faith']}, happiness {s['happiness']:+}.",
    ]
    if s["blocking"] != "NONE":
        out.append(f"Must handle before ending turn: {s['blocking']}")

    if s["research"]:
        out.append(f"Researching {s['research']} ({s['research_turns']} turns left).")
    else:
        out.append("Researching: NOTHING - pick a tech.")
    techs = sorted(s["techs"], key=lambda t: t["turns"])
    out.append("Techs you can research now:")
    out.extend(f"  {t['type']} ({t['turns']}t)" + (f": {t['unlocks']}" if t["unlocks"] else "") for t in techs)
    if s["tech_goals"]:
        out.append("Techs your land is waiting for (set_research takes the goal tech and queues the path):")
        out.extend(f"  {g['tech']} - {g['why']}: {g['path']}" for g in s["tech_goals"])

    out.append(f"Social policies: {', '.join(s['policies']) or 'none yet'}. "
               f"Culture {s['culture_stored']}/{s['policy_cost']} toward the next one.")
    if s["policy_due"]:
        branches = [o["type"] for o in s["policy_options"] if o["kind"] == "BRANCH"]
        policies = [o["type"] for o in s["policy_options"] if o["kind"] == "POLICY"]
        out.append("  POLICY CHOICE DUE. Can open branches: " + (", ".join(branches) or "none")
                   + ". Can adopt policies: " + (", ".join(policies) or "none"))
    if s["free_techs"]:
        out.append(f"FREE TECH: you can take {s['free_techs']} tech(s) for free (free_tech).")
    if s["ideology_options"]:
        out.append("IDEOLOGY CHOICE DUE: " + ", ".join(s["ideology_options"]))

    # Faith and religion
    if s["religion"]:
        rel = f"you founded {s['religion']}"
    elif s["has_pantheon"]:
        rel = (f"you have a pantheon; a Great Prophet comes at {s['prophet_cost']} faith "
               f"({s['religions_left']} religions still available to found)")
    else:
        rel = f"no pantheon yet; one can be founded at {s['pantheon_cost']} faith"
    out.append(f"Faith {s['faith_stored']} ({s['faith_rate']:+}/turn): {rel}.")
    if s["religion_options"]:
        out.append("  RELIGION CHOICE DUE. Religions you can found: " + ", ".join(s["religion_options"]))
    for kind, options in s["beliefs"].items():
        out.append(f"  {kind} beliefs you can pick:")
        out.extend(f"    {b['type']}: {b['text']}" for b in options)

    # Other civs, espionage and one-off choices
    out.extend(_trade_section(s))
    out.extend(_civ_section(s))
    out.extend(_victory_section(s))
    out.extend(_rivals_section(s))
    out.extend(_city_states_section(s))
    out.extend(_happiness_section(s))
    minors = [c for c in s["civs"] if c["kind"] == "MINOR"]
    if minors and not s["city_states"]:
        out.append("City-states you know: " + "; ".join(
            f"player {c['id']} {c['name']} (influence {c['influence']}"
            + (", AT WAR" if c["at_war"] else "") + ")" for c in minors))
    if s["spies"]:
        out.append("Spies: " + "; ".join(
            f"spy {p['id']} {p['name']} ({p['rank']}, {p['state']}"
            + (f", in city {p['city']} of player {p['owner']}" if p["city"] >= 0 else ", unassigned") + ")"
            for p in s["spies"]))
        out.append("  Cities a spy can go to: " + "; ".join(
            f"{t['name']} of {t['owner_name']} (player {t['owner']}, city {t['city']}"
            + (f", potential {t['potential']}" if t["potential"] not in (None, "") else "") + ")"
            for t in s["spy_targets"]))
    if s["steal_options"]:
        out.append("STEAL A TECH (steal_tech): " + ", ".join(
            f"{o['tech']} from player {o['player']}" for o in s["steal_options"]))
    if s["great_person_options"]:
        kind = s["great_person_options"][0]["kind"]
        out.append(f"CHOOSE A GREAT PERSON (choose_great_person, kind {kind}): "
                   + ", ".join(o["type"] for o in s["great_person_options"]))
    if s["archaeology_options"]:
        out.append("ARCHAEOLOGY CHOICE (archaeology):")
        out.extend(f"  {o}" for o in s["archaeology_options"])
    if s["diplo_vote_options"]:
        out.append("DIPLOMATIC VICTORY VOTE (diplo_vote): " + ", ".join(
            f"player {o['player']} {o['name']}" for o in s["diplo_vote_options"]))
    league = s["league"]
    if league:
        out.append(f"WORLD CONGRESS: {league['votes']} votes and {league['proposals']} proposals left.")
        if league["propose"]:
            out.append("  You can propose (league_propose kind, id, choice):")
            out.extend(f"    {o['kind']} id {o['id']} choice {o['choice']}: {o['text']}" for o in league["propose"])
        if league["vote"]:
            out.append("  Vote on (league_vote kind, resolution_id, choice, votes):")
            out.extend(f"    {o['kind']} resolution {o['id']} choice {o['choice']}: {o['text']}" for o in league["vote"])

    out.append("\nCities:" if s["cities"] else "\nCities: none yet.")
    for c in s["cities"].values():
        producing = (f"{c['producing']} ({c['production_turns']}t)"
                     if c["producing"] else "NOTHING - pick production")
        out.append(f"  city {c['id']} {c['name']} at ({c['x']},{c['y']}): pop {c['pop']} "
                   f"(grows in {c['growth_turns']}t, food {c['food']:+}), "
                   f"production {c['production']}, building {producing}")
        if "hp" in c:
            out.append(f"    hp {c['hp']}/{c['max_hp']}, defense {c['defense']}, "
                       f"religion {c['majority_religion'] or 'none'}")
        if c["land"]:
            water = ", coastal" if c["coastal"] else ""
            out.append(f"    land around it: {c['land']}; {c['river_tiles']} river tiles{water}")
        if c["resources"]:
            out.append("    resources nearby: " + "; ".join(
                f"{r['type']} ({r['class']}) at ({r['x']},{r['y']})" + _resource_status(r)
                for r in c["resources"]))
        builds = sorted(c["can_build"], key=lambda b: b["turns"])
        out.append("    can build: " + ", ".join(f"{b['type']} ({b['turns']}t)" for b in builds))
        for currency in ("GOLD", "FAITH"):
            buys = [b for b in c["can_buy"] if b["currency"] == currency]
            if buys:
                buys.sort(key=lambda b: b["cost"])
                out.append(f"    can buy now with {currency.lower()}: "
                           + ", ".join(f"{b['type']} ({b['cost']})" for b in buys))

    military = [u["type"] for u in s["units"].values() if u["combat"]]
    civilian = [u["type"] for u in s["units"].values() if not u["combat"]]
    out.append(f"\nUnits ({len(s['units'])}): {len(military)} military"
               + (f" ({', '.join(military)})" if military else "")
               + f", {len(civilian)} civilian" + (f" ({', '.join(civilian)})" if civilian else "")
               + ". Only these units exist; use their ids.")
    for u in s["units"].values():
        if needs_orders(u):
            flag = " NEEDS ORDERS"
        elif u.get("destination"):
            flag = (f" (on its way to ({u['destination']}) from an earlier order; "
                    "move_unit or attack to give it a new one)")
        elif u.get("activity_name") in ("FORTIFIED", "SLEEP", "SENTRY") and u["moves"] > 0:
            flag = f" ({u['activity_name'].lower()} - idle; give it a new order any time)"
        elif u["moves"] == 0:
            flag = " (no moves left this turn)"
        elif u["automated"]:
            flag = " (automated)"
        else:
            flag = ""
        strength = ""
        if u.get("strength"):
            strength = f" strength {u['strength']}" + (f" ranged {u['ranged']}" if u.get("ranged") else "")
        danger = ""
        if u["enemies_near"]:
            danger = f" - {u['enemies_near']} enemy unit(s) within 2 tiles"
            if u["hp"] is not None and u["hp"] < 50:
                danger += ", BADLY HURT: pull back to heal"
        out.append(f"  unit {u['id']} {u['type']} at ({u['x']},{u['y']}) "
                   f"moves {u['moves']}/{u['max_moves']} hp {u['hp']}/100{strength}{flag}{danger}")
        heal = _heal_line(u)
        if heal:
            out.append("    " + heal)
        if u["promotions"]:
            out.append("    PROMOTION READY: " + ", ".join(
                p + (" (heals 50 hp at once instead of a lasting bonus)" if p == INSTA_HEAL else "")
                for p in u["promotions"]))
        if u.get("great_person"):
            out.extend("    " + line for line in _great_person_lines(u))
        elif u["missions"]:
            out.append("    special actions available here: " + ", ".join(u["missions"]))
        if u["builds"]:
            out.append("    can build here (build_improvement): " + ", ".join(
                f"{b['type']} ({b['turns']}t)" for b in u["builds"]))
        if u["work_targets"]:
            out.append("    unimproved resources it can work on (build_improvement with x,y): " + "; ".join(
                f"{t['resource']} at ({t['x']},{t['y']}) -> {t['build']}, {t['dist']} tiles away"
                for t in u["work_targets"]))
        if u["steps"]:
            out.append("    can step to: " + "; ".join(
                f"({t['x']},{t['y']}) {t['terrain']}" for t in u["steps"]))
        if u["routes"]:
            out.append("    trade route destinations (trade_route): " + "; ".join(
                f"{r['city']} at ({r['x']},{r['y']}) {r['kind']}: gold {r['gold']}, science {r['science']}, "
                f"food {r['food']}, production {r['production']}"
                + (f" - RISK: {r['risk']} hostile unit(s) near the route, it may be plundered" if r.get("risk") else "")
                for r in u["routes"]))
        if u["homes"]:
            out.append("    could move its home city to reach other destinations (trade_home): " + "; ".join(
                f"{h['city']} at ({h['x']},{h['y']})" for h in u["homes"]))
        if u["sites"]:
            best = u["sites"][0]["value"]
            out.append("    best city sites (score = the game's own rating, 100 = best here):")
            out.extend("      " + _site_line(t, best, u, s) for t in u["sites"])
            if not s["cities"]:
                out.append("    FIRST CITY: founding right where the Settler stands, or 1 tile away, is usually "
                           "best; each turn of delay costs growth and production. Only walk further for a "
                           "clearly better site (coast, river, or much higher score).")

    if s["cities"] and not any(u["type"] == "UNIT_SETTLER" for u in s["units"].values()):
        # spell this out: small models keep hunting for the settler they already used
        where = [f"{c['name']} ({b['turns']}t)" for c in s["cities"].values()
                 for b in c["can_build"] if b["type"] == "UNIT_SETTLER"]
        out.append("  You have NO Settler now (it was used up founding a city). "
                   + ("A new UNIT_SETTLER can be built in: " + ", ".join(where) if where
                      else "Settlers can't be built yet (cities need to grow first)."))

    ex = s["unexplored"]
    if ex and ex["unseen"]:
        out.append(f"\nUnexplored land: {ex['unseen']} of the {ex['total']} tiles within 8 of your capital "
                   "are still unexplored.")

    if s["new_city_sites"]:
        best = s["new_city_sites"][0]["value"]
        out.append("\nBest spots for new cities (for planning; a Settler founds them):")
        out.extend(f"  ({t['x']},{t['y']}) score {round(100 * t['value'] / best)}, "
                   f"{t['dist']} tiles from {t['near']} [{t['info']}]" for t in s["new_city_sites"])

    if s["pois"]:
        out.append("\nPoints of interest:")
        for poi in sorted(s["pois"], key=lambda q: q["dist"]):
            label = "ANCIENT RUINS (free reward for the first unit to enter)" if poi["kind"] == "RUINS" \
                else "BARBARIAN CAMP (spawns barbarians; clearing it gives gold)"
            out.append(f"  {label} at ({poi['x']},{poi['y']}), {poi['dist']} tiles from unit {poi['unit']}")

    if s["enemies"]:
        out.append("\nHostile units in sight:")
        for e in s["enemies"]:
            power = f", strength {e['strength']}" if e.get("strength") else ""
            if e.get("ranged"):
                power += f", ranged {e['ranged']}"
            out.append(f"  {e['owner']} {e['type']} at ({e['x']},{e['y']}) hp {e['hp']}{power}")
        for t in attack_options(s):
            odds = (f", forecast: {t['forecast']}" if t["forecast"] else "") + _damage_text(t, s)
            where = f"({t['x']},{t['y']})"
            if t["kind"] == "CITY":
                out.append(f"  city {t['id']} can shoot {where} now (city_attack{odds})")
            elif t["kind"] == "UNIT":
                out.append(f"  unit {t['id']} can shoot {where} now (attack{odds})")
            elif t["kind"] == "MELEE":
                out.append(f"  unit {t['id']} is next to {where} and can attack it now (attack{odds})")
            else:
                out.append(f"  unit {t['id']} is close to {where}; attack moves it next to the target "
                           f"and strikes if it has moves left{odds}")
    else:
        out.append("\nNo hostile units in sight.")

    # Explicit checklist: small models do much better with this than with
    # inferring what still needs doing from the state above.
    todo = []
    if not s["research"]:
        todo.append("pick research (set_research)")
    if s["policy_due"] and s["policy_options"]:
        todo.append("adopt a social policy or open a branch (adopt_policy)")
    if s["free_techs"]:
        todo.append("take your free tech (free_tech)")
    if s["ideology_options"]:
        todo.append("choose an ideology (choose_ideology)")
    if s["blocking"] == "FOUND_PANTHEON":
        todo.append("choose a pantheon belief (found_pantheon)")
    if s["blocking"] == "ADD_REFORMATION_BELIEF":
        todo.append("choose a reformation belief (found_pantheon)")
    if s["blocking"] == "FOUND_RELIGION":
        todo.append("found your religion (found_religion)")
    if s["blocking"] == "ENHANCE_RELIGION":
        todo.append("enhance your religion (enhance_religion)")
    for u in s["units"].values():
        if u["promotions"]:
            todo.append(f"promote unit {u['id']} (promote)")
    for t in attack_options(s):
        if t["kind"] == "CITY":
            todo.append(f"fire city {t['id']} at the enemy on ({t['x']},{t['y']}) (city_attack)")
    if s["steal_options"]:
        todo.append("pick a tech to steal (steal_tech)")
    if s["great_person_options"]:
        todo.append("choose a great person (choose_great_person)")
    if s["archaeology_options"]:
        todo.append("make the archaeology choice (archaeology)")
    if s["diplo_vote_options"]:
        todo.append("cast your diplomatic victory vote (diplo_vote)")
    if s["league"] and s["league"]["propose"] and s["league"]["proposals"]:
        todo.append("make a World Congress proposal (league_propose)")
    if s["league"] and s["league"]["vote"] and s["league"]["votes"]:
        todo.append("vote in the World Congress (league_vote or league_abstain)")
    for c in s["cities"].values():
        if not c["producing"]:
            todo.append(f"pick production for city {c['id']} {c['name']} (set_production)")
    for u in s["units"].values():
        if needs_orders(u) and u.get("great_person"):
            todo.append(f"decide how to use Great Person {u['id']} {u['type']} (its options are listed under it)")
        elif needs_orders(u) and u["routes"]:
            todo.append(f"send {u['type']} {u['id']} on a trade route (trade_route; its destinations are listed under it)")
        elif needs_orders(u):
            todo.append(f"give orders to unit {u['id']} {u['type']}")
    for poi in s["pois"]:
        if poi["kind"] == "RUINS":
            todo.append(f"send a unit to the ruins at ({poi['x']},{poi['y']}) (unit {poi['unit']} is closest)")
    out.append("\nTO DO THIS TURN (required): " + ("; ".join(todo) if todo else "nothing required"))

    # Threats and opportunities: things worth acting on beyond the required list.
    threats = [f"{t['type']} at ({t['x']},{t['y']}), {t['dist']} tiles from {t['city_name']}"
               for t in s["threats"]]
    if threats:
        out.append("THREATS: " + "; ".join(threats))
    chances = []
    for t in attack_options(s):
        where = f"({t['x']},{t['y']})"
        if t["kind"] == "CITY":
            chances.append(f"city {t['id']} can shoot {where} (city_attack)")
        elif t["kind"] == "UNIT":
            chances.append(f"unit {t['id']} can shoot {where} (attack)")
        elif "victory" in t["forecast"]:
            chances.append(f"unit {t['id']} can win against {where} ({t['forecast']}; attack)")
    for u in s["units"].values():
        if u["work_targets"]:
            t = u["work_targets"][0]
            chances.append(f"unit {u['id']} could build {t['build']} on {t['resource']} at "
                           f"({t['x']},{t['y']}) (build_improvement)")
    if ex and ex["unseen"] > ex["total"] // 4 and not s["threats"]:
        idle = [u for u in s["units"].values() if u["combat"] and u["moves"] > 0
                and (needs_orders(u) or u.get("activity_name") in ("FORTIFIED", "SLEEP", "SENTRY"))]
        if idle:
            chances.append(f"unit {idle[0]['id']} {idle[0]['type']} could explore ({ex['unseen']} nearby tiles "
                           "unexplored, no enemies near your cities; automate explore or move_unit)")
    chances.extend(_trade_chances(s))
    if chances:
        out.append("OPPORTUNITIES: " + "; ".join(chances))
    out.append("Then call end_turn.")
    return "\n".join(out)


CS_BONUS = {"maritime": "food in your cities", "cultured": "culture", "militaristic": "free military units",
            "mercantile": "happiness and gold", "religious": "faith"}


def _city_states_section(s):
    if not s["city_states"]:
        return []
    names = {c["id"]: c["name"] for c in s["civs"]}
    out = ["\nCity-states (friends get a bonus, the ally gets more; influence decays each turn):"]
    for cs in s["city_states"].values():
        bits = [f"{cs['trait']} - friends get {CS_BONUS.get(cs['trait'], 'a bonus')}", f"you: {cs['status']}",
                f"influence {cs['influence']}"]
        if cs["ally"] and cs["ally"] != "you":
            bits.append(f"ally: {cs['ally']}")
        if cs["protected"]:
            bits.append("you protect it")
        elif cs["can_pledge"]:
            bits.append("you could pledge protection")
        if cs["gift_influence"]:
            bits.append(f"a small gift ({cs['gift_cost']} gold) gives +{cs['gift_influence']} influence")
        out.append(f"  player {cs['id']} {names.get(cs['id'], '?')}: " + ", ".join(bits))
        if cs["quests"]:
            out.append(f"    quests: {cs['quests']}")
    return out


def _happiness_section(s):
    h = s["happy"]
    if not h:
        return []
    plus = [(k, h[k]) for k in ("luxuries", "buildings", "policies", "religion", "natural_wonders",
                                "city_states", "world_congress") if h.get(k)]
    minus = [(k[2:], h[k]) for k in ("u_cities", "u_population", "u_occupied", "u_puppets", "u_specialists")
             if h.get(k)]
    out = [f"\nHappiness {h['excess']:+}: {h['happiness']} happiness ("
           + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in plus) + f") minus {h['unhappiness']} unhappiness ("
           + ", ".join(f"{k} {v:g}" for k, v in minus) + ")."]
    if h["excess"] <= -10:
        out.append("  VERY UNHAPPY: no growth, combat penalty, rebels may appear. Fix this first.")
    elif h["excess"] < 0:
        out.append("  UNHAPPY: cities grow much slower. Get new luxuries, happiness buildings or city-state friends.")
    elif h["excess"] <= 3:
        out.append("  Close to unhappiness: a new city or more population will push you below 0.")
    if s["luxuries"]:
        lux = []
        for x in s["luxuries"]:
            spare = x["available"] - 1
            lux.append(f"{x['type']} x{x['available']}" + (f" ({spare} spare to trade)" if spare > 0 else ""))
        out.append("  Luxuries you have (each different type adds happiness; copies don't): " + ", ".join(lux))
    have = {x["type"] for x in s["luxuries"] if x["available"] > 0}
    nearby = sorted({r["type"] for c in s["cities"].values() for r in c["resources"]
                     if r["class"] == "luxury" and not r["improved"] and r["type"] not in have})
    if nearby:
        out.append("  New luxury types near your cities, not improved yet: " + ", ".join(nearby))
    return out


TRADE_UNITS = ("UNIT_CARAVAN", "UNIT_CARGO_SHIP")


def _free_trade_slots(s):
    """Route slots not used by a route or by a trade unit we already have."""
    t = s.get("trade")
    if not t or not isinstance(t["available"], int) or not isinstance(t["used"], int):
        return 0
    waiting = sum(1 for u in s["units"].values() if u["type"] in TRADE_UNITS or u["routes"])
    return max(0, t["available"] - t["used"] - waiting)


def _trade_section(s):
    """Trade route slots, our routes and what they earn, and rivals' routes into our cities."""
    t = s.get("trade")
    if not t or not t["available"]:
        return []
    free = _free_trade_slots(s)
    out = [f"\nTrade routes: {t['used']} of {t['available']} in use"
           + (f" ({free} free: build a Caravan, or a Cargo Ship in a coastal city, to fill it)" if free else "") + "."]
    for r in s["trade_routes"]:
        gains = [f"+{r[k]} {k}" for k in ("gold", "science", "food", "production") if r[k]]
        to = f"{r['to']} ({r['civ']})" if r["civ"] else r["to"]
        out.append(f"  {r['from']} -> {to}, {r['domain']}: {', '.join(gains) or 'no yield'}"
                   + (f", {r['turns']} turns left" if r["turns"] not in (None, "") else ""))
    for r in s["trade_in"]:
        gains = [f"+{r[k]} {k}" for k in ("gold", "science") if r[k]]
        out.append(f"  {r['civ']}'s route {r['from']} -> your {r['to']}: {', '.join(gains) or 'nothing'} for you"
                   " (they earn from it too; keep good relations or it ends if you go to war)")
    return out


def _trade_chances(s):
    """Opportunities: a free route slot and where a trade unit is quickest to build; routes about to end."""
    out = []
    free = _free_trade_slots(s)
    if free:
        options = [(b["turns"], c["name"], c["id"], b["type"]) for c in s["cities"].values()
                   for b in c["can_build"] if b["type"] in TRADE_UNITS and isinstance(b["turns"], int)]
        if options:
            turns, name, cid, utype = min(options)
            out.append(f"{free} free trade route slot(s): city {cid} {name} can build {utype} in {turns} turns "
                       "(set_production; a trade route earns every turn it runs)")
    for r in s["trade_routes"]:
        if isinstance(r["turns"], int) and r["turns"] <= 1:
            out.append(f"the trade route {r['from']} -> {r['to']} ends now; its unit will need a new trade_route")
    return out


def _civ_section(s):
    """Your leader's ability and your civ's unique units/buildings: what to pick a victory from."""
    if not s["traits"] and not s["uniques"]:
        return []
    out = ["\nYour civilization" +(f" (led by {s['leader']})" if s["leader"] else "")
           + " - pick the victory that uses these strengths:"]
    out.extend(f"  Ability {t['name']}: {_clean(t['text'], 300)}" for t in s["traits"])
    for u in s["uniques"]:
        kind = u["kind"].lower()
        replaces = f", replaces {u['replaces']}" if u["replaces"] else ""
        out.append(f"  Unique {kind} {u['type']}{replaces}: {_clean(u['text'], 200)}")
    return out


def _victory_section(s):
    rows = s["victory"]
    me = next((r for r in rows if r["name"] == "you"), None)
    if not me:
        return []
    rivals = [r for r in rows if r is not me]

    def leader(key):
        return max(rivals, key=lambda r: r[key] or 0) if rivals else None

    def line(label, key, fmt):
        best = leader(key)
        return f"  {label}: you {fmt(me)}" + (f"; best rival {best['name']} {fmt(best)}" if best else "")

    out = ["\nVictory race (your plan should name the victory you are going for):",
           line("Science (techs, then the spaceship)", "techs",
                lambda r: f"{r['techs']} techs, Apollo {'built' if r['apollo'] else 'no'}, {r['parts']} spaceship parts"),
           line("Culture (be influential on every civ)", "influential",
                lambda r: f"influential on {r['influential']} of {r['influence_needed'] or '?'}"),
           line(f"Domination (hold all {s['total_capitals'] or '?'} original capitals)", "capitals",
                lambda r: f"{r['capitals']} capitals"),
           line("Diplomatic (World Leader vote)", "cs_allies",
                lambda r: f"{r['cs_allies']} city-state allies"
                + (f", {r['delegates']} delegates" if r["delegates"] not in (None, "") else ""))]
    return out


# what each Great Person can do: (one-off action, where it works), and what its improvement gives
GREAT_PEOPLE = {
    "SCIENTIST": ("MISSION_DISCOVER: a burst of science toward your research", "anywhere",
                  "an Academy: extra science every turn"),
    "ENGINEER": ("MISSION_HURRY: a burst of production in the city it stands in (best on a wonder)",
                 "inside a city that is building something", "a Manufactory: extra production every turn"),
    "MERCHANT": ("MISSION_TRADE: a lot of gold and city-state influence",
                 "inside a city-state's territory", "a Customs House: extra gold every turn"),
    "ARTIST": ("MISSION_GOLDEN_AGE, or MISSION_CREATE_GREAT_WORK (culture and tourism)",
               "anywhere; a great work needs a city with an empty art slot", ""),
    "WRITER": ("MISSION_GIVE_POLICIES (culture toward a policy), or MISSION_CREATE_GREAT_WORK",
               "anywhere; a great work needs a city with an empty writing slot", ""),
    "MUSICIAN": ("MISSION_ONE_SHOT_TOURISM (a concert tour: tourism with that civ), or MISSION_CREATE_GREAT_WORK",
                 "a concert tour in another civ's territory; a great work needs an empty music slot", ""),
    "GREAT_GENERAL": ("keep it next to your army: +15% combat strength nearby", "with your units",
                      "a Citadel: takes surrounding tiles and damages enemies next to it"),
    "GREAT_ADMIRAL": ("keep it with your fleet (+15%), or repair all your ships", "with your ships", ""),
    "PROPHET": ("MISSION_FOUND_RELIGION / MISSION_ENHANCE_RELIGION / MISSION_SPREAD_RELIGION",
                "inside a city (yours for founding/enhancing, any for spreading)", "a Holy Site: extra faith every turn"),
}


def _great_person_lines(u):
    kind = next((k for k in GREAT_PEOPLE if k in u["great_person"]), None)
    lines = [f"GREAT PERSON - choose how to use it (each use consumes it, except generals/admirals kept with units):"]
    if kind:
        action, where, improvement = GREAT_PEOPLE[kind]
        lines.append(f"  action: {action} - works {where}")
        if improvement:
            lines.append(f"  or build {improvement} (build_improvement with x,y)")
    if u["missions"]:
        lines.append("  possible right where it stands (unit_mission): " + ", ".join(u["missions"]))
    for b in u["gp_builds"]:
        lines.append(f"  nearest tile for {b['build']}: ({b['x']},{b['y']}), {b['dist']} tiles away")
    if u.get("gp_trade"):
        t = u["gp_trade"]
        lines.append(f"  nearest city-state for a trade mission: {t['city']} at ({t['x']},{t['y']}), {t['dist']} tiles away "
                     "(move into its territory, then MISSION_TRADE)")
    return lines


def _reserved_sites(s):
    """Sites a Settler is already walking to: {(x, y): unit id}."""
    out = {}
    for u in s["units"].values():
        if u["type"] == "UNIT_SETTLER" and u.get("destination"):
            x, _, y = u["destination"].partition(",")
            if x.lstrip("-").isdigit() and y.lstrip("-").isdigit():
                out[(int(x), int(y))] = u["id"]
    return out


def _site_line(t, best, unit, s):
    when = t.get("found_in")
    if when is None:
        timing = f"{t['dist']} tiles away"
    elif when == 0:
        timing = "can found this turn"
    else:
        timing = f"city in about {when} turn{'s' if when != 1 else ''}"
    text = f"({t['x']},{t['y']}) score {round(100 * t['value'] / best)}, {timing} [{t['info']}]"
    if t.get("near_city"):
        shares = " - would share tiles with it" if t["near_dist"] is not None and t["near_dist"] <= 5 else ""
        text += f", {t['near_dist']} tiles from {t['near_city']}{shares}"
    if t.get("risk"):
        text += f". RISK: {t['risk']} - send a military unit with the Settler"
    taken = _reserved_sites(s).get((t["x"], t["y"]))
    if taken and taken != unit["id"]:
        text += f". TAKEN: Settler {taken} is already heading here"
    return text


def _resource_status(r):
    if r["improved"]:
        return ""
    if r.get("missing_tech"):
        return f" UNIMPROVED - needs {r['needs']}, which needs {r['missing_tech']}"
    return f" UNIMPROVED - {r['needs']} possible now" if r.get("needs") else " UNIMPROVED"


def _ratio(theirs, ours):
    if not ours or theirs in (None, ""):
        return "?"
    return f"{theirs / ours:.1f}x yours"


def _rivals_section(s):
    """One block per known major civ: strength vs. us, attitude, relations, proximity, wonders."""
    if not s["rivals"]:
        return []
    me = s["me"] or {}
    at_war = {c["id"] for c in s["civs"] if c["at_war"]}
    out = ["\nOther civilizations:"]
    out.append(f"  You: military might {me.get('might')}, {me.get('techs')} techs, {me.get('policies')} policies, "
               f"tourism {me.get('tourism')}.")
    names = {r["id"]: r["name"] for r in s["rivals"].values()}
    for r in s["rivals"].values():
        techs = ""
        if isinstance(r["techs"], int) and isinstance(me.get("techs"), int):
            diff = r["techs"] - me["techs"]
            techs = f", {abs(diff)} techs {'ahead of' if diff > 0 else 'behind'} you" if diff else ", same techs as you"
        relation = ["AT WAR WITH YOU"] if r["id"] in at_war else []
        if r["friends"]:
            relation.append("declared friendship with you")
        if r["denounced_us"]:
            relation.append("has DENOUNCED you")
        if r["we_denounced"]:
            relation.append("you denounced them")
        near = (f" Nearest city {r['their_city']} is {r['dist']} tiles from your {r['our_city']}."
                if r["dist"] not in (None, "") else " None of their cities seen yet.")
        out.append(f"  player {r['id']} {r['name']}: score {r['score']}, {r['cities']} cities (pop {r['pop']}), "
                   f"military {_ratio(r['might'], me.get('might'))}, {r['era']} era{techs}, "
                   f"{r['policies']} policies, tourism {r['tourism']}"
                   + (f", founded {r['religion']}" if r["religion"] else "") + ".")
        out.append(f"    Attitude toward you: {r['attitude']}" + (" (" + ", ".join(relation) + ")" if relation else "")
                   + "." + near)
        if r["opinions"]:
            out.append("    Why: " + "; ".join(r["opinions"][:6]))
        if r["wonders"]:
            out.append("    Wonders: " + ", ".join(r["wonders"]))
        if r["can_give"] or r["can_get"]:
            out.append(f"    Trade (propose_trade with player {r['id']}): you can give "
                       + (", ".join(_trade_item(x, s, mine=True) for x in r["can_give"]) or "nothing")
                       + "; they can give " + (", ".join(_trade_item(x, s) for x in r["can_get"]) or "nothing") + ".")
        if not r["friends"] and not r["denounced_us"] and not r["we_denounced"] and r["id"] not in at_war:
            out.append(f"    You can ask for a declaration of friendship (declare_friendship {r['id']}).")
    for rel in s["rival_relations"]:
        a, b = names.get(rel["a"], rel["a"]), names.get(rel["b"], rel["b"])
        out.append(f"  {a} and {b}: {rel['kind'].replace('_', ' ').lower()}")
    return out


INSTA_HEAL = "PROMOTION_INSTA_HEAL"
HURT = 60  # below this a combat unit gets healing advice
HEAL_RATE = {"CITY": 25, "OWN": 20, "NEUTRAL": 10, "ENEMY": 10}


def _heal_line(u):
    """Healing advice for a hurt combat unit: rate where it stands, and the better place nearby."""
    h = u.get("heal")
    if not h or not u["combat"] or u["hp"] is None or u["hp"] >= HURT:
        return ""
    rate = HEAL_RATE.get(h["where"], 10)
    where = {"CITY": "in your city", "OWN": "in your land", "NEUTRAL": "outside your land",
             "ENEMY": "in enemy land"}.get(h["where"], "here")
    text = (f"HURT ({u['hp']} hp): heals ~{rate}/turn {where} if it doesn't move or attack "
            "(unit_mission MISSION_HEAL, fortify or skip)")
    if h["where"] != "CITY" and h["city"] and isinstance(h["dist"], int):
        text += f"; your city {h['city']} is {h['dist']} tiles away (25/turn there)"
    if INSTA_HEAL in u["promotions"]:
        text += f"; or promote {INSTA_HEAL} to heal 50 hp now"
    return text + "."


def _trade_item(x, s, mine=False):
    """'RESOURCE_WINE (you have 2: spare copy)', 'GOLD (up to 120)', 'OPEN_BORDERS'."""
    item, have = x["item"], x["have"]
    if item in ("GOLD", "GOLD_PER_TURN"):
        return f"{item} (up to {have})"
    if not item.startswith("RESOURCE_"):
        return item
    if x["class"] != "luxury":
        return f"{item} ({'you' if mine else 'they'} have {have})"
    if mine:
        note = "spare copy" if isinstance(have, int) and have > 1 else "your only copy: you'd lose its happiness"
        return f"{item} (luxury, you have {have}: {note})"
    have_it = {"RESOURCE_" + l["type"] for l in s["luxuries"] if l["available"] > 0}
    return f"{item} (luxury" + (", you have it already: no extra happiness)" if item in have_it
                                else ": new for you, +happiness)")


def _damage_text(t, s):
    """'you deal ~35 (enemy 100->65), take ~20 (you 100->80)' from the game's own estimate."""
    if t["dealt"] in (None, ""):
        return ""
    enemy = next((e for e in s["enemies"] if (e["x"], e["y"]) == (t["x"], t["y"])), None)
    ehp = enemy["hp"] if enemy and enemy["hp"] is not None else 100
    text = f"; deals ~{t['dealt']} damage (enemy hp {ehp} -> {max(0, ehp - t['dealt'])})"
    if t["kind"] in ("MELEE", "NEAR") and t["taken"] not in (None, ""):
        mine = s["units"].get(t["id"], {}).get("hp", 100)
        text += f", takes ~{t['taken']} (your hp {mine} -> {max(0, mine - t['taken'])})"
    return text


# the game's combat forecasts, best first
_FORECASTS = ["total victory", "major victory", "small victory", "stalemate",
              "small defeat", "major defeat", "total defeat"]


def attack_options(s):
    """Ranged/melee targets, one per attacker and tile (a tile can hold several units).

    Where a tile has several defenders, keep the most pessimistic forecast: the
    game makes the attacker fight the strongest one.
    """
    best = {}
    for t in s["ranged_targets"]:
        key = (t["kind"], t["id"], t["x"], t["y"])
        rank = _FORECASTS.index(t["forecast"]) if t["forecast"] in _FORECASTS else -1
        if key not in best or rank > best[key][0]:
            best[key] = (rank, t)
    return [t for _, t in best.values()]


if __name__ == "__main__":
    from .tuner import Tuner
    with Tuner() as t:
        s = get_state(t)
    print(summarize(s))
