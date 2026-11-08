"""Proposing deals and friendship: item parsing, the Trade line in the state, and the screen flow."""
import unittest
from unittest import mock

from civ5ai import trade
from civ5ai.state import parse, summarize
from tests.test_state import SNAPSHOT, T


class ItemsTest(unittest.TestCase):
    def test_parse_item(self):
        self.assertEqual(trade.parse_item("RESOURCE_WINE"), ("RESOURCE_WINE", 1))
        self.assertEqual(trade.parse_item("iron x2"), ("RESOURCE_IRON", 2))
        self.assertEqual(trade.parse_item("GOLD 100"), ("GOLD", 100))
        self.assertEqual(trade.parse_item("gpt 3"), ("GOLD_PER_TURN", 3))
        self.assertEqual(trade.parse_item("open borders"), ("OPEN_BORDERS", None))
        self.assertEqual(trade.parse_item("ALLOW_EMBASSY"), ("EMBASSY", None))
        with self.assertRaises(ValueError):
            trade.parse_item("GOLD")

    def test_deal_spec_adds_both_sides_of_mutual_items(self):
        self.assertEqual(trade.deal_spec(["RESOURCE_WINE", "RESEARCH_AGREEMENT"], ["GOLD_PER_TURN 4"]),
                         "you|RESOURCE_WINE|1;you|RESEARCH_AGREEMENT|;them|RESEARCH_AGREEMENT|;them|GOLD_PER_TURN|4")
        with self.assertRaises(ValueError):
            trade.deal_spec([], [])


class TradeLineTest(unittest.TestCase):
    def test_state_shows_what_can_be_traded(self):
        recs = SNAPSHOT + [
            T.join(["DT", "2", "you", "RESOURCE_WINE", "2", "luxury"]),
            T.join(["DT", "2", "you", "EMBASSY", ""]),
            T.join(["DT", "2", "them", "RESOURCE_SILK", "1", "luxury"]),
            T.join(["DT", "2", "them", "RESOURCE_IRON", "4", "strategic"]),
            T.join(["DT", "2", "them", "GOLD_PER_TURN", "6"]),
        ]
        text = summarize(parse(recs))
        self.assertIn("Trade (propose_trade with player 2): you can give RESOURCE_WINE (luxury, you have 2: "
                      "spare copy), EMBASSY; they can give RESOURCE_SILK (luxury: new for you, +happiness), "
                      "RESOURCE_IRON (they have 4), GOLD_PER_TURN (up to 6).", text)
        self.assertIn("declare_friendship 2", text)


class FakeTuner:
    """Just enough of the game for the trade flow: screens open and close, deals get counted."""

    def __init__(self, accept=True):
        self.accept = accept
        self.visible = {"LeaderHeadRoot": False, "DiploTrade": False}
        self.deals = 0
        self.calls = []
        self.states = {"LeaderHeadRoot": 1, "DiploTrade": 2}

    def run(self, lua, state="InGame", timeout=5):
        self.calls.append((state, lua.strip()[:40]))
        if "ContextPtr:IsHidden" in lua:
            return ["true" if self.visible.get(state) else "false"]
        if "DoBeginDiploWithHuman" in lua:
            self.visible["LeaderHeadRoot"] = True
            return ["ok\tRome"]
        if lua == "OnTrade()":
            self.visible["DiploTrade"] = True
            return []
        if "_AI.build_deal" in lua:
            return ["ok: 2 items in the deal"]
        if lua == "OnPropose()":
            self.deals += 1 if self.accept else 0
            return []
        if "GetNumCurrentDeals" in lua:
            return [str(self.deals)]
        if "GetGameTurn" in lua:
            return ["12"]
        if "SPEECH" in lua:
            return ["SPEECH\tA fair offer." if self.accept else "SPEECH\tNo."]
        if lua in ("OnBack()", "OnReturn()"):
            self.visible["DiploTrade" if lua == "OnBack()" else "LeaderHeadRoot"] = False
        return []


@mock.patch("civ5ai.trade.time.sleep", lambda s: None)
@mock.patch("civ5ai.diplomacy.get_diplomacy", lambda t: None)
class ProposeFlowTest(unittest.TestCase):
    def test_accepted_deal_closes_the_screens(self):
        t = FakeTuner(accept=True)
        r = trade.Trader(t).propose(2, ["RESOURCE_WINE"], ["GOLD_PER_TURN 4"])
        self.assertTrue(r.startswith("ok: Rome accepted the deal"), r)
        self.assertIn("A fair offer.", r)
        self.assertFalse(any(t.visible.values()))

    def test_refusal_and_repeat_limit(self):
        t = FakeTuner(accept=False)
        trader = trade.Trader(t)
        r = trader.propose(2, ["RESOURCE_WINE"], [])
        self.assertTrue(r.startswith("error: Rome refused"), r)
        self.assertFalse(any(t.visible.values()))
        trader.propose(2, ["RESOURCE_WINE"], [])
        self.assertIn("already asked player 2", trader.propose(2, ["GOLD 10"], []))

    def test_bad_items_never_open_a_screen(self):
        t = FakeTuner()
        self.assertTrue(trade.Trader(t).propose(2, [], []).startswith("error: the deal is empty"))
        self.assertEqual(t.calls, [])


if __name__ == "__main__":
    unittest.main()
