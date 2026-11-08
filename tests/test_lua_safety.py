"""Guard against game functions whose Lua bindings crash Civ V.

Many bindings use the SDK's generic BasicLuaMethod wrapper, which converts every
argument with lua_tointeger (CvLuaArgTemplates.h). That's fine for numbers, but a
unit, plot or city argument arrives as a null pointer and the game crashes. These
are the ones that take objects and have bitten us, or would.
"""
import re
import unittest
from pathlib import Path

LUA_DIR = Path(__file__).resolve().parent.parent / "civ5ai" / "lua"

# method -> why it is unsafe from Lua
UNSAFE = {
    "MovementCost": "Plot:MovementCost(unit, fromPlot) passes both objects through lua_tointeger",
    "GeneratePath": "Unit:GeneratePath is not implemented in this build (raises NYI)",
}


class LuaSafetyTest(unittest.TestCase):
    def test_no_unsafe_game_calls(self):
        for path in LUA_DIR.glob("*.lua"):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("--", 1)[0]  # comments may mention them
                for method, why in UNSAFE.items():
                    if re.search(r"[:.]" + method + r"\s*\(", code):
                        self.fail(f"{path.name}:{n} calls {method}: {why}")


if __name__ == "__main__":
    unittest.main()
