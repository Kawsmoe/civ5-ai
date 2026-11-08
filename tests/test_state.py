"""Parsing and summarizing a game-state snapshot, without the game."""
import unittest

from civ5ai.state import needs_orders, parse, summarize

T = "\t"

# A small but complete snapshot, in the record format lua/state.lua prints.
SNAPSHOT = [
    T.join(["P", "12", "Brazil", "40", "3", "6", "2", "1", "9", "UNITS", "TECH_POTTERY", "4"]),
    T.join(["CIV", "Pedro II", "Carnival", "Tourism output is +100% during their Golden Ages. [NEWLINE]Earn Great Artists faster."]),
    T.join(["CIVU", "UNIT", "UNIT_BRAZILIAN_PRACINHA", "UNIT_INFANTRY", "Earns points toward a Golden Age."]),
    T.join(["CIVU", "IMPROVEMENT", "IMPROVEMENT_BRAZILWOOD_CAMP", "", "+2 [ICON_GOLD] Gold in jungle."]),
    T.join(["T", "TECH_ARCHERY", "7", "units ARCHER"]),
    T.join(["TP", "TECH_CALENDAR", "plantation for WINE", "TECH_POTTERY (3t) -> TECH_CALENDAR (8t), 11 turns"]),
    T.join(["T", "TECH_MINING", "5"]),
    T.join(["L", "8", "25", "0", "false"]),
    T.join(["A", "POLICY_BRANCH_TRADITION"]),
    T.join(["R", "3", "1", "false", "", "10", "4", "200", "0"]),
    T.join(["C", "8192", "Rio de Janeiro", "19", "23", "3", "2", "5", "Monument", "6", "8"]),
    T.join(["CX", "8192", "200", "200", "9", ""]),
    T.join(["CT", "8192", "grassland 9, plains hills 4, coast 6", "5", "true"]),
    T.join(["CR", "8192", "WINE", "luxury", "20", "24", "false", "BUILD_PLANTATION", "TECH_CALENDAR"]),
    T.join(["CR", "8192", "WHEAT", "bonus", "18", "23", "false", "BUILD_FARM", ""]),
    T.join(["NS", "24", "20", "5200", "5", "Rio de Janeiro", "fresh water, hills; IRON, 1 bonus"]),
    T.join(["B", "8192", "UNIT", "UNIT_SETTLER", "15"]),
    T.join(["B", "8192", "UNIT", "UNIT_WARRIOR", "8"]),
    T.join(["BUY", "8192", "GOLD", "UNIT_WARRIOR", "120"]),
    T.join(["U", "16385", "UNIT_WARRIOR", "13", "23", "2", "2", "100", "0", "false", "true"]),
    T.join(["UX", "16385", "8", "0", "0", "10", "false"]),
    T.join(["NB", "16385", "12", "23", "grassland"]),
    T.join(["NB", "16385", "14", "22", "plains hills forest"]),
    T.join(["U", "24576", "UNIT_SCOUT", "15", "27", "0", "2", "100", "0", "true", "true"]),
    T.join(["UX", "24576", "5", "0", "0", "10", "false", "70,39"]),
    T.join(["POI", "RUINS", "16", "20", "16385", "3"]),
    T.join(["E", "17", "21", "Barbarians", "UNIT_BARBARIAN_WARRIOR", "100", "8", "0"]),
    T.join(["RT", "MELEE", "16385", "17", "21", "major victory", "40", "15"]),
    T.join(["RT", "MELEE", "16385", "17", "21", "small defeat", "20", "45"]),  # second unit on the tile
    T.join(["TH", "8192", "Rio de Janeiro", "17", "21", "UNIT_BARBARIAN_WARRIOR", "2"]),
    T.join(["K", "2", "MAJOR", "Rome", "false", "true", "120", ""]),
    T.join(["ME", "50", "12", "2", "0", "3"]),
    T.join(["CV", "2", "Rome", "120", "4", "15", "90", "classical", "16", "3", "0", "5", "",
            "GUARDED", "false", "false", "false", "7", "Antium", "Rio de Janeiro"]),
    T.join(["CO", "2", "[COLOR_NEGATIVE_TEXT]You have settled too near them[ENDCOLOR]"]),
    T.join(["CW", "2", "PYRAMID"]),
    T.join(["ND", "16385", "1"]),
    T.join(["K", "23", "MINOR", "Geneva", "false", "true", "", "35"]),
    T.join(["CS", "23", "cultured", "FRIENDS", "35", "Rome", "false", "true", "15", "250"]),
    T.join(["HP", "2", "21", "19", "12", "4", "0", "0", "0", "5", "0", "6", "13", "0", "0", "0"]),
    T.join(["LX", "WINE", "2", "2"]),
    T.join(["VC", "0", "you", "12", "0", "0", "0", "7", "1", "0", ""]),
    T.join(["VC", "2", "Rome", "16", "0", "0", "1", "7", "1", "2", ""]),
    T.join(["VT", "8"]),
]


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.s = parse(SNAPSHOT)

    def test_player(self):
        s = self.s
        self.assertEqual(s["turn"], 12)
        self.assertEqual(s["civ"], "Brazil")
        self.assertEqual(s["blocking"], "UNITS")
        self.assertEqual(s["research"], "TECH_POTTERY")
        self.assertEqual(s["research_turns"], 4)
        self.assertEqual(s["policies"], ["POLICY_BRANCH_TRADITION"])
        self.assertFalse(s["policy_due"])
        self.assertFalse(s["has_pantheon"])

    def test_city(self):
        c = self.s["cities"][8192]
        self.assertEqual(c["name"], "Rio de Janeiro")
        self.assertEqual(c["producing"], "Monument")
        self.assertEqual(c["defense"], 9)
        self.assertEqual([b["type"] for b in c["can_build"]], ["UNIT_SETTLER", "UNIT_WARRIOR"])
        self.assertEqual(c["can_buy"], [{"currency": "GOLD", "type": "UNIT_WARRIOR", "cost": 120}])

    def test_units(self):
        warrior, scout = self.s["units"][16385], self.s["units"][24576]
        self.assertEqual(warrior["strength"], 8)
        self.assertEqual(len(warrior["steps"]), 2)
        self.assertTrue(needs_orders(warrior))
        self.assertFalse(needs_orders(scout))  # automated, and out of moves

    def test_map_and_civs(self):
        self.assertEqual(self.s["pois"][0]["kind"], "RUINS")
        self.assertEqual(self.s["enemies"][0]["owner"], "Barbarians")
        self.assertEqual(self.s["civs"][0]["name"], "Rome")


