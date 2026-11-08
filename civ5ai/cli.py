"""Console entry point: py agent.py [--turns N] [--model NAME] [--say TEXT] [--ctx N] [--lessons-every N]

For a window instead of the console: py gui.py
"""
import argparse
import signal
import sys
from pathlib import Path

if __package__ in (None, ""):
    # run as a plain file (e.g. VS Code's Run button on this file): make the package importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "civ5ai"

from .agent import DEFAULT_MODEL, LESSONS_EVERY, MODEL_OPTIONS
from .runner import Runner


def main():
    # the Windows console is cp1252; don't crash on the model's non-ASCII text
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Let a local Ollama model play Civilization V.")
    ap.add_argument("--turns", type=int, default=500,
                    help="stop after this many turns (Ctrl+C then q also stops)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default {DEFAULT_MODEL})")
    ap.add_argument("--say", default="", help="direction for the model on its first turn")
    ap.add_argument("--ctx", type=int, default=MODEL_OPTIONS["num_ctx"],
                    help=f"model context size in tokens (default {MODEL_OPTIONS['num_ctx']}); "
                         "lower it if the model doesn't fit on the GPU next to the game")
    ap.add_argument("--lessons-every", type=int, default=LESSONS_EVERY,
                    help=f"turns between reviews that update lessons.md (default {LESSONS_EVERY}; 0 = off)")
    args = ap.parse_args()

    runner = Runner(model=args.model, ctx=args.ctx, turns=args.turns, lessons_every=args.lessons_every,
                    say=args.say)

    # Ctrl+C asks for a pause instead of killing the run mid-command (which
    # could leave the game half-way through an action); we pause between turns.
    pause = {"wanted": False}

    def on_ctrl_c(*_):
        if pause["wanted"]:
            # second Ctrl+C: the turn may be stuck, so quit right away
            raise KeyboardInterrupt
        pause["wanted"] = True
        print("\n  [pausing after this turn... press Ctrl+C again to quit now]")

    def between_turns(r):
        if not pause["wanted"]:
            return
        pause["wanted"] = False
        msg = input("\nPaused. Message for the model (Enter to just continue, q to quit): ").strip()
        if msg.lower() == "q":
            r.stop_after_turn.set()
        elif msg:
            r.send(msg)

    signal.signal(signal.SIGINT, on_ctrl_c)
    print("Press Ctrl+C any time to pause and give the model direction.")
    try:
        runner.run(between_turns)
    except KeyboardInterrupt:
        print("\n  stopped.")


if __name__ == "__main__":
    main()
