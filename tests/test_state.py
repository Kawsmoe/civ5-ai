"""Parsing and summarizing a game-state snapshot, without the game."""
import unittest

from civ5ai.state import needs_orders, parse, summarize

T = "\t"

# A small but complete snapshot, in the record format lua/state.lua prints.
SNAPSHOT = [
    T.join(["P", "12", "Brazil", "40", "3", "6", "2", "1", "9", "UNITS", "TECH_POTTERY", "4"]),
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


if __name__ == "__main__":
    unittest.main()
