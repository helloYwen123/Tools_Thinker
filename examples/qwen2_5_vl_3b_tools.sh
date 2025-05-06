set -x

export NCCL_P2P_DISABLE=1
MODEL_PATH=Qwen/Qwen2.5-VL-3B-Instruct  # replace it with your local file path
timestamp=$(date +"%m%d_%H%M%S")
mkdir -p Debug_logs
echo "CUDA_VISIBLE_DEVICES: $CUDA_VISIBLE_DEVICES"

# Blink: BLINK-Benchmark/BLINK
# SAT: SAT
PYTHONUNBUFFERED=1 python3 -m verl.trainer.main_tools \
    config=examples/config_tools.yaml \
    data.train_files=BLINK-Benchmark/BLINK \
    data.val_files=BLINK-Benchmark/BLINK \
    worker.actor.model.model_path=${MODEL_PATH} \
    worker.rollout.tensor_parallel_size=1 \
    trainer.experiment_name=qwen2_5_vl_3b_grpo \
    trainer.n_gpus_per_node=1 \
    2>&1 | tee "Debug_logs/training_log_${timestamp}.txt"