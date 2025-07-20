#!/bin/bash
# /workspace/ywen_ws/datasets/Spatial457/questions_sat/L1_single_mcq.json
# /workspace/ywen_ws/datasets/Spatial457/questions_sat/L2_objects_mcq.json \
# /workspace/ywen_ws/datasets/Spatial457/questions_sat/L3_2D_spatial_mcq.json \
# /workspace/ywen_ws/datasets/Spatial457/questions_sat/L4_occ_mcq.json \
# /workspace/ywen_ws/datasets/Spatial457/questions_sat/L4_pose_mcq.json \
# /workspace/ywen_ws/datasets/Spatial457/questions_sat/L5_6d_spatial_mcq.json \
# /workspace/ywen_ws/datasets/Spatial457/questions_sat/L5_collision_mcq.json \

# /workspace/models/sft/ tool_thinker-0.1  tools_nl_0.1
# /workspace/models/grpo_models/  tools_180steps mixture_40steps

OUTPUT_ROOT="/workspace/ywen_ws/eval/eval_tools_grpo" # 改
DATASET="Spatial457"
CONFIG_FILE="/workspace/ywen_ws/Tools_Thinker/scripts/eval_config/prompt.yaml" # 改 prompt_nl
PREFIX="/workspace/ywen_ws/datasets"
MODEL="/workspace/models/grpo_models/tools_180steps" # 改

python scripts/batch_eval.py \
  --json_path \
    /workspace/ywen_ws/datasets/Spatial457/questions_sat/L1_single_mcq.json \
  --output_root "$OUTPUT_ROOT" \
  --dataset "$DATASET" \
  --config_file "$CONFIG_FILE" \
  --prefix "$PREFIX" \
  --model "$MODEL"

# or
#!/bin/bash

# /workspace/models/sft/ tool_thinker-0.1  tools_nl_0.1
# /workspace/models/grpo_models/  tools_180steps mixture_40steps

# JSON_DIR="/workspace/ywen_ws/datasets/Spatial457/questions_sat"
# OUTPUT_ROOT="/workspace/ywen_ws/Tools_Thinker/eval_tools_grpo" # 改
# DATASET="Spatial457"
# CONFIG_FILE="/workspace/ywen_ws/Tools_Thinker/scripts/eval_config/prompt.yaml" # 改 prompt_nl
# PREFIX="/workspace/ywen_ws/datasets"
# MODEL="/workspace/models/grpo_models/tools_180steps" # 改

# python scripts/eval.py \
#   --json_path "$JSON_DIR"/*.json \
#   --output_root "$OUTPUT_ROOT" \
#   --dataset "$DATASET" \
#   --config_file "$CONFIG_FILE" \
#   --prefix "$PREFIX" \
#   --model "$MODEL"