"""Fine-tune the agent's model on its own good turns (LoRA), and load the result into Ollama.

Needs an NVIDIA GPU and a separate install (not in requirements.txt; best in its own venv,
or WSL on Windows, where unsloth is better supported):
    pip install unsloth trl datasets
Run with the game and the agent stopped (training needs the whole GPU):
    py scripts/build_dataset.py
    py scripts/finetune_lora.py                          # qwen2.5:14b -> Ollama model civ5-qwen
    py scripts/finetune_lora.py --base unsloth/Qwen2.5-7B-Instruct-bnb-4bit --ollama-base qwen2.5:7b
Then pick "civ5-qwen" as the model in the GUI (or --model civ5-qwen) and compare it with the
base model over a few games before trusting it.

Steps: load the base model in 4 bit, add a LoRA adapter, train only on the model's own replies
(its tool calls; the state and tool results are context), merge and export to GGUF, then
`ollama create` with the base model's chat template so tool calls keep working.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=str(ROOT / "datasets" / "sft.jsonl"))
    ap.add_argument("--base", default="unsloth/Qwen2.5-14B-Instruct-bnb-4bit",
                    help="Hugging Face base model; must be the same model family as --ollama-base")
    ap.add_argument("--ollama-base", default="qwen2.5:14b", help="Ollama model whose chat template to reuse")
    ap.add_argument("--name", default="civ5-qwen", help="name of the new Ollama model")
    ap.add_argument("--max-seq", type=int, default=8192, help="longer examples are skipped (default 8192 tokens)")
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=16, help="LoRA rank (default 16)")
    ap.add_argument("--out", default=str(ROOT / "finetune"))
    args = ap.parse_args()

    try:
        from datasets import Dataset
        from trl import SFTConfig, SFTTrainer
        from unsloth import FastLanguageModel, is_bfloat16_supported
        from unsloth.chat_templates import train_on_responses_only
    except ImportError as e:
        sys.exit(f"missing training libraries ({e}). Install them with: pip install unsloth trl datasets")

    rows = [json.loads(line) for line in Path(args.data).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        sys.exit(f"no examples in {args.data}; run scripts/build_dataset.py first")

    model, tokenizer = FastLanguageModel.from_pretrained(model_name=args.base, max_seq_length=args.max_seq,
                                                         load_in_4bit=True)
    model = FastLanguageModel.get_peft_model(
        model, r=args.rank, lora_alpha=args.rank, lora_dropout=0, bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=0)

    # render each example with the model's own chat template (tools included), skipping ones too long
    texts, too_long = [], 0
    for row in rows:
        text = tokenizer.apply_chat_template(row["messages"], tools=row["tools"], tokenize=False)
        if len(tokenizer(text)["input_ids"]) > args.max_seq:
            too_long += 1
            continue
        texts.append({"text": text})
    print(f"{len(texts)} examples to train on ({too_long} skipped as longer than {args.max_seq} tokens)")
    if not texts:
        sys.exit("nothing left to train on; raise --max-seq if your GPU has room")

    out = Path(args.out)
    config = SFTConfig(
        dataset_text_field="text", max_seq_length=args.max_seq, per_device_train_batch_size=1,
        gradient_accumulation_steps=8, num_train_epochs=args.epochs, learning_rate=args.lr,
        warmup_ratio=0.05, lr_scheduler_type="cosine", optim="adamw_8bit", logging_steps=5,
        fp16=not is_bfloat16_supported(), bf16=is_bfloat16_supported(), output_dir=str(out / "checkpoints"),
        save_strategy="no", report_to="none", seed=0)
    dataset = Dataset.from_list(texts)
    try:
        trainer = SFTTrainer(model=model, tokenizer=tokenizer, train_dataset=dataset, args=config)
    except TypeError:  # newer TRL renamed the argument
        trainer = SFTTrainer(model=model, processing_class=tokenizer, train_dataset=dataset, args=config)
    # learn the model's replies only, not the game state or tool results it was shown
    trainer = train_on_responses_only(trainer, instruction_part="<|im_start|>user\n",
                                      response_part="<|im_start|>assistant\n")
    trainer.train()

    model.save_pretrained(str(out / "lora"))
    tokenizer.save_pretrained(str(out / "lora"))
    print("LoRA adapter saved to", out / "lora")

    gguf_dir = out / "gguf"
    model.save_pretrained_gguf(str(gguf_dir), tokenizer, quantization_method="q4_k_m")
    ggufs = sorted(gguf_dir.glob("*.gguf"), key=lambda p: ("q4_k_m" not in p.name.lower(), p.name))
    if not ggufs:
        sys.exit(f"no GGUF file was written to {gguf_dir}")

    # reuse the base model's Ollama template and parameters, with our weights
    base = subprocess.run(["ollama", "show", args.ollama_base, "--modelfile"], capture_output=True, text=True)
    if base.returncode != 0:
        sys.exit(f"couldn't read {args.ollama_base}'s Modelfile from Ollama: {base.stderr.strip()}")
    lines = [line for line in base.stdout.splitlines() if not line.startswith(("FROM ", "ADAPTER "))]
    modelfile = out / "Modelfile"
    modelfile.write_text(f"FROM {ggufs[0].resolve()}\n" + "\n".join(lines) + "\n", encoding="utf-8")
    made = subprocess.run(["ollama", "create", args.name, "-f", str(modelfile)])
    if made.returncode != 0:
        sys.exit("ollama create failed; the Modelfile is at " + str(modelfile))
    print(f"Done: Ollama model '{args.name}'. Try it with: py agent.py --model {args.name}")


if __name__ == "__main__":
    main()
