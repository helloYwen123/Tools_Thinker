set -x

export WANDB_API_KEY=2d883ab1037c7c4b261d54b523c3515fa87dde91
MODEL_PATH=Qwen/Qwen2.5-VL-7B-Instruct #/home/stud/wxie/Dataset_Create/src/sft/train/output/vlm_finetuned #Qwen/Qwen2.5-VL-7B-Instruct  # replace it with your local file path


timestamp=$(date +"%m%d_%H%M%S")
mkdir -p Debug_logs
echo "CUDA_VISIBLE_DEVICES: $CUDA_VISIBLE_DEVICES"

export HF_HOME=/home/vault/v100dd/v100dd23/hf_cache
echo "huggingface cahce: $HF_HOME"
export RAY_DISABLE_DASHBOARD=1
# Blink: BLINK-Benchmark/BLINK
# SAT: SAT
# Mixed_SAT: /nfs/data8/liao/wxie/datasets/mixed_vqa.json



PYTHONUNBUFFERED=1 python -m verl.trainer.main_tools \
    config=examples/config_tools.yaml \
    data.train_files=Mixed_SAT \
    data.val_files=Mixed_SAT \
    worker.actor.model.model_path=${MODEL_PATH} \
    worker.rollout.tensor_parallel_size=1 \
    trainer.experiment_name=qwen2_5_vl_7b_grpo \
    trainer.n_gpus_per_node=2 \
    2>&1 | tee "Debug_logs/training_log_${timestamp}.txt"