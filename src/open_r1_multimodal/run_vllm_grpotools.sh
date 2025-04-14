#!/bin/bash
# The latest vllm==0.7.3 is required for this script: pip3 install vllm==0.7.3
# The latest transformers is required too, install by: pip install git+https://github.com/huggingface/transformers.git@a40f1ac602fe900281722254c52ce3773f28eb0e

# export DEBUG_MODE="true"
# export LOG_PATH="./vllm_run.txt"
# export NCCL_DEBUG=INFO
# export NCCL_DEBUG_SUBSYS=ALL
export NCCL_P2P_DISABLE=1
export WANDB_PROJECT="code_gen_GRPO"
export TOKENIZERS_PARALLELISM=false
export CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES
echo "CUDA_VISIBLE_DEVICES: $CUDA_VISIBLE_DEVICES"

# export MKL_SERVICE_FORCE_INTEL=1
QWEN_PATH="Qwen/Qwen2-VL-2B-Instruct"  # Qwen2.5
HF_DATASET="SAT" 

OUTPUT_DIR="outputs/Qwen2-VL-2B-Instruct-GRPO-SAT"
if [ ! -d "$OUTPUT_DIR" ]; then
 mkdir -p "$OUTPUT_DIR"
fi
RUN_NAME="Qwen2-VL-2B-GRPO-vLLM"
DS_CONFIG="configs/zero1_no_optimizer.json"  # Note that other zero setting would meet bugs related to vllm at current stage.

mkdir -p Debug_logs
timestamp=$(date +"%m%d_%H%M%S")
# NOTE: you are expected to use X + 1 cards for X training proc and 1 vLLM proc 
# e.g., the visible devices should be 0,1,2,3,4 for 5 cards, and  --nproc_per_node="4"

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

    torchrun \
    --nproc_per_node="5" \
    --nnodes="1" \
    --node_rank="0" \
    --master_addr="127.0.0.1" \
    --master_port="12345" \
    src/open_r1/toolsgrpo.py \
    --confile configs/prompt_configuration_file.yaml \
    --use_vllm true \
    --output_dir ${OUTPUT_DIR} \
    --model_name_or_path ${QWEN_PATH} \
    --dataset_name ${HF_DATASET} \
    --max_prompt_length 4096 \
    --max_completion_length 512 \
    --per_device_train_batch_size 1 \
    --gradient_accumulation_steps 2 \
    --learning_rate 1e-6 \
    --lr_scheduler_type "constant" \
    --logging_steps 1 \
    --bf16 true \
    --torch_dtype bfloat16 \
    --gradient_checkpointing true \
    --attn_implementation flash_attention_2 \
    --min_pixels 3136 \
    --max_pixels 401408 \
    --num_train_epochs 2 \
    --run_name ${RUN_NAME} \
    --save_steps 100 \
    --save_total_limit 3 \
    --save_only_model true \
    --report_to wandb \
    --temperature 1.0 \
    --num_generations 7 \
    --vllm_device "cuda:5" \
    --vllm_gpu_memory_utilization 0.8 \
    --deepspeed ${DS_CONFIG} \
    2>&1 | tee "Debug_logs/training_log_${timestamp}.txt"