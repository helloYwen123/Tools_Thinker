#!/bin/bash
#SBATCH --job-name=syang-thinker        
#SBATCH --partition=all                 
#SBATCH --nodes=1                       
#SBATCH --ntasks=1                     
#SBATCH --cpus-per-task=8               
#SBATCH --gres=gpu:5                    
#SBATCH --mem=0                         
#SBATCH --time=1-00:00:00               
#SBATCH --output=syang_sbatch_logs/%x-%j.out        
#SBATCH --error=syang_sbatch_logs/%x-%j.err          
#SBATCH --mail-user=shucheng.yang@tum.de
#SBATCH --mail-type=BEGIN,END,FAIL

echo "== Job start: $(date) =="

# 1) 初始化 conda
source ~/.bashrc
conda activate thinker

# 2) 进入脚本所在目录
cd /home/stud/syang/Tools_Thinker/src/open_r1_multimodal

# 3) 启动你的训练脚本
bash run_grpo_thinker_syang.sh        # :contentReference[oaicite:0]{index=0}:contentReference[oaicite:1]{index=1}

echo "== Job end: $(date) =="
