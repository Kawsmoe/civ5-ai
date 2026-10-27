"""Every tool offered to the model must have code behind it."""
import re
import unittest
from pathlib import Path

from civ5ai.actions import Actions
from civ5ai.tools import TOOLS

HANDLED_BY_AGENT = {"update_plan", "respond_to_leader"}
LUA = (Path(__file__).resolve().parent.parent / "civ5ai" / "lua" / "actions.lua").read_text()


class ToolsTest(unittest.TestCase):
    def test_names_unique(self):
        names = [t["function"]["name"] for t in TOOLS]
        self.assertEqual(len(names), len(set(names)))

    def test_every_tool_is_implemented(self):
        lua_functions = set(re.findall(r"^function _AI\.(\w+)\(", LUA, re.M))
        for t in TOOLS:
            name = t["function"]["name"]
            if name in HANDLED_BY_AGENT:
                continue
            self.assertTrue(hasattr(Actions, name), f"Actions.{name} missing")
            self.assertIn(name, lua_functions, f"_AI.{name} missing from actions.lua")

    def test_required_params_exist(self):
        for t in TOOLS:
            params = t["function"]["parameters"]
            for r in params["required"]:
                self.assertIn(r, params["properties"])
            for p in params["properties"].values():
                self.assertNotIn("optional", p)  # tool() must strip the marker


if __name__ == "__main__":
    unittest.main()
