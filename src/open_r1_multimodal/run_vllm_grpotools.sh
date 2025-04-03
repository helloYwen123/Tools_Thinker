#!/bin/bash


# The latest vllm==0.7.3 is required for this script: pip3 install vllm==0.7.3
# The latest transformers is required too, install by: pip install git+https://github.com/huggingface/transformers.git@a40f1ac602fe900281722254c52ce3773f28eb0e



export DEBUG_MODE="true"
export LOG_PATH="./vllm_run.txt"
export TOKENIZERS_PARALLELISM=false
echo "CUDA_VISIBLE_DEVICES: $CUDA_VISIBLE_DEVICES"

QWEN_PATH="Qwen/Qwen2-VL-2B-Instruct"  # Qwen2.5
HF_DATASET="BLINK_visual_counting" 
OUTPUT_DIR="outputs/Qwen2-VL-2B-Instruct-GRPO-BLINK"
if [ ! -d "$OUTPUT_DIR" ]; then
 mkdir -p "$OUTPUT_DIR"
fi
RUN_NAME="Qwen2-VL-2B-GRPO-BLINK"
DS_CONFIG="configs/zero1_no_optimizer.json"  # Note that other zero setting would meet bugs related to vllm at current stage.

# NOTE: you are expected to use X + 1 cards for X training proc and 1 vLLM proc 
# e.g., the visible devices should be 0,1,2,3,4 for 5 cards, and  --nproc_per_node="4"

CUDA_VISIBLE_DEVICES="0,1,2,3" torchrun \
    --nproc_per_node="3" \
    --nnodes="1" \
    --node_rank="0" \
    --master_addr="127.0.0.1" \
    --master_port="12345" \
    src/open_r1/toolsgrpo.py \
    --confile configs/configuration_file.yaml \
    --use_vllm true \
    --output_dir ${OUTPUT_DIR} \
    --model_name_or_path ${QWEN_PATH} \
    --dataset_name ${HF_DATASET} \
    --max_prompt_length 4096 \
    --max_completion_length 2048 \
    --per_device_train_batch_size 1 \
    --gradient_accumulation_steps 2 \
    --learning_rate 1e-6 \
    --lr_scheduler_type "constant" \
    --logging_steps 1 \
    --bf16 true \
    --torch_dtype bfloat16 \
    --gradient_checkpointing true \
    --attn_implementation flash_attention_2 \
    --max_pixels 401408 \
    --num_train_epochs 2 \
    --run_name ${RUN_NAME} \
    --save_steps 100 \
    --save_total_limit 3 \
    --save_only_model true \
    --report_to wandb \
    --temperature 1.0 \
    --num_generations 8 \
    --vllm_device "cuda:3" \
    --vllm_gpu_memory_utilization 0.8 \
    --deepspeed ${DS_CONFIG} \
    2>&1 | tee "${OUTPUT_DIR}/training_log.txt"
