# Copyright 2024 Bytedance Ltd. and/or its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json

import ray
from omegaconf import OmegaConf

from ..single_controller.ray import RayWorkerGroup
from ..utils.tokenizer import get_processor, get_tokenizer
from ..workers.fsdp_workers import FSDPWorker
from ..workers.reward import BatchFunctionRewardManager, SequentialFunctionRewardManager
from .config import PPOConfig
from .data_loader import create_dataloader
from .ray_trainer import RayPPOTrainer, ResourcePoolManager, Role

import torch
import gc
# please make sure main_task is not scheduled on head
@ray.remote(num_cpus=1)
class Runner:
    """A runner for RL training."""

    def run(self, config: PPOConfig):
        # print config
        print(json.dumps(config.to_dict(), indent=2))

        # instantiate tokenizer
        tokenizer = get_tokenizer(
            config.worker.actor.model.model_path,
            trust_remote_code=config.worker.actor.model.trust_remote_code,
            use_fast=True,
        )
        processor = get_processor(
            config.worker.actor.model.model_path,
            trust_remote_code=config.worker.actor.model.trust_remote_code,
            use_fast=True,
        )

        # define worker classes
        ray_worker_group_cls = RayWorkerGroup
        role_worker_mapping = {
            Role.ActorRollout: ray.remote(FSDPWorker),
            Role.Critic: ray.remote(FSDPWorker),
            Role.RefPolicy: ray.remote(FSDPWorker),
        }
        global_pool_id = "global_pool"
        resource_pool_spec = {
            global_pool_id: [config.trainer.n_gpus_per_node] * config.trainer.nnodes,
        }
        mapping = {
            Role.ActorRollout: global_pool_id,
            Role.Critic: global_pool_id,
            Role.RefPolicy: global_pool_id,
        }
        resource_pool_manager = ResourcePoolManager(resource_pool_spec=resource_pool_spec, mapping=mapping)

        if config.worker.reward.reward_type == "sequential":
            RewardManager = SequentialFunctionRewardManager
        elif config.worker.reward.reward_type == "batch":
            RewardManager = BatchFunctionRewardManager
        else:
            raise NotImplementedError(f"Unknown reward type {config.worker.reward.reward_type}.")
        
        RemoteRewardManager = ray.remote(RewardManager).options(num_cpus=config.worker.reward.num_cpus, num_gpus=config.worker.reward.num_gpus)
        reward_fn = RemoteRewardManager.remote(config.worker.reward, tokenizer)
        val_reward_fn = RemoteRewardManager.remote(config.worker.reward, tokenizer)
        
        train_dataloader, val_dataloader = create_dataloader(
            config=config.data, tokenizer=tokenizer, processor=processor
        )
        ########################################
        # check prompt loading and model inputs#
        ########################################
        # n = 0
        # import os
        # log_dir = "/workspace/ywen_ws/Tools_Thinker/logs"
        # os.makedirs(log_dir, exist_ok=True)
        # path = os.path.join(log_dir, "Mix_SAT.txt")
        
        # for batch in train_dataloader:
        #     if n > 0:
        #         break
        #     print(f"the type of batch: {type(batch)}")
        #     print(f"the length of batch: {len(batch)}")
        #     print (f"key: {batch.keys()}")
        #     with open(path ,"w") as f:
        #         f.write(f"batch : {batch}\n")
        #     n += 1
            
        trainer = RayPPOTrainer(
            config=config,
            tokenizer=tokenizer,
            processor=processor,
            train_dataloader=train_dataloader,
            val_dataloader=val_dataloader,
            role_worker_mapping=role_worker_mapping,
            resource_pool_manager=resource_pool_manager,
            ray_worker_group_cls=ray_worker_group_cls,
            reward_fn=reward_fn,
            val_reward_fn=val_reward_fn, # None
        )
        trainer.init_workers()
        trainer.fit()

        # clear memory
        if torch.distributed.is_initialized():
            torch.distributed.destroy_process_group()
        gc.collect()
        torch.cuda.empty_cache()
        
def main():
    cli_args = OmegaConf.from_cli()
    default_config = OmegaConf.structured(PPOConfig())

    if hasattr(cli_args, "config"):
        config_path = cli_args.pop("config", None)
        file_config = OmegaConf.load(config_path)
        default_config = OmegaConf.merge(default_config, file_config)

    ppo_config = OmegaConf.merge(default_config, cli_args)
    ppo_config: PPOConfig = OmegaConf.to_object(ppo_config)
    ppo_config.deep_post_init()
    
    import os
    ray_log_dir = f"/workspace/ywen_ws/ray" # ray absolute path
    os.makedirs(ray_log_dir, exist_ok=True)
    
    os.environ["TOKENIZERS_PARALLELISM"] = "true"
    os.environ["NCCL_DEBUG"] = "WARN"
    os.environ["VLLM_LOGGING_LEVEL"] = "INFO"
    os.environ["TORCH_NCCL_AVOID_RECORD_STREAMS"] = "1"
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:False"
    if not ray.is_initialized():
        ray.init(_temp_dir=ray_log_dir,include_dashboard=False)

    runner = Runner.remote()
    ray.get(runner.run.remote(ppo_config))

if __name__ == "__main__":
    main()
