#!/bin/bash

#SBATCH --job-name=w_m_woe
#SBATCH --partition=lrz-hgx-a100-80x4
#SBATCH --gres=gpu:2
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --mem=512g
#SBATCH --time=2-00:00:00
#SBATCH --output=/dss/dssmcmlfs01/pn39qo/pn39qo-dss-0000/di97cow/sbatch_logs/output_%j.log                   
#SBATCH --error=/dss/dssmcmlfs01/pn39qo/pn39qo-dss-0000/di97cow/sbatch_logs/error_%j.log
#SBATCH --container-image=/dss/dssmcmlfs01/pn39qo/pn39qo-dss-0000/di97cow/easytool.sqsh
#SBATCH --container-mounts=/dss/dssmcmlfs01/pn39qo/pn39qo-dss-0000/di97cow/vlm_project:/workspace/ywen_ws/,/dss/mcmlscratch/06/di97cow/vlm_project/saved_model:/workspace/models/

# available partitions:
# lrz-hgx-a100-80x4,lrz-dgx-a100-80x8,lrz-hgx-h100-94x4, mcml-hgx-a100-80x4,mcml-hgx-h100-94x4,mcml-hgx-a100-80x4-mig, mcml-dgx-a100-40x8
# SBATCH --qos=mcml
source /workspace/ywen_ws/miniconda/etc/profile.d/conda.sh
conda activate vlm

echo 'Activated conda env: vlm'
cd /workspace/ywen_ws/Tools_Thinker

bash examples/purecode_457_w_code_think_length_w_multi_wo_e_semi.sh