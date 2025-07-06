export WANDB_PROJECT="sft"
export WANDB_API_KEY="2d883ab1037c7c4b261d54b523c3515fa87dde91"
# oumi train
# oumi distributed torchrun \
#   -m oumi train \
#   -c traintools.yaml \
#   --fsdp.enable_fsdp true \
#   --fsdp.sharding_strategy FULL_SHARD

oumi train -c traintools.yaml

# # Using DDP (DistributedDataParallel)
# oumi distributed torchrun \
#   -m oumi train \
#   -c configs/recipes/llama3_2/sft/3b_full/train.yaml

# # Using FSDP (Fully Sharded Data Parallel)
# oumi distributed torchrun \
#   -m oumi train \
#   -c configs/recipes/llama3_2/sft/3b_full/train.yaml \
#   --fsdp.enable_fsdp true \
#   --fsdp.sharding_strategy FULL_SHARD