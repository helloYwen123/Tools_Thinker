export DEBUG_MODE="true" # Enable Debug if you want to see the rollout of model during RL
export LOG_PATH="./debug_log_2b.txt"
export CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES
echo "CUDA_VISIBLE_DEVICES: $CUDA_VISIBLE_DEVICES"
export WANDB_PROJECT="code_gen_GRPO"
export NCCL_P2P_DISABLE=1
# export TOKENIZERS_PARALLELISM=true
mkdir -p Debug_logs
timestamp=$(date +"%m%d_%H%M%S")

# BUG regarding tmp file
NODE_LOCAL_STORAGE="${TMPDIR:-/tmp}"
JOB_LOCAL_DIR="$NODE_LOCAL_STORAGE/wxie/grpo_job_${SLURM_JOB_ID}"
mkdir -p "$JOB_LOCAL_DIR"
echo "Created job-specific local directory: $JOB_LOCAL_DIR"

TRITON_CACHE_PATH="$JOB_LOCAL_DIR/triton_cache"
mkdir -p "$TRITON_CACHE_PATH"
export TRITON_CACHE_DIR="$TRITON_CACHE_PATH"
echo "TRITON_CACHE_DIR set to: $TRITON_CACHE_DIR"

WANDB_LOCAL_PATH="$JOB_LOCAL_DIR/wandb"
mkdir -p "$WANDB_LOCAL_PATH"
export WANDB_DIR="$WANDB_LOCAL_PATH"

WANDB_CACHE_PATH="$JOB_LOCAL_DIR/wandb_cache"
mkdir -p "$WANDB_CACHE_PATH"
export WANDB_CACHE_DIR="$WANDB_CACHE_PATH"

WANDB_CONFIG_PATH="$JOB_LOCAL_DIR/wandb_config"
mkdir -p "$WANDB_CONFIG_PATH"
export WANDB_CONFIG_DIR="$WANDB_CONFIG_PATH"
# BUG

accelerate launch --main_process_port 29508 --config_file=configs/zero3.yaml src/open_r1/toolsgrpo.py \
    --confile configs/prompt_configuration_file.yaml \
    --output_dir outputs/Qwen2-VL-2B-Instruct-GRPO-BLINK \
    --model_name_or_path Qwen/Qwen2-VL-2B-Instruct \
    --dataset_name BLINK_visual_counting \
    --max_prompt_length 4096 \
    --max_completion_length 2024 \
    --per_device_train_batch_size 1 \
    --gradient_accumulation_steps 2 \
    --logging_steps 1 \
    --bf16 true \
    --torch_dtype bfloat16 \
    --gradient_checkpointing true \
    --attn_implementation flash_attention_2 \
    --max_pixels 401408 \
    --num_train_epochs 2 \
    --temperature 1.0 \
    --run_name Qwen2-VL-2B-GRPO-SAT \
    --save_steps 100 \
    --save_only_model true \
    --report_to wandb \
    --use_cpu False \
    --num_generations 8 \
    2>&1 | tee "Debug_logs/training_log_${timestamp}.txt"