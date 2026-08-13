#!/bin/bash
set -e

echo "=== NEXUS Trading Model Fine-tuning (DUAL GPU OPTIMIZED) ==="
echo "GPU(s): $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"

export CUDA_VISIBLE_DEVICES=0,1

# Fix DNS if needed
if ! ping -c 1 -W 2 pypi.org &>/dev/null; then
    echo "Fixing DNS..."
    echo "nameserver 8.8.8.8" > /etc/resolv.conf
    echo "nameserver 1.1.1.1" >> /etc/resolv.conf
fi

echo "[1/6] Installing dependencies..."
pip install -q transformers peft trl datasets bitsandbytes accelerate

echo "[2/6] Configuring Accelerate..."
accelerate config default

# Check dataset
if [ ! -f "training_data.jsonl" ]; then
    echo "ERROR: training_data.jsonl not found"
    exit 1
fi

EXAMPLES=$(wc -l < training_data.jsonl)
echo "[3/6] Found training_data.jsonl ($EXAMPLES examples)"

echo "[4/6] Preparing training script..."

cat > run_train.py << 'PYEOF'
import os, json, torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training, PeftModel
from trl import SFTTrainer
from datasets import Dataset

# ========= CONFIG =========
MODEL = "Qwen/Qwen2.5-7B-Instruct"
SEQ_LEN = 1024
BATCH = 4
EPOCHS = 2

LR = 2e-5
LORA_RANK = 64
RESUME_PATH = "output/checkpoints/checkpoint-2000"
# ==========================

print(f"GPUs available: {torch.cuda.device_count()}")

# Load dataset
with open("training_data.jsonl") as f:
    examples = [json.loads(l) for l in f]

print(f"Examples: {len(examples)}")

tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
if tok.pad_token is None:
    tok.pad_token = tok.eos_token

def fmt(ex):
    return {"text": tok.apply_chat_template(ex["messages"], tokenize=False, add_generation_prompt=False)}

ds = Dataset.from_list(examples).map(fmt)

split = ds.train_test_split(test_size=0.05, seed=42)
print(f"Train: {len(split['train'])}, Eval: {len(split['test'])}")

# Load model (NO device_map!)
bnb = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True
)

model = AutoModelForCausalLM.from_pretrained(
    MODEL,
    quantization_config=bnb,
    trust_remote_code=True,
    torch_dtype=torch.bfloat16
)

model = prepare_model_for_kbit_training(model)

# LoRA
lora = LoraConfig(
    r=LORA_RANK,
    lora_alpha=LORA_RANK * 2,
    lora_dropout=0.05,
    target_modules=[
        "q_proj","k_proj","v_proj","o_proj",
        "gate_proj","up_proj","down_proj"
    ],
    bias="none",
    task_type="CAUSAL_LM"
)

model = get_peft_model(model, lora)

# Load previous adapter safely (optional)
if os.path.exists(RESUME_PATH):
    print(f"Loading adapter from {RESUME_PATH}")
    model = PeftModel.from_pretrained(model, RESUME_PATH)

model.print_trainable_parameters()

# Training args (multi-GPU stable)
train_args = TrainingArguments(
    output_dir="output/checkpoints",

    per_device_train_batch_size=BATCH,
    gradient_accumulation_steps=4,

    num_train_epochs=EPOCHS,
    learning_rate=LR,
    warmup_ratio=0.05,

    logging_steps=25,
    eval_strategy="no",

    save_strategy="steps",
    save_steps=1000,
    save_total_limit=2,

    optim="adamw_8bit",
    max_grad_norm=1.0,

    bf16=True,
    fp16=False,

    gradient_checkpointing=True,

    logging_nan_inf_filter=True,
    report_to="none",
    seed=42,
)

# Trainer compatibility
import inspect
sig = inspect.signature(SFTTrainer.__init__)
params = list(sig.parameters.keys())

kwargs = {
    "model": model,
    "args": train_args,
    "train_dataset": split["train"],
    "eval_dataset": split["test"]
}

if "processing_class" in params:
    kwargs["processing_class"] = tok
elif "tokenizer" in params:
    kwargs["tokenizer"] = tok

if "max_seq_length" in params:
    kwargs["max_seq_length"] = SEQ_LEN

if "dataset_text_field" in params:
    kwargs["dataset_text_field"] = "text"
    kwargs["packing"] = False

trainer = SFTTrainer(**kwargs)

# Train
print("Starting training...")

try:
    stats = trainer.train()
    print(f"Training complete! Loss: {stats.training_loss:.4f}")
except Exception as e:
    print("TRAINING CRASHED:", e)
    model.save_pretrained("output/crash_adapter")
    raise

# Save LoRA
os.makedirs("output", exist_ok=True)
model.save_pretrained("output/lora_adapter")
tok.save_pretrained("output/lora_adapter")

# Merge
print("Merging adapter...")
merged = model.merge_and_unload()

merged.save_pretrained("output/merged_model", safe_serialization=True)
tok.save_pretrained("output/merged_model")

print("TRAINING_DONE")
PYEOF

echo "[5/6] Training with BOTH GPUs..."
accelerate launch --multi_gpu run_train.py

echo "[6/6] Converting to GGUF..."

if [ ! -d "llama.cpp" ]; then
    git clone https://github.com/ggml-org/llama.cpp
fi

cd llama.cpp
pip install -q -r requirements.txt

python convert_hf_to_gguf.py ../output/merged_model \
    --out-type q4_k_m \
    --outfile ../output/nexus-trader-Q4_K_M.gguf

cd ..

echo ""
echo "=========================================="
echo " DONE! Dual-GPU model ready."
echo "=========================================="
ls -lh output/nexus-trader-Q4_K_M.gguf