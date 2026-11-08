"""Trade routes in the state: slots, active and incoming routes, risk, home cities, checklist, fallback."""
import unittest

from civ5ai.agent import Agent
from civ5ai.state import parse, summarize
from tests.test_state import SNAPSHOT, T

CARAVAN = [
    T.join(["U", "50001", "UNIT_CARAVAN", "19", "23", "1", "1", "100", "0", "false", "false"]),
    T.join(["TR", "50001", "20", "31", "Antium", "INTERNATIONAL", "6", "2", "0", "0", "2"]),
    T.join(["TR", "50001", "25", "60", "Geneva", "INTERNATIONAL", "4", "0", "0", "0", "0"]),
    T.join(["TRH", "50001", "30", "40", "Sao Paulo"]),
]
ROUTES = [
    T.join(["TRS", "1", "3"]),
    T.join(["TRA", "Rio de Janeiro", "Antium", "Rome", "land", "12", "5", "1", "0", "0"]),
    T.join(["TRA", "Rio de Janeiro", "Sao Paulo", "", "land", "1", "0", "0", "3", "0"]),
    T.join(["TRI", "Rome", "Antium", "Rio de Janeiro", "2", "1"]),
]


def build_options(city_id, *items):
    return [T.join(["B", str(city_id), "UNIT", t, str(n)]) for t, n in items]


class TradeStateTest(unittest.TestCase):
    def test_routes_slots_and_incoming(self):
        text = summarize(parse(SNAPSHOT + ROUTES + build_options(8192, ("UNIT_CARAVAN", 5))))
        # 3 available - 1 used = 2 free (no trade unit waiting)
        self.assertIn("Trade routes: 1 of 3 in use (2 free: build a Caravan", text)
        self.assertIn("  Rio de Janeiro -> Antium (Rome), land: +5 gold, +1 science, 12 turns left", text)
        self.assertIn("  Rome's route Antium -> your Rio de Janeiro: +2 gold, +1 science for you", text)
        self.assertIn("2 free trade route slot(s): city 8192 Rio de Janeiro can build UNIT_CARAVAN in 5 turns", text)
        self.assertIn("the trade route Rio de Janeiro -> Sao Paulo ends now", text)

    def test_waiting_caravan_fills_a_slot_and_shows_risk_and_homes(self):
        text = summarize(parse(SNAPSHOT + ROUTES + CARAVAN + build_options(8192, ("UNIT_CARAVAN", 5))))
        self.assertIn("1 of 3 in use (1 free", text)
        self.assertIn("Antium at (20,31) INTERNATIONAL: gold 6, science 2, food 0, production 0 - RISK: 2 hostile", text)
        self.assertNotIn("Geneva at (25,60) INTERNATIONAL: gold 4, science 0, food 0, production 0 - RISK", text)
        self.assertIn("could move its home city to reach other destinations (trade_home): Sao Paulo at (30,40)", text)
        self.assertIn("send UNIT_CARAVAN 50001 on a trade route (trade_route", text)

    def test_no_trade_section_before_trade_is_possible(self):
        text = summarize(parse(SNAPSHOT + [T.join(["TRS", "0", "0"])]))
        self.assertNotIn("Trade routes:", text)


class TradeFallbackTest(unittest.TestCase):
    def test_idle_caravan_takes_the_best_safe_route(self):
        calls = []

        class FakeActions:
            def trade_route(self, uid, x, y):
                calls.append((uid, x, y))
                return "ok: sent"

            def __getattr__(self, name):
                return lambda *a, **k: "ok"

        a = Agent.__new__(Agent)
        a.a, a.t = FakeActions(), None
        s = parse(SNAPSHOT + CARAVAN)
        s["cities"] = {}  # nothing else to decide
        for u in s["units"].values():
            if u["id"] != 50001:
                u["activity"] = 1  # only the caravan needs orders
        a.enough_workers = lambda s: True
        import civ5ai.agent as agent_mod
        orig = agent_mod.diplomacy.get_diplomacy
        agent_mod.diplomacy.get_diplomacy = lambda t: None
        try:
            done = a.fallback(s)
        finally:
            agent_mod.diplomacy.get_diplomacy = orig
        self.assertEqual(calls, [(50001, 25, 60)])  # Antium pays more but is risky
        self.assertIn("ok: sent", done)


if __name__ == "__main__":
    unittest.main()
