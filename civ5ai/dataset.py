"""Training data from the agent's own play, for fine-tuning the model (scripts/finetune_lora.py).

While playing, every turn's full exchange with the model (the state it was given,
its tool calls, the results) goes to logs/train/<run>.jsonl with the game's
numbers at the start of the turn. The system prompt is saved once per version
in logs/train/system-<hash>.txt rather than on every line.

build() turns those into supervised examples, keeping only good turns:
  - every tool call worked (no "error:" results) and the model never answered without a tool call
  - the turn was ended by the model itself
  - (unless min_gain is None) the score gap to rivals over the next `horizon` turns grew at
    least as much as min_gain, or, with min_gain="median", at least as much as that run's median
Examples are in the chat format with tool calls that Hugging Face chat templates
(and so unsloth/TRL) take: {"messages": [...], "tools": [...]}.
"""
import hashlib
import json
from pathlib import Path
from statistics import median


class TrainLog:
    def __init__(self, directory, run, system):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.sha = hashlib.sha1(system.encode("utf-8")).hexdigest()[:12]
        sys_file = self.dir / f"system-{self.sha}.txt"
        if not sys_file.exists():
            sys_file.write_text(system, encoding="utf-8")
        self.path = self.dir / f"{run}.jsonl"
        self.run = run

    def turn(self, turn, model, metrics, messages):
        """Save one turn's exchange (messages after the system prompt)."""
        clean = []
        for m in messages:
            m = {k: v for k, v in m.items() if k in ("role", "content", "tool_calls", "tool_name")}
            clean.append(m)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"run": self.run, "turn": turn, "model": model, "system": self.sha,
                                "metrics": metrics, "messages": clean}) + "\n")


# --- building a dataset -------------------------------------------------------------------

def load(directory):
    """{run: [turn records sorted by turn]} and {system sha: text}."""
    directory = Path(directory)
    runs, systems = {}, {}
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            runs.setdefault(rec["run"], []).append(rec)
    for path in directory.glob("system-*.txt"):
        systems[path.stem[len("system-"):]] = path.read_text(encoding="utf-8")
    for recs in runs.values():
        recs.sort(key=lambda r: r["turn"])
    return runs, systems


def quality(rec):
    """(errors, silent replies, ended by the model) for one turn."""
    errors = sum(1 for m in rec["messages"] if m["role"] == "tool" and str(m.get("content", "")).startswith("error"))
    silent = sum(1 for m in rec["messages"] if m["role"] == "assistant" and not m.get("tool_calls"))
    ended = any(m["role"] == "tool" and m.get("tool_name") == "end_turn" and str(m.get("content", "")).startswith("ok")
                for m in rec["messages"])
    return errors, silent, ended


def _gap(metrics):
    if not metrics or None in (metrics.get("score"), metrics.get("rival_avg_score")):
        return None
    return metrics["score"] - metrics["rival_avg_score"]


def gains(recs, horizon):
    """{turn: change in (score - rivals' average) from this turn to `horizon` turns later}."""
    out = {}
    for i, rec in enumerate(recs):
        later = next((r for r in recs[i + 1:] if r["turn"] >= rec["turn"] + horizon), None)
        g0, g1 = _gap(rec["metrics"]), _gap(later["metrics"]) if later else None
        if g0 is not None and g1 is not None:
            out[rec["turn"]] = g1 - g0
    return out


def to_example(rec, system, tools):
    """One turn as a chat example: system, state, then the model's calls and the results."""
    messages = [{"role": "system", "content": system}]
    for m in rec["messages"]:
        if m["role"] == "assistant":
            out = {"role": "assistant", "content": m.get("content") or ""}
            if m.get("tool_calls"):
                out["tool_calls"] = [{"type": "function", "function": {
                    "name": c["function"]["name"], "arguments": c["function"].get("arguments") or {}}}
                    for c in m["tool_calls"]]
            messages.append(out)
        elif m["role"] == "tool":
            messages.append({"role": "tool", "name": m.get("tool_name", ""), "content": m.get("content", "")})
        else:
            messages.append({"role": m["role"], "content": m.get("content", "")})
    return {"messages": messages, "tools": tools}


def build(directory, tools, horizon=10, min_gain="median"):
    """Return (examples, report): the good turns as training examples, and counts of why others were dropped."""
    runs, systems = load(directory)
    examples = []
    report = {"turns": 0, "kept": 0, "errors": 0, "silent": 0, "not_ended": 0, "no_system": 0,
              "no_outcome": 0, "low_gain": 0}
    for recs in runs.values():
        g = gains(recs, horizon)
        threshold = None
        if min_gain == "median":
            threshold = median(g.values()) if g else None
        elif min_gain is not None:
            threshold = float(min_gain)
        for rec in recs:
            report["turns"] += 1
            errors, silent, ended = quality(rec)
            reason = ("errors" if errors else "silent" if silent else "not_ended" if not ended
                      else "no_system" if rec.get("system") not in systems else None)
            if reason is None and min_gain is not None:
                if rec["turn"] not in g:
                    reason = "no_outcome"
                elif threshold is not None and g[rec["turn"]] < threshold:
                    reason = "low_gain"
            if reason:
                report[reason] += 1
                continue
            report["kept"] += 1
            examples.append(to_example(rec, systems[rec["system"]], tools))
    return examples, report
