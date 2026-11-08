"""Run the Civ V agent with a desktop window: py gui.py"""
import sys

try:
    from civ5ai.gui import main
except ModuleNotFoundError as e:
    if e.name and e.name.startswith("PyQt6"):
        sys.exit(f"The window needs PyQt6, which isn't installed for this Python ({sys.executable}).\n"
                 f"Install it with:  \"{sys.executable}\" -m pip install PyQt6\n"
                 "or run the console version instead:  py agent.py")
    raise

if __name__ == "__main__":
    main()