class SummarizeTest(unittest.TestCase):
    def setUp(self):
        self.text = summarize(parse(SNAPSHOT))

    def test_civilization_strengths(self):
        for expected in ["Your civilization (led by Pedro II) - pick the victory that uses these strengths:",
                         "Ability Carnival: Tourism output is +100% during their Golden Ages. Earn Great Artists faster.",
                         "Unique unit UNIT_BRAZILIAN_PRACINHA, replaces UNIT_INFANTRY: Earns points toward a Golden Age.",
                         "Unique improvement IMPROVEMENT_BRAZILWOOD_CAMP: +2 Gold in jungle."]:
            self.assertIn(expected, self.text)

    def test_sections(self):
        for expected in ["Turn 12 - you are Brazil.", "Researching TECH_POTTERY (4 turns left).", "  TECH_ARCHERY (7t): units ARCHER",
                         "TECH_CALENDAR - plantation for WINE: TECH_POTTERY (3t) -> TECH_CALENDAR (8t), 11 turns",
                         "city 8192 Rio de Janeiro", "can buy now with gold: UNIT_WARRIOR (120)",
                         "unit 16385 UNIT_WARRIOR", "NEEDS ORDERS", "can step to: (12,23) grassland",
                         "ANCIENT RUINS", "Barbarians UNIT_BARBARIAN_WARRIOR at (17,21) hp 100, strength 8",
                         "player 2 Rome: score 120, 4 cities (pop 15), military 1.8x yours, classical era, 4 techs ahead of you",
                         "Attitude toward you: GUARDED. Nearest city Antium is 7 tiles from your Rio de Janeiro.",
                         "Why: You have settled too near them", "Wonders: PYRAMID",
                         "1 enemy unit(s) within 2 tiles",
                         "player 23 Geneva: cultured - friends get culture, you: FRIENDS, influence 35, ally: Rome, "
                         "you could pledge protection, a small gift (250 gold) gives +15 influence",
                         "Happiness +2: 21 happiness (luxuries 12, buildings 4, city states 5) minus 19 unhappiness "
                         "(cities 6, population 13).",
                         "Close to unhappiness",
                         "WINE x2 (1 spare to trade)",
                         "Science (techs, then the spaceship): you 12 techs, Apollo no, 0 spaceship parts; "
                         "best rival Rome 16 techs",
                         "Domination (hold all 8 original capitals): you 1 capitals",
                         "Diplomatic (World Leader vote): you 0 city-state allies; best rival Rome 2 city-state allies",
                         "deals ~20 damage (enemy hp 100 -> 80), takes ~45 (your hp 100 -> 55)",
                         "land around it: grassland 9, plains hills 4, coast 6; 5 river tiles, coastal",
                         "WINE (luxury) at (20,24) UNIMPROVED - needs BUILD_PLANTATION, which needs TECH_CALENDAR",
                         "WHEAT (bonus) at (18,23) UNIMPROVED - BUILD_FARM possible now",
                         "(24,20) score 100, 5 tiles from Rio de Janeiro [fresh water, hills; IRON, 1 bonus]",
                         "unit 16385 is next to (17,21) and can attack it now (attack, forecast: small defeat;",
                         "THREATS: UNIT_BARBARIAN_WARRIOR at (17,21), 2 tiles from Rio de Janeiro",
                         "on its way to (70,39) from an earlier order"]:
            self.assertIn(expected, self.text)

    def test_no_settler_hint(self):
        self.assertIn("You have NO Settler now", self.text)
        self.assertIn("Rio de Janeiro (15t)", self.text)

    def test_todo(self):
        todo = self.text.split("TO DO THIS TURN (required): ")[1].splitlines()[0]
        self.assertIn("give orders to unit 16385", todo)
        self.assertIn("ruins at (16,20)", todo)
        self.assertNotIn("24576", todo)

    def test_minimal_snapshot(self):
        # turn 0: no cities, nothing optional present
        s = parse([line for line in SNAPSHOT if line.split(T)[0] in ("P", "L", "R")])
        self.assertIn("Cities: none yet.", summarize(s))




