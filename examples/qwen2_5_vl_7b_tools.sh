set -x

export WANDB_API_KEY=2d883ab1037c7c4b261d54b523c3515fa87dde91
MODEL_PATH=/workspace/ywen_ws/saved_model/tool_thinker-0.1 #/workspace/ywen_ws/saved_model/tool_thinker-0.1 #Qwen/Qwen2.5-VL-7B-Instruct  # replace it with your local file path


timestamp=$(date +"%m%d_%H%M%S")

mkdir -p debug_logs

echo "CUDA_VISIBLE_DEVICES: $CUDA_VISIBLE_DEVICES"

echo "huggingface cahce: $HF_HOME"
export RAY_DISABLE_DASHBOARD=1
# Blink: BLINK-Benchmark/BLINK
# SAT: SAT
# Mixed_SAT: /workspace/ywen_ws/datasets/Mix_VQAs.json



PYTHONUNBUFFERED=1 python -m verl.trainer.main_tools \
    config=examples/tools_config/config_tools.yaml \
    data.train_files=Mixed_SAT \
    data.val_files=Mixed_SAT \
    worker.actor.model.model_path=${MODEL_PATH} \
    worker.rollout.tensor_parallel_size=1 \
    trainer.experiment_name=qwen2_5_vl_7b_grpo \
    trainer.n_gpus_per_node=2 \
    2>&1 | tee "debug_logs/training_log_${timestamp}.txt"

