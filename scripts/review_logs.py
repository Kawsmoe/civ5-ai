"""Seed or refresh lessons.md from past game logs, without the game running.

Collects failed actions, lost units and idle replies from logs/*.jsonl and
runs the same review the agent does every few turns.

    py scripts/review_logs.py                 # the 5 most recent logs, default model
    py scripts/review_logs.py --logs 20 --model gpt-oss:20b
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from civ5ai import lessons  # noqa: E402
from civ5ai.agent import DEFAULT_MODEL, LOG_DIR, chat, extract_text_tool_calls  # noqa: E402


def summarize_logs(paths):
    period = lessons.Period.__new__(lessons.Period)
    period.failures, period.examples, period.silent_replies, period.lost = lessons.Counter(), {}, 0, []
    turns, first_lines, last_lines, plan = [], None, None, ""
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if "state" in row:
                turns.append(int(row["turn"]))
                head = row["state"].splitlines()[:2]
                first_lines = first_lines or head
                last_lines = head
                for m in re.finditer(r"LOST since last turn[^:]*: (.+)", row["state"]):
                    period.lost.extend(x.strip() for x in m.group(1).split(";") if "SETTLER" not in x)
                m = re.search(r"Your plan so far[^:]*: \(written turn \d+\) (.+)", row["state"])
                plan = m.group(1) if m else plan
            elif row.get("tool") and str(row.get("result", "")).startswith("error"):
                period.failure(row["tool"], row["result"])
    return period, turns, first_lines or [], last_lines or [], plan


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--logs", type=int, default=5, help="how many recent logs to read (default 5)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    paths = sorted(LOG_DIR.glob("game-*.jsonl"))[-args.logs:]
    if not paths:
        sys.exit("no logs found in " + str(LOG_DIR))
    period, turns, first, last, plan = summarize_logs(paths)
    current = lessons.load()
    prompt = "\n".join([
        f"These are {len(paths)} recent games ({len(turns)} turns played in total).",
        "Start of the earliest game:", *("  " + l for l in first),
        "End of the latest game:", *("  " + l for l in last),
        "Units lost: " + (", ".join(period.lost[:15]) or "none"),
        # counts only: the error texts are interface noise that drowns out strategy
        "Failed tool calls (interface mistakes, mostly fixed since): "
        + ", ".join(f"{tool} x{n}" for tool, n in period.failures.most_common(6)),
        f"Your last plan: {plan or 'none'}",
        "Current lessons:" if current else "Current lessons: none yet.",
        *(f"  {i}. {x}" for i, x in enumerate(current, 1)),
        f"\nUpdate the lessons (at most {lessons.MAX_LESSONS}) and call save_lessons with the full list.",
    ])
    print(prompt, "\n\nAsking", args.model, "...")
    reply = chat(args.model, [{"role": "system", "content": lessons.REVIEW_SYSTEM},
                              {"role": "user", "content": prompt}], tools=[lessons.SAVE_TOOL])
    calls = reply.get("tool_calls") or extract_text_tool_calls(reply.get("content") or "", tools=[lessons.SAVE_TOOL])
    new = next((c["function"]["arguments"].get("lessons") for c in calls
                if c["function"]["name"] == "save_lessons"), None)
    if not new:
        sys.exit("the model didn't return lessons:\n" + (reply.get("content") or ""))
    saved = lessons.save(new, f"from {len(paths)} logs")
    print("\nSaved to", lessons.LESSONS_FILE)
    print("\n".join(f"- {x}" for x in saved))


if __name__ == "__main__":
    main()