class SettleSitesTest(unittest.TestCase):
    def test_timing_risk_and_reservations(self):
        recs = [T.join(r) for r in [
            ["P", "0", "Germany", "0", "0", "0", "0", "0", "9", "UNITS", "", ""],
            ["L", "0", "10", "0", "false"], ["R", "0", "0", "false", "", "10", "4", "200", "0"],
            ["U", "8192", "UNIT_SETTLER", "15", "43", "2", "2", "100", "0", "false", "false"],
            ["S", "8192", "17", "42", "5400", "2", "coast; WINE", "2", "", "", ""],
            ["S", "8192", "15", "43", "5200", "0", "fresh water", "0", "", "", "barbarian camp 3 tiles away"],
            ["U", "9000", "UNIT_SETTLER", "10", "40", "0", "2", "100", "8", "false", "false"],
            ["UX", "9000", "0", "0", "0", "10", "false", "17,42", "MISSION"]]]
        text = summarize(parse(recs))
        self.assertIn("(17,42) score 100, city in about 2 turns [coast; WINE]. TAKEN: Settler 9000", text)
        self.assertIn("(15,43) score 96, can found this turn [fresh water]. RISK: barbarian camp", text)
        self.assertIn("FIRST CITY", text)




class GreatPeopleTest(unittest.TestCase):
    def test_options_and_todo(self):
        recs = [T.join(r) for r in [
            ["P", "40", "Germany", "100", "5", "20", "8", "3", "6", "UNITS", "TECH_PHILOSOPHY", "4"],
            ["L", "0", "10", "0", "false"], ["R", "0", "0", "false", "", "10", "4", "200", "0"],
            ["C", "8192", "Berlin", "19", "66", "6", "2", "10", "Library", "3", "8"],
            ["U", "40960", "UNIT_SCIENTIST", "19", "66", "2", "2", "100", "0", "false", "false"],
            ["UM", "40960", "MISSION_DISCOVER"], ["GPU", "40960", "UNIT_SCIENTIST"],
            ["GPB", "40960", "BUILD_ACADEMY", "20", "67", "1"],
            ["U", "41000", "UNIT_MERCHANT", "18", "60", "2", "2", "100", "0", "false", "false"],
            ["GPU", "41000", "UNIT_MERCHANT"], ["GPT", "41000", "Geneva", "25", "60", "7"]]]
        text = summarize(parse(recs))
        for expected in ["GREAT PERSON - choose how to use it", "MISSION_DISCOVER: a burst of science",
                         "or build an Academy", "nearest tile for BUILD_ACADEMY: (20,67), 1 tiles away",
                         "possible right where it stands (unit_mission): MISSION_DISCOVER",
                         "nearest city-state for a trade mission: Geneva at (25,60), 7 tiles away",
                         "decide how to use Great Person 40960 UNIT_SCIENTIST"]:
            self.assertIn(expected, text)


