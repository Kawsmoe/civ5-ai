"""Running a game: connect, play turns, recover from hiccups, stop on request.

Shared by the console (cli.py) and the browser GUI (gui.py). Everything that
happens is reported through on_event(kind, text, **data); see Agent.event.
"""
import queue
import threading
import time
import traceback
import urllib.error

from .agent import DEFAULT_MODEL, LESSONS_EVERY, MODEL_OPTIONS, Agent, console_event
from .tuner import Tuner, TunerError

# Problems talking to the game or to Ollama: worth reconnecting and retrying the turn.
RECOVERABLE = (TunerError, OSError, urllib.error.URLError)
MAX_FAILURES_IN_A_ROW = 5


class Runner:
    def __init__(self, model=DEFAULT_MODEL, ctx=None, turns=500, lessons_every=LESSONS_EVERY, say="",
                 on_event=console_event):
        self.model, self.ctx, self.turns, self.lessons_every = model, ctx, turns, lessons_every
        self.on_event = on_event
        self.messages = queue.Queue()  # direction for the model, applied at the next turn
        if say:
            self.messages.put(say)
        self.stop_after_turn = threading.Event()
        self.stop_now = threading.Event()
        self.status = "idle"
        self.tuner = None
        self.agent = None

    def set_status(self, status, text=""):
        self.status = status
        self.on_event("status", text, status=status)

    def send(self, message):
        """Direction for the model; it sees it at the start of its next turn."""
        self.messages.put(message)
        self.on_event("info", f"message queued for the next turn: {message}")

    def request_stop(self, now=False):
        """Stop after the current turn, or (now=True) as soon as possible."""
        self.stop_after_turn.set()
        if now:
            self.stop_now.set()
            if self.tuner:  # breaks any wait on the game; the loop sees stop_now and exits
                try:
                    self.tuner.close()
                except OSError:
                    pass
        self.set_status("stopping", "stopping now..." if now else "stopping after this turn...")

    def connect(self, wait=600):
        """Connect and wait until a game is loaded (it may be at the menu or reloading)."""
        deadline, told = time.time() + wait, False
        while not self.stop_now.is_set():
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
                self.on_event("warn", f"waiting: {problem}. Load a game (and close FireTuner)...")
                told = True
            time.sleep(3)
        return None

    def run(self, between_turns=None):
        """Play until the turn limit, a stop request, or repeated failures.

        between_turns(runner) is called after each turn (the console uses it for its pause prompt).
        """
        if self.ctx:
            MODEL_OPTIONS["num_ctx"] = self.ctx
        self.set_status("connecting", "connecting to the game...")
        try:
            self.tuner = self.connect()
            if self.tuner is None:
                return
            self.agent = Agent(self.tuner, self.model, on_event=self.on_event)
            self.agent.lessons_every = self.lessons_every
            self.on_event("info", f"playing with {self.model}; logging to {self.agent.log_path}"
                          + (f"; using {len(self.agent.lessons)} lessons" if self.agent.lessons else ""))
            played, failures = 0, 0
            while played < self.turns and not self.stop_after_turn.is_set():
                parts = []
                while not self.messages.empty():
                    parts.append(self.messages.get())
                if parts:
                    self.agent.human_message = " ".join(parts)
                    self.agent.record(human_message=self.agent.human_message)
                self.set_status("playing")
                try:
                    self.agent.play_turn()
                    played, failures = played + 1, 0
                except RECOVERABLE as e:
                    if self.stop_now.is_set():
                        break
                    failures += 1
                    self.on_event("error", f"problem talking to the game or Ollama: {e!r}")
                    self.agent.record(error=repr(e), traceback=traceback.format_exc())
                    if failures >= MAX_FAILURES_IN_A_ROW:
                        self.on_event("error", "giving up after repeated failures; see the log for details")
                        break
                    self.on_event("info", "reconnecting and retrying the turn...")
                    self.tuner.close()
                    self.tuner = self.connect()
                    if self.tuner is None:
                        break
                    self.agent.attach(self.tuner)
                    continue
                if between_turns:
                    between_turns(self)
            if self.agent.lessons_every and not self.stop_now.is_set():
                self.set_status("reviewing", "reviewing the last turns for lessons...")
                self.agent.review_at_end()  # a clean stop: learn from the last few turns too
        except Exception as e:
            # a bug rather than a hiccup: keep the details in the log as well as on screen
            if self.agent:
                self.agent.record(error=repr(e), traceback=traceback.format_exc())
            self.on_event("error", f"stopped by an error: {e!r}", traceback=traceback.format_exc())
            raise
        finally:
            if self.tuner:
                try:
                    self.tuner.close()  # resets the connection so the game is free for the next run
                except OSError:
                    pass
            self.set_status("stopped", "stopped.")
