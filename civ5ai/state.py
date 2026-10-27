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
             "new_city_sites": [], "threats": []}
    for line in lines:
        tag, *f = line.split("\t")
        if tag == "P":
            keys = ["turn", "civ", "gold", "gold_rate", "science", "culture",
                    "faith", "happiness", "blocking", "research", "research_turns"]
            state.update({k: (v if k in ("civ", "blocking", "research") else _num(v))
                          for k, v in zip(keys, f)})
        elif tag == "T":
            state["techs"].append({"type": f[0], "turns": _num(f[1])})
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
                "routes": [], "steps": [], "builds": [], "work_targets": []}
        elif tag == "S":
            state["units"][int(f[0])]["sites"].append(
                {"x": int(f[1]), "y": int(f[2]), "value": int(f[3]), "dist": int(f[4]),
                 "info": f[5] if len(f) > 5 else ""})
        elif tag == "CT":
            state["cities"][int(f[0])].update(
                {"land": f[1], "river_tiles": _num(f[2]), "coastal": f[3] == "true"})
        elif tag == "CR":
            state["cities"][int(f[0])]["resources"].append(
                {"type": f[1], "class": f[2], "x": int(f[3]), "y": int(f[4]), "improved": f[5] == "true"})
        elif tag == "NS":
            state["new_city_sites"].append(
                {"x": int(f[0]), "y": int(f[1]), "value": int(f[2]), "dist": int(f[3]),
                 "near": f[4], "info": f[5]})
        elif tag == "E":
            state["enemies"].append({"x": int(f[0]), "y": int(f[1]), "owner": f[2],
                                     "type": f[3], "hp": _num(f[4])})
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
                                              "destination": f[6] if len(f) > 6 else ""})
        elif tag == "UP":
            state["units"][int(f[0])]["promotions"].append(f[1])
        elif tag == "UM":
            state["units"][int(f[0])]["missions"].append(f[1])
        elif tag == "RT":
            state["ranged_targets"].append({"kind": f[0], "id": int(f[1]),
                                            "x": int(f[2]), "y": int(f[3]),
                                            "forecast": f[4] if len(f) > 4 else ""})
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
                 "gold": _num(f[5]), "science": _num(f[6]), "food": _num(f[7]), "production": _num(f[8])})
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


def get_state(tuner):
    return parse(tuner.run(LUA, timeout=15))


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
    out.append("Techs available: " + ", ".join(f"{t['type']} ({t['turns']}t)" for t in techs))

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
    majors = [c for c in s["civs"] if c["kind"] == "MAJOR"]
    minors = [c for c in s["civs"] if c["kind"] == "MINOR"]
    if majors:
        out.append("Civs you know: " + "; ".join(
            f"player {c['id']} {c['name']} (score {c['score']}"
            + (", AT WAR" if c["at_war"] else "") + ")" for c in majors))
    if minors:
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
        out.append(f"    hp {c['hp']}/{c['max_hp']}, defense {c['defense']}, "
                   f"religion {c['majority_religion'] or 'none'}")
        if c["land"]:
            water = ", coastal" if c["coastal"] else ""
            out.append(f"    land around it: {c['land']}; {c['river_tiles']} river tiles{water}")
        if c["resources"]:
            out.append("    resources nearby: " + "; ".join(
                f"{r['type']} ({r['class']}) at ({r['x']},{r['y']})"
                + ("" if r["improved"] else " UNIMPROVED") for r in c["resources"]))
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
        elif u["moves"] == 0:
            flag = " (no moves left this turn)"
        elif u["automated"]:
            flag = " (automated)"
        else:
            flag = ""
        strength = ""
        if u["strength"]:
            strength = f" strength {u['strength']}" + (f" ranged {u['ranged']}" if u["ranged"] else "")
        out.append(f"  unit {u['id']} {u['type']} at ({u['x']},{u['y']}) "
                   f"moves {u['moves']}/{u['max_moves']} hp {u['hp']}{strength}{flag}")
        if u["promotions"]:
            out.append("    PROMOTION READY: " + ", ".join(u["promotions"]))
        if u["missions"]:
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
                f"food {r['food']}, production {r['production']}" for r in u["routes"]))
        if u["sites"]:
            best = u["sites"][0]["value"]
            out.append("    best city sites:")
            out.extend(f"      ({t['x']},{t['y']}) score {round(100 * t['value'] / best)}, "
                       f"{t['dist']} tiles away [{t['info']}]" for t in u["sites"])

    if s["cities"] and not any(u["type"] == "UNIT_SETTLER" for u in s["units"].values()):
        # spell this out: small models keep hunting for the settler they already used
        where = [f"{c['name']} ({b['turns']}t)" for c in s["cities"].values()
                 for b in c["can_build"] if b["type"] == "UNIT_SETTLER"]
        out.append("  You have NO Settler now (it was used up founding a city). "
                   + ("A new UNIT_SETTLER can be built in: " + ", ".join(where) if where
                      else "Settlers can't be built yet (cities need to grow first)."))

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
            out.append(f"  {e['owner']} {e['type']} at ({e['x']},{e['y']}) hp {e['hp']}")
        for t in attack_options(s):
            odds = f", forecast: {t['forecast']}" if t["forecast"] else ""
            where = f"({t['x']},{t['y']})"
            if t["kind"] == "CITY":
                out.append(f"  city {t['id']} can shoot {where} now (city_attack)")
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
        if needs_orders(u):
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
    if chances:
        out.append("OPPORTUNITIES: " + "; ".join(chances))
    out.append("Then call end_turn.")
    return "\n".join(out)


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
