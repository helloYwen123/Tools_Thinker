#! /bin/bash

#SBATCH --job-name=Clever            # name of work
#SBATCH --nodes=1
#SBATCH --output=Cleverlog-%j/slurm-%j.out   # output log (%j replaced by ID)
#SBATCH --error=Cleverlog-%j/slurm-%j.err    # error log (%j replaced by ID)
#SBATCH --partition=all        # specific partition
#SBATCH --gres=gpu:1               # assign n GPUs
#SBATCH --cpus-per-task=1          # the num of cpu for one task
#SBATCH --mem=32G             # assign memory
#SBATCH --time=10-00:00:00              # time limitation
#SBATCH --ntasks=1                   # num of works
#SBATCH --nodelist=worker-6      # specify a particular node

echo "Job $SLURM_JOB_ID starting on $SLURMD_NODENAME"

# Load your conda environment
source ~/.bashrc  # 确保 conda 命令可用
conda activate easyr1
echo "Activated conda environment: easyr1"

# Go to your working directory
cd /home/stud/wxie/Dataset_Create/src/sft/train/

python oumi_train_format.py

echo "Job $SLURM_JOB_ID finished."

