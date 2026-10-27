"""Command line entry point: py agent.py [--turns N] [--model NAME] [--say TEXT]"""
import argparse
import signal
import sys
import time
import traceback
import urllib.error

from .agent import DEFAULT_MODEL, Agent
from .tuner import Tuner, TunerError

# Problems talking to the game or to Ollama: worth reconnecting and retrying the turn.
RECOVERABLE = (TunerError, OSError, urllib.error.URLError)
MAX_FAILURES_IN_A_ROW = 5


def connect(wait=600):
    """Connect to the game and wait until a game is loaded (it may be at the menu or reloading)."""
    deadline = time.time() + wait
    told = False
    while True:
        try:
            tuner = Tuner()
            if "InGame" in tuner.states:
                return tuner
            tuner.close()
            problem = "the game is at a menu, not in a game"
        except RECOVERABLE as e:
            problem = f"can't reach the game ({e})"
        if time.time() > deadline:
            raise TunerError(f"gave up waiting: {problem}")
        if not told:
            print(f"  waiting: {problem}. Load a game (and close FireTuner)...")
            told = True
        time.sleep(3)


def main():
    # the Windows console is cp1252; don't crash on the model's non-ASCII text
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Let a local Ollama model play Civilization V.")
    ap.add_argument("--turns", type=int, default=500,
                    help="stop after this many turns (Ctrl+C then q also stops)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default {DEFAULT_MODEL})")
    ap.add_argument("--say", default="", help="direction for the model on its first turn")
    args = ap.parse_args()

    # Ctrl+C asks for a pause instead of killing the run mid-command (which
    # could leave the game half-way through an action); we pause between turns.
    pause = {"wanted": False}

    def on_ctrl_c(*_):
        pause["wanted"] = True
        print("\n  [pausing after this turn...]")

    signal.signal(signal.SIGINT, on_ctrl_c)

    tuner = connect()
    agent = Agent(tuner, args.model)
    agent.human_message = args.say
    print(f"Logging to {agent.log_path}. Press Ctrl+C any time to pause and give the model direction.")
    played, failures = 0, 0
    try:
        while played < args.turns:
            try:
                agent.play_turn()
                played, failures = played + 1, 0
            except RECOVERABLE as e:
                # e.g. a leader screen or reload dropped the connection: reconnect and redo the turn
                failures += 1
                print(f"\n  !! problem talking to the game or Ollama: {e!r}")
                agent.record(error=repr(e), traceback=traceback.format_exc())
                if failures >= MAX_FAILURES_IN_A_ROW:
                    print("  !! giving up after repeated failures; see the log for details")
                    break
                print("  reconnecting and retrying the turn...")
                tuner.close()
                tuner = connect()
                agent.attach(tuner)
                continue
            if pause["wanted"]:
                pause["wanted"] = False
                msg = input("\nPaused. Message for the model (Enter to just continue, q to quit): ").strip()
                if msg.lower() == "q":
                    break
                agent.human_message = msg
                agent.record(human_message=msg)
    except Exception as e:
        # a bug rather than a hiccup: keep the details in the log as well as the console
        agent.record(error=repr(e), traceback=traceback.format_exc())
        raise
    finally:
        tuner.close()


if __name__ == "__main__":
    main()
