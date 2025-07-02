#! /bin/bash

#SBATCH --job-name=eval            # name of work
#SBATCH --nodes=1
#SBATCH --output=evallog-%j/slurm-%j.out   # output log (%j replaced by ID)
#SBATCH --error=evallog-%j/slurm-%j.err    # error log (%j replaced by ID)
#SBATCH --partition=all        # specific partition
#SBATCH --gres=gpu:1               # assign n GPUs
#SBATCH --cpus-per-task=1          # the num of cpu for one task
#SBATCH --mem=32G             # assign memory
#SBATCH --time=10-00:00:00              # time limitation
#SBATCH --ntasks=1                   # num of works
#SBATCH --nodelist=worker-6      # specify a particular node

echo "Job $SLURM_JOB_ID starting on $SLURMD_NODENAME"

# Load your conda environment
source ~/.bashrc 
conda activate sft
echo "Activated conda environment: sft"

# Go to your working directory
cd /home/stud/wxie/Dataset_Create/src/sft/eval/

python eval.py

echo "Job $SLURM_JOB_ID finished."

