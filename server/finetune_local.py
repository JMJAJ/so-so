"""
Local LoRA fine-tuning for NEXUS trading agent.
Uses standard HuggingFace (no unsloth, works on Windows).

Usage:
    pip install transformers peft trl datasets bitsandbytes accelerate
    python finetune_local.py --epochs 1 --max-examples 20000
"""

import os
import json
import random
import argparse
from pathlib import Path

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer
from datasets import Dataset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, default="training_data.jsonl")
    parser.add_argument("--base-model", type=str, default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--lora-rank", type=int, default=32)
    parser.add_argument("--max-seq-len", type=int, default=1024)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--max-examples", type=int, default=20000)
    parser.add_argument("--output-dir", type=str, default="output")
    args = parser.parse_args()

    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_mem / 1e9:.1f} GB")

    # Load data
    with open(args.data) as f:
        all_examples = [json.loads(line) for line in f]
    print(f"Total examples in file: {len(all_examples)}")

    # Downsample if needed
    if len(all_examples) > args.max_examples:
        random.seed(42)
        all_examples = random.sample(all_examples, args.max_examples)
    print(f"Using: {len(all_examples)} examples")

    # Tokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    def format_example(example):
        messages = example["messages"]
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        return {"text": text}

    dataset = Dataset.from_list(all_examples)
    dataset = dataset.map(format_example)
    split = dataset.train_test_split(test_size=0.05, seed=42)
    train_dataset = split["train"]
    eval_dataset = split["test"]
    print(f"Train: {len(train_dataset)}, Eval: {len(eval_dataset)}")

    # Load model in 4-bit
    print(f"Loading {args.base_model} in 4-bit...")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.float16,
    )

    model = prepare_model_for_kbit_training(model)

    # Apply LoRA
    lora_config = LoraConfig(
        r=args.lora_rank,
        lora_alpha=args.lora_rank * 2,
        lora_dropout=0.05,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        bias="none",
        task_type="CAUSAL_LM",
    )

    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # Train
    print("Starting training...")
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
            gradient_accumulation_steps=8,
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            warmup_steps=10,
            logging_steps=25,
            eval_strategy="no",
            save_strategy="steps",
            save_steps=1000,
            save_total_limit=1,
            optim="adamw_8bit",
            seed=42,
            report_to="none",
            fp16=True,
        ),
    )

    stats = trainer.train()
    print(f"\nTraining loss: {stats.training_loss:.4f}")

    # Save
    os.makedirs(args.output_dir, exist_ok=True)

    adapter_path = os.path.join(args.output_dir, "lora_adapter")
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    print(f"LoRA adapter saved: {adapter_path}/")

    # Merge and save full model
    print("Merging adapter into base model...")
    merged_model = model.merge_and_unload()
    merged_path = os.path.join(args.output_dir, "merged_model")
    merged_model.save_pretrained(merged_path, safe_serialization=True)
    tokenizer.save_pretrained(merged_path)
    print(f"Merged model saved: {merged_path}/")

    print(f"\n{'='*60}")
    print("DONE! To convert to GGUF for LM Studio:")
    print("  pip install llama-cpp-python[server]")
    print(f"  # Or use llama.cpp convert script on {merged_path}/")
    print(f"\nAlternatively, serve the merged model directly with:")
    print(f"  python -m vllm.entrypoints.openai.api_server --model {merged_path}")


if __name__ == "__main__":
    main()
