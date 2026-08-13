"""
LoRA fine-tuning script for NEXUS trading agent.
Uses unsloth for fast, memory-efficient training.

Usage:
    cd server
    pip install unsloth
    python finetune.py                          # default: Qwen 2.5 7B, 1 epoch
    python finetune.py --model 8b --epochs 3    # bigger model, more epochs
    python finetune.py --base-model "meta-llama/Llama-3.1-8B" --epochs 2

Output:
    output/merged_model/     — full merged model (HuggingFace format)
    output/lora_adapter/     — just the LoRA weights (small, shareable)
    output/model.gguf        — quantized model for LM Studio
"""

import os
import json
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Fine-tune a trading agent model with LoRA")
    parser.add_argument("--data", type=str, default="training_data.jsonl", help="Training data file")
    parser.add_argument("--base-model", type=str, default="unsloth/Qwen2.5-7B-Instruct",
                        help="Base model from HuggingFace (default: Qwen 2.5 7B)")
    parser.add_argument("--model", type=str, choices=["7b", "8b", "14b"], default=None,
                        help="Quick model size selector (overrides --base-model)")
    parser.add_argument("--epochs", type=int, default=1, help="Number of training epochs")
    parser.add_argument("--lr", type=float, default=2e-4, help="Learning rate")
    parser.add_argument("--lora-rank", type=int, default=64, help="LoRA rank (higher = more capacity, more VRAM)")
    parser.add_argument("--max-seq-len", type=int, default=2048, help="Max sequence length")
    parser.add_argument("--batch-size", type=int, default=2, help="Per-device batch size")
    parser.add_argument("--output-dir", type=str, default="output", help="Output directory")
    parser.add_argument("--skip-gguf", action="store_true", help="Skip GGUF export (faster)")
    args = parser.parse_args()

    # Quick model selector
    model_map = {
        "7b": "unsloth/Qwen2.5-7B-Instruct",
        "8b": "unsloth/Llama-3.1-8B-Instruct",
        "14b": "unsloth/Qwen2.5-14B-Instruct",
    }
    if args.model:
        args.base_model = model_map[args.model]

    # Validate data
    data_path = Path(args.data)
    if not data_path.exists():
        print(f"Error: Training data not found: {args.data}")
        print("Generate it first: python training_data.py --period 2y")
        return

    # Count examples
    with open(data_path) as f:
        num_examples = sum(1 for _ in f)
    print(f"Training data: {num_examples} examples from {args.data}")
    print(f"Base model: {args.base_model}")
    print(f"LoRA rank: {args.lora_rank}")
    print(f"Epochs: {args.epochs}, LR: {args.lr}")
    print(f"Output: {args.output_dir}/")
    print()

    os.makedirs(args.output_dir, exist_ok=True)

    # ── Step 1: Load model with unsloth ──
    print("[1/5] Loading model with unsloth...")
    from unsloth import FastLanguageModel
    import torch

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base_model,
        max_seq_length=args.max_seq_len,
        dtype=None,  # auto-detect
        load_in_4bit=True,  # saves VRAM
    )

    # ── Step 2: Apply LoRA adapters ──
    print("[2/5] Applying LoRA adapters...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.lora_rank,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_alpha=args.lora_rank * 2,
        lora_dropout=0.05,
        bias="none",
        use_gradient_checkpointing="unsloth",  # saves VRAM
        random_state=42,
    )

    model.print_trainable_parameters()

    # ── Step 3: Prepare dataset ──
    print("[3/5] Preparing dataset...")

    def format_example(example):
        """Convert our JSONL format to the chat template the model expects."""
        messages = example["messages"]
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        return {"text": text}

    from datasets import load_dataset

    dataset = load_dataset("json", data_files=str(data_path), split="train")
    dataset = dataset.map(format_example)

    # Train/test split
    split = dataset.train_test_split(test_size=0.05, seed=42)
    train_dataset = split["train"]
    eval_dataset = split["test"]

    print(f"  Train: {len(train_dataset)} examples")
    print(f"  Eval:  {len(eval_dataset)} examples")

    # ── Step 4: Train ──
    print("[4/5] Training...")
    from trl import SFTTrainer
    from transformers import TrainingArguments

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        dataset_text_field="text",
        max_seq_length=args.max_seq_len,
        packing=False,
        args=TrainingArguments(
            output_dir=args.output_dir + "/checkpoints",
            per_device_train_batch_size=args.batch_size,
            gradient_accumulation_steps=4,
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            warmup_steps=10,
            logging_steps=25,
            eval_strategy="steps",
            eval_steps=100,
            save_strategy="steps",
            save_steps=200,
            save_total_limit=2,
            optim="adamw_8bit",
            seed=42,
            report_to="none",
            fp16=not torch.cuda.is_bf16_supported(),
            bf16=torch.cuda.is_bf16_supported(),
        ),
    )

    stats = trainer.train()
    print(f"\n  Training complete!")
    print(f"  Loss: {stats.training_loss:.4f}")
    print(f"  Steps: {stats.global_step}")

    # ── Step 5: Export ──
    print("[5/5] Exporting model...")

    # Save LoRA adapter (small, ~100MB)
    adapter_path = os.path.join(args.output_dir, "lora_adapter")
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    print(f"  LoRA adapter saved: {adapter_path}/")

    # Save merged model (full, ~14GB)
    merged_path = os.path.join(args.output_dir, "merged_model")
    model.save_pretrained_merged(merged_path, tokenizer, save_method="merged_16bit")
    print(f"  Merged model saved: {merged_path}/")

    # Export GGUF for LM Studio
    if not args.skip_gguf:
        gguf_path = os.path.join(args.output_dir, "nexus-trader-Q4_K_M.gguf")
        print(f"  Exporting GGUF (this takes a few minutes)...")
        model.save_pretrained_gguf(
            os.path.join(args.output_dir, "gguf_temp"),
            tokenizer,
            quantization_method="q4_k_m",
        )
        # Move the GGUF file
        import glob
        gguf_files = glob.glob(os.path.join(args.output_dir, "gguf_temp", "*.gguf"))
        if gguf_files:
            os.rename(gguf_files[0], gguf_path)
            # Clean up temp
            import shutil
            shutil.rmtree(os.path.join(args.output_dir, "gguf_temp"), ignore_errors=True)
            print(f"  GGUF model saved: {gguf_path}")
            print(f"\n{'='*60}")
            print(f"TO USE IN LM STUDIO:")
            print(f"  1. Open LM Studio")
            print(f"  2. Go to My Models")
            print(f"  3. Click 'Show in File Explorer'")
            print(f"  4. Copy {gguf_path} into the models folder")
            print(f"  5. Select the model in LM Studio and chat")
            print(f"  6. In NEXUS Settings, set provider to 'lmstudio'")
            print(f"     and model to the GGUF filename")
        else:
            print("  Warning: GGUF export may have failed")
    else:
        print("  Skipped GGUF export (--skip-gguf)")

    print(f"\n{'='*60}")
    print(f"DONE! Your fine-tuned trading model is ready.")
    print(f"\nFiles:")
    print(f"  {adapter_path}/     — LoRA adapter (~100MB, shareable)")
    print(f"  {merged_path}/     — Full merged model (~14GB)")
    if not args.skip_gguf:
        print(f"  {gguf_path}  — GGUF for LM Studio (~4GB)")


if __name__ == "__main__":
    main()