class HealingTest(unittest.TestCase):
    def unit_lines(self, hp, where, promos=()):
        recs = []
        for r in SNAPSHOT:
            if r.startswith("U\t16385\t"):
                recs.append(T.join(["U", "16385", "UNIT_WARRIOR", "13", "23", "2", "2", str(hp), "0", "false", "true"]))
                recs.append(T.join(["UH", "16385", where, "Rio de Janeiro", "3"]))
                recs.extend(T.join(["UP", "16385", p]) for p in promos)
            else:
                recs.append(r)
        text = summarize(parse(recs))
        return [l for l in text.splitlines() if "16385" in l or "HURT" in l or "PROMOTION READY" in l]

    def test_hurt_unit_gets_heal_advice_without_enemies_near(self):
        lines = "\n".join(self.unit_lines(40, "NEUTRAL"))
        self.assertIn("HURT (40 hp): heals ~10/turn outside your land", lines)
        self.assertIn("MISSION_HEAL", lines)
        self.assertIn("your city Rio de Janeiro is 3 tiles away (25/turn there)", lines)

    def test_lightly_hurt_or_in_city_says_less(self):
        self.assertNotIn("HURT", "\n".join(self.unit_lines(80, "NEUTRAL")))
        lines = "\n".join(self.unit_lines(30, "CITY"))
        self.assertIn("heals ~25/turn in your city", lines)
        self.assertNotIn("tiles away", lines)

    def test_insta_heal_promotion_is_explained(self):
        lines = "\n".join(self.unit_lines(30, "ENEMY", promos=["PROMOTION_INSTA_HEAL", "PROMOTION_SHOCK_1"]))
        self.assertIn("PROMOTION_INSTA_HEAL (heals 50 hp at once instead of a lasting bonus)", lines)
        self.assertIn("or promote PROMOTION_INSTA_HEAL to heal 50 hp now", lines)


if __name__ == "__main__":
    unittest.main()
