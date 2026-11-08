"""Build a fine-tuning dataset from the agent's own good turns.

Reads logs/train/ (written while the agent plays) and writes datasets/sft.jsonl:
one chat example per kept turn, with the tool definitions, ready for
scripts/finetune_lora.py. Prints how many turns were kept and why the rest weren't.

    py scripts/build_dataset.py                    # error-free turns that beat the run's median score trend
    py scripts/build_dataset.py --min-gain 0       # ...whose score gap to rivals didn't shrink
    py scripts/build_dataset.py --min-gain none    # every error-free turn (more data, less selective)
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from civ5ai.agent import TRAIN_DIR  # noqa: E402
from civ5ai.dataset import build  # noqa: E402
from civ5ai.tools import TOOLS  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "datasets" / "sft.jsonl"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--horizon", type=int, default=10, help="turns ahead to judge a turn's outcome (default 10)")
    ap.add_argument("--min-gain", default="median",
                    help="keep turns whose score gap to rivals changed at least this much over the horizon: "
                         "a number, 'median' (per run, the default) or 'none' (don't judge outcomes)")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    min_gain = None if args.min_gain.lower() == "none" else args.min_gain
    if min_gain not in (None, "median"):
        min_gain = float(min_gain)

    examples, report = build(TRAIN_DIR, TOOLS, horizon=args.horizon, min_gain=min_gain)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")
    print(f"{report['turns']} turns read from {TRAIN_DIR}; kept {report['kept']} -> {out}")
    for reason, label in [("errors", "had failed tool calls"), ("silent", "had replies without tool calls"),
                          ("not_ended", "weren't ended by the model"), ("no_system", "system prompt file missing"),
                          ("no_outcome", f"too close to the end of a run to judge ({args.horizon} turns)"),
                          ("low_gain", "score trend below the threshold")]:
        if report[reason]:
            print(f"  dropped {report[reason]:5d}: {label}")
    if report["kept"] < 500:
        print("Fewer than ~500 examples: fine-tuning on this little is likely to overfit. Play more games first.")


if __name__ == "__main__":
    main()
