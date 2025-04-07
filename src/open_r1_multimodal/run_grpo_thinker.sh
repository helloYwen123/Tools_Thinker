export DEBUG_MODE="true" # Enable Debug if you want to see the rollout of model during RL
export LOG_PATH="./debug_log_2b.txt"
export CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES
echo "CUDA_VISIBLE_DEVICES: $CUDA_VISIBLE_DEVICES"
export WANDB_PROJECT="code_gen_GRPO"
# export MAIN_PROCESS_PORT=29507  # Change this to an available port
export NCCL_P2P_DISABLE=1
export TOKENIZERS_PARALLELISM=false

# netstat -tulnp | grep 29507
#"flash_attention_2",  #  "eager" / "sdpa"

# Confusing Parameters
# dataset_name: push_to_hub; 
# respectively modify zero3 yaml `num_processes` to control parallel GPU computation

accelerate launch --main_process_port 29508 --config_file=configs/zero3.yaml src/open_r1/toolsgrpo.py \
    --confile configs/prompt_configuration_file.yaml \
    --output_dir outputs/Qwen2-VL-2B-Instruct-GRPO-BLINK \
    --model_name_or_path Qwen/Qwen2-VL-2B-Instruct \
    --dataset_name BLINK_visual_counting \
    --max_prompt_length 4096 \
    --max_completion_length 2048 \
    --per_device_train_batch_size 1 \
    --gradient_accumulation_steps 2 \
    --logging_steps 1 \
    --bf16 true \
    --torch_dtype bfloat16 \
    --gradient_checkpointing true \
    --attn_implementation flash_attention_2 \
    --max_pixels 401408 \
    --num_train_epochs 3 \
    --run_name Qwen2-VL-2B-GRPO-BLINK \
    --save_steps 100 \
    --save_only_model true \
    --report_to wandb \
    --use_cpu False \
    --num_generations 8 \