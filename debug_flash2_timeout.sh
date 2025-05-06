#!/usr/bin/env bash
# debug_flash2_timeout.sh
# 依次尝试 nvidia_a100-pcie、nvidia_rtx_a6000、nvidia_l40s、nvidia_a40，
# 如果某型号申请排队超过 180s 就放弃，切换下一个

GPU_TYPES=(nvidia_a100-pcie-40gb nvidia_rtx_a6000 nvidia_l40s nvidia_a40)
TIMEOUT="180s"
GPU_NUM=2
# 排队最大等候时间

for TYPE in "${GPU_TYPES[@]}"; do
  echo "→ 尝试在 ${TYPE} 上分配 ${GPU_NUM} 卡（排队最长 ${TIMEOUT}）……"
  timeout --foreground $TIMEOUT srun \
    --job-name=syang-thinker \
    --nodes=1 \
    --ntasks=1 \
    --cpus-per-task=16 \
    --gres=gpu:${TYPE}:${GPU_NUM} \
    --mem=0 \
    --time=00:30:00 \
    --pty /bin/bash

  RET=$?
  if [ $RET -eq 0 ]; then
    # 成功拿到资源并进入了交互式 shell（退出码 0）
    exit 0
  elif [ $RET -eq 124 ]; then
    # timeout 命令超时，会返回 124，代表“排队超过 $TIMEOUT”
    echo "  ⚠️ ${TYPE} 等候超过 ${TIMEOUT}，放弃并尝试下一个型号"
  else
    # 其他错误（比如格式写错），也跳下一个
    echo "  ❌ ${TYPE} 申请出错 (exit code $RET)，尝试下一个"
  fi
done

echo "❗️ 所有型号都尝试完毕，仍未分到可用节点。"
exit 1
