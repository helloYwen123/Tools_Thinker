# Copyright 2025 The HuggingFace Team. All rights reserved.
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

import os
import textwrap
from collections import defaultdict
from typing import Any, Callable, Optional, Union
from accelerate.utils.other import is_compiled_module
from accelerate.utils import broadcast_object_list, gather, gather_object
import torch
import torch.utils.data
import transformers
import warnings
from unittest.mock import patch
from datasets import Dataset, IterableDataset
from packaging import version
from transformers import (
    AriaForConditionalGeneration,
    AriaProcessor,
    AutoModelForCausalLM,
    AutoModelForSequenceClassification,
    AutoProcessor,
    AutoTokenizer,
    GenerationConfig,
    PreTrainedModel,
    PreTrainedTokenizerBase,
    Qwen2VLForConditionalGeneration,
    Qwen2_5_VLForConditionalGeneration,
    Trainer,
    TrainerCallback,
    is_wandb_available,
)
from transformers.integrations.deepspeed import is_deepspeed_zero3_enabled
from transformers.utils import is_peft_available

from trl.data_utils import (
    apply_chat_template,
    is_conversational,
    maybe_apply_chat_template,
)
from trl.import_utils import is_vllm_available

from trl.models import (
    create_reference_model,
    prepare_deepspeed,
    unwrap_model_for_generation,
)
from trl.trainer.grpo_config import GRPOConfig
from trl.trainer.utils import generate_model_card, get_comet_experiment_url, pad
from trl import GRPOTrainer

import copy
import time # computation time log

if is_peft_available():
    from peft import PeftConfig, get_peft_model

if is_vllm_available():
    from vllm import LLM, SamplingParams

if is_wandb_available():
    import wandb
import torch.nn as nn
from torch.utils.data import Sampler

# What we call a reward function is a callable that takes a list of prompts and completions and returns a list of
# rewards. When it's a string, it's a model ID, so it's loaded as a pretrained model.
RewardFunc = Union[str, PreTrainedModel, Callable[[list, list], list[float]]]


class Qwen2VLGRPOVLLMTrainerModified(Trainer):
    def __init__(
        self,
        model: Union[str, PreTrainedModel],
        reward_funcs: Union[RewardFunc, list[RewardFunc]],
        args: GRPOConfig = None,
        train_dataset: Optional[Union[Dataset, IterableDataset]] = None,
        eval_dataset: Optional[
            Union[Dataset, IterableDataset, dict[str, Union[Dataset, IterableDataset]]]
        ] = None,
        processing_class: Optional[PreTrainedTokenizerBase] = None,
        reward_processing_classes: Optional[
            Union[PreTrainedTokenizerBase, list[PreTrainedTokenizerBase]]
        ] = None,
        callbacks: Optional[list[TrainerCallback]] = None,
        optimizers: tuple[
            Optional[torch.optim.Optimizer], Optional[torch.optim.lr_scheduler.LambdaLR]
        ] = (None, None),
        peft_config: Optional["PeftConfig"] = None,
        # qwen2-vl related params
        max_pixels: Optional[int] = 12845056,
        min_pixels: Optional[int] = 3136,
        attn_implementation: str = "flash_attention_2",
        torch_dtype: str = None,  # Debug
        reward_weights: list[float] = None
        
    ):

        # Args
        if args is None:
            model_name = model if isinstance(model, str) else model.config._name_or_path
            model_name = model_name.split("/")[-1]
            args = GRPOConfig(f"{model_name}-GRPO")

        # Models
        # Trained model
        model_init_kwargs = args.model_init_kwargs or {}
        model_init_kwargs["attn_implementation"] = attn_implementation
        model_init_kwargs["torch_dtype"] = torch_dtype # Debug
        if isinstance(model, str):
            model_id = model
            torch_dtype = model_init_kwargs.get("torch_dtype")
            if (
                isinstance(torch_dtype, torch.dtype)
                or torch_dtype == "auto"
                or torch_dtype is None
            ):
                pass  # torch_dtype is already a torch.dtype or "auto" or None
            elif isinstance(torch_dtype, str):  # it's a str, but not "auto"
                torch_dtype = getattr(torch, torch_dtype)
                model_init_kwargs["torch_dtype"] = torch_dtype
            else:
                raise ValueError(
                    "Invalid `torch_dtype` passed to `GRPOConfig`. Expected either 'auto' or a string representing "
                    f"a `torch.dtype` (e.g., 'float32'), but got {torch_dtype}."
                )
            # Disable caching if gradient checkpointing is enabled (not supported)
            model_init_kwargs["use_cache"] = (
                False
                if args.gradient_checkpointing
                else model_init_kwargs.get("use_cache")
            )
            if "Qwen2-VL" in model_id:
                model = Qwen2VLForConditionalGeneration.from_pretrained(
                    model, **model_init_kwargs
                )
            elif "Qwen2.5-VL" in model_id:
                model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                    model, **model_init_kwargs
                )
            elif "Aria" in model_id:
                model_init_kwargs.pop("use_cache")
                model = AriaForConditionalGeneration.from_pretrained(
                    model, **model_init_kwargs
                )
            else:
                model = AutoModelForCausalLM.from_pretrained(model, **model_init_kwargs)
        else:
            model_id = model.config._name_or_path
            if args.model_init_kwargs is not None:
                raise ValueError(
                    "You passed `model_init_kwargs` to the `GRPOConfig`, but your model is already instantiated. "
                    "This argument can only be used when the `model` argument is a string."
                )

        if peft_config is not None:
            model = get_peft_model(model, peft_config)

        # Reference model
        if is_deepspeed_zero3_enabled():
            if "Qwen2-VL" in model_id:
                self.ref_model = Qwen2VLForConditionalGeneration.from_pretrained(
                    model_id, **model_init_kwargs
                )
            elif "Qwen2.5-VL" in model_id:
                self.ref_model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                    model, **model_init_kwargs
                )
            elif "Aria" in model_id:
                self.ref_model = AriaForConditionalGeneration.from_pretrained(
                    model_id, **model_init_kwargs
                )
            else:
                self.ref_model = AutoModelForCausalLM.from_pretrained(
                    model_id, **model_init_kwargs
                )
        elif peft_config is None:
            # If PEFT configuration is not provided, create a reference model based on the initial model.
            self.ref_model = create_reference_model(model)
        else:
            # If PEFT is used, the reference model is not needed since the adapter can be disabled
            # to revert to the initial model.
            self.ref_model = None

        # Processing class
        if processing_class is None:
            if "Qwen" in model_id or "Aria" in model_id:
                processing_class = AutoProcessor.from_pretrained(model_id)
                pad_token_id = processing_class.tokenizer.pad_token_id
                processing_class.pad_token_id = pad_token_id
                processing_class.eos_token_id = processing_class.tokenizer.eos_token_id
                if "Qwen" in model_id:
                    processing_class.image_processor.max_pixels = max_pixels
                    processing_class.image_processor.min_pixels = min_pixels
            else:
                processing_class = AutoTokenizer.from_pretrained(
                    model.config._name_or_path, padding_side="left"
                )
                pad_token_id = processing_class.pad_token_id

        # Reward functions
        if not isinstance(reward_funcs, list):
            reward_funcs = [reward_funcs]
        for i, reward_func in enumerate(reward_funcs):
            if isinstance(reward_func, str):
                reward_funcs[i] = AutoModelForSequenceClassification.from_pretrained(
                    reward_func, num_labels=1, **model_init_kwargs
                )
        self.reward_funcs = reward_funcs
        self.reward_weights = reward_weights
        # Reward processing class
        if reward_processing_classes is None:
            reward_processing_classes = [None] * len(reward_funcs)
        elif not isinstance(reward_processing_classes, list):
            reward_processing_classes = [reward_processing_classes]
        else:
            if len(reward_processing_classes) != len(reward_funcs):
                raise ValueError(
                    "The number of reward processing classes must match the number of reward functions."
                )

        for i, (reward_processing_class, reward_func) in enumerate(
            zip(reward_processing_classes, reward_funcs)
        ):
            if isinstance(reward_func, PreTrainedModel):
                if reward_processing_class is None:
                    reward_processing_class = AutoTokenizer.from_pretrained(
                        reward_func.config._name_or_path
                    )
                if reward_processing_class.pad_token_id is None:
                    reward_processing_class.pad_token = (
                        reward_processing_class.eos_token
                    )
                # The reward model computes the reward for the latest non-padded token in the input sequence.
                # So it's important to set the pad token ID to the padding token ID of the processing class.
                reward_func.config.pad_token_id = reward_processing_class.pad_token_id
                reward_processing_classes[i] = reward_processing_class
        self.reward_processing_classes = reward_processing_classes

        # Data collator
        def data_collator(features):  # No data collation is needed in GRPO
            return features

        # Training arguments
        self.max_prompt_length = args.max_prompt_length
        self.max_completion_length = (
            args.max_completion_length
        )  # = |o_i| in the GRPO paper
        self.num_generations = args.num_generations  # = G in the GRPO paper
        self.generation_config = GenerationConfig(
            max_new_tokens=self.max_completion_length,
            do_sample=True,
            temperature=1.0,  # HACK
            num_return_sequences=self.num_generations,
            pad_token_id=pad_token_id,
        )
        self.beta = args.beta

        # The trainer estimates the number of FLOPs (floating-point operations) using the number of elements in the
        # input tensor associated with the key "input_ids". However, in GRPO, the sampled data does not include the
        # "input_ids" key. Instead, the available keys is "prompt". As a result, the trainer issues the warning:
        # "Could not estimate the number of tokens of the input, floating-point operations will not be computed." To
        # suppress this warning, we set the "estimate_tokens" key in the model's "warnings_issued" dictionary to True.
        # This acts as a flag to indicate that the warning has already been issued.
        model.warnings_issued["estimate_tokens"] = True

        # Initialize the metrics
        self._metrics = defaultdict(list)
        self.use_vllm = args.use_vllm

        super().__init__(
            model=model,
            args=args,
            data_collator=data_collator,
            train_dataset=train_dataset,
            eval_dataset=eval_dataset,
            processing_class=processing_class,
            callbacks=callbacks,
            optimizers=optimizers,
        )
        # Gradient accumulation requires scaled loss. Normally, loss scaling in the parent class depends on whether the
        # model accepts loss-related kwargs. Since we compute our own loss, this check is irrelevant. We set
        # self.model_accepts_loss_kwargs to False to enable scaling.
        self.model_accepts_loss_kwargs = False

        if self.use_vllm:
            if not is_vllm_available():
                raise ImportError(
                    "vLLM is not available and `use_vllm` is set to True. Please install vLLM with "
                    "`pip install vllm` to use it."
                )

            if self.accelerator.is_main_process:
                vllm_device = self.args.vllm_device
                if vllm_device == "auto":
                    vllm_device = f"cuda:{self.accelerator.num_processes}"  # take the next GPU idx
                # Check that the requested device is available
                if (
                    vllm_device.split(":")[0] == "cuda"
                    and int(vllm_device.split(":")[1]) >= torch.cuda.device_count()
                ):
                    raise ValueError(
                        f"The requested device for vllm ({vllm_device}) is not available. You are likely using vLLM "
                        "without restricting the number of GPUs for training. Set the `--num_processes` argument to a "
                        "value lower than the number of GPUs available on your machine—typically, reducing it by one "
                        f"is sufficient. In your case: `--num_processes {torch.cuda.device_count() - 1}`."
                    )
                # Check that the requested device is not also used for training
                if vllm_device in {
                    f"cuda:{idx}" for idx in range(self.accelerator.num_processes)
                }:
                    warnings.warn(
                        f"The requested device {vllm_device} is also used for training. This may lead to unexpected "
                        "behavior. It is recommended to use a dedicated device for vLLM."
                    )
                # vLLM is not compatible with accelerate. So we need to patch it to make sure we can (1) place the vLLM
                # model on the desired device (world_size_patch) and (2) avoid a test that is not designed for our
                # setting (profiling_patch).
                world_size_patch = patch(
                    "torch.distributed.get_world_size", return_value=1
                )
                profiling_patch = patch(
                    "vllm.worker.worker.Worker._assert_memory_footprint_increased_during_profiling",
                    return_value=None,
                )
                with world_size_patch, profiling_patch:
                    print("vllm is running on: ", vllm_device)
                    self.llm = LLM(
                        model=model.name_or_path,
                        device=vllm_device,
                        gpu_memory_utilization=self.args.vllm_gpu_memory_utilization,
                        dtype=torch.bfloat16,
                        # Automatic Prefix Caching caches the KV cache of existing queries, so that a new query can
                        # directly reuse the KV cache if it shares the same prefix with one of the existing queries.
                        # This is particularly useful here because we generate completions from the same prompts.
                        enable_prefix_caching=True,
                        enforce_eager=True,
                        mm_processor_kwargs=(
                            {
                                "max_pixels": max_pixels,
                                "min_pixels": min_pixels,
                            }
                            if "Qwen2-VL" in model_id or "Qwen2.5-VL" in model_id
                            else None
                        ),
                        max_model_len=args.max_prompt_length + args.max_completion_length,
                        limit_mm_per_prompt={"image": 3}, # Debug multi-images inputs
                    )
                self.sampling_params = SamplingParams(
                    temperature=args.temperature,
                    max_tokens=self.max_completion_length,
                )

            self._last_loaded_step = 0  # tag to avoid useless loading during grad accumulation

            # When using vLLM, the main process is responsible for loading the model weights. This can cause process
            # desynchronization and seems to lead to DeepSpeed hanging during initialization. To prevent this, we
            # synchronize all processes after vLLM has been fully initialized.
            self.accelerator.wait_for_everyone()
        else:
            raise ValueError(
                "GRPOVLLMTrainerModified only supports vllm generation, please set --use_vllm True"
            )

        if self.ref_model is not None:
            if self.is_deepspeed_enabled:
                self.ref_model = prepare_deepspeed(self.ref_model, self.accelerator)
            else:
                self.ref_model = self.accelerator.prepare_model(self.ref_model, evaluation_mode=True)

        for i, reward_func in enumerate(self.reward_funcs):
            if isinstance(reward_func, PreTrainedModel):
                self.reward_funcs[i] = self.accelerator.prepare_model(reward_func, evaluation_mode=True)

    def _set_signature_columns_if_needed(self):
        # If `self.args.remove_unused_columns` is True, non-signature columns are removed.
        # By default, this method sets `self._signature_columns` to the model's expected inputs.
        # In GRPOTrainer, we preprocess data, so using the model's signature columns doesn't work.
        # Instead, we set them to the columns expected by the `training_step` method, hence the override.
        if self._signature_columns is None:
            self._signature_columns = ["prompt"]

    # Get the per-token log probabilities for the completions for the model and the reference model
    def _get_per_token_logps(
        self,
        model,
        input_ids,
        attention_mask,
        pixel_values,
        image_grid_thw,
        logits_to_keep,
    ):
        pixel_values = pixel_values.to(model.device)
        image_grid_thw = image_grid_thw.to(device=model.device)
        # if self.accelerator.is_main_process:
            # image_token_id_to_check = 151655
            # print(f"[_get_per_token_logps] Checking input_ids (shape {input_ids.shape}) right before model call...")
            # all_contain_token = True
            # for i in range(input_ids.shape[0]):
            #     if not torch.any(input_ids[i] == image_token_id_to_check):
            #         print(f"[_get_per_token_logps] FATAL DEBUG: Sample {i} in batch passed to model DOES NOT contain image token {image_token_id_to_check}!")
            #         # print(input_ids[i].tolist()) 
            #         all_contain_token = False
            # if all_contain_token:
            #     print(f"[_get_per_token_logps] OK: All {input_ids.shape[0]} samples passed to model contain image token {image_token_id_to_check}.")
            # 打印 pixel_values 和 image_grid_thw 形状
        #    print(f"[_get_per_token_logps] pixel_values shape: {pixel_values.shape if pixel_values is not None else 'None'}")
        #    print(f"[_get_per_token_logps] image_grid_thw shape: {image_grid_thw.shape if image_grid_thw is not None else 'None'}")
        logits = model(
            input_ids,
            attention_mask=attention_mask,
            pixel_values=pixel_values,
            image_grid_thw=image_grid_thw,
        ).logits  # (B, L, V)
        logits = logits[
            :, :-1, :
        ]  # (B, L-1, V), exclude the last logit: it corresponds to the next token pred
            
        input_ids = input_ids[
            :, -logits_to_keep:
        ]  # (B, L-1), exclude the first input ID since we don't have logits for it
        # Compute the log probabilities for the input tokens. Use a loop to reduce memory peak.
        logits = logits[:, -logits_to_keep:]
        
        per_token_logps = []
        for logits_row, input_ids_row in zip(logits, input_ids):
            log_probs = logits_row.log_softmax(dim=-1) ### log softmax computation
            token_log_prob = torch.gather(
                log_probs, dim=1, index=input_ids_row.unsqueeze(1)
            ).squeeze(1)
            per_token_logps.append(token_log_prob)
        return torch.stack(per_token_logps)

    # Trainer "prepares" the inputs before calling `compute_loss`. It converts to tensor and move to device.
    # Since we preprocess the data in `compute_loss`, we need to override this method to skip this step.
    def _prepare_inputs(
        self, inputs: dict[str, Union[torch.Tensor, Any]]
    ) -> dict[str, Union[torch.Tensor, Any]]:
        device = self.accelerator.device
        prompts = [x["prompt"] for x in inputs]
        images = [x["image"] for x in inputs]
        prompts_text = [
            maybe_apply_chat_template(example, self.processing_class)["prompt"]
            for example in inputs
        ]
        prompt_inputs = self.processing_class(
            text=copy.deepcopy(prompts_text),
            images=images,
            return_tensors="pt",
            padding=True,
            padding_side="left",
            add_special_tokens=False,
        )
        prompt_ids, prompt_mask = prompt_inputs["input_ids"].to(device), prompt_inputs["attention_mask"].to(device)

        if self.max_prompt_length is not None:
            prompt_ids = prompt_ids[:, -self.max_prompt_length :]
            prompt_mask = prompt_mask[:, -self.max_prompt_length :]
        # # --- Debug ---
        # if self.accelerator.is_main_process:
        #     image_token_id_to_check = 151655 # 或者 self.processing_class.tokenizer.img_token_id
        #     print(f"[DEBUG] after truncation, prompt_ids shape: {prompt_ids.shape}")
        #     print(f"[DEBUG] after truncation, contains image token ({image_token_id_to_check})? {torch.any(prompt_ids == image_token_id_to_check)}")
        #     print(f"[DEBUG] after truncation, prompt_ids[0]: {prompt_ids[0]}") # 打印第一个样本看看
        # # --- End Debug ---
        if self.args.use_vllm:
            # First, have main process load weights if needed
            if self.state.global_step != self._last_loaded_step:
                with unwrap_model_for_generation(
                    self.model,
                    self.accelerator,
                    gather_deepspeed3_params=False,  # TODO: fix this, self.args.ds3_gather_for_generation,
                ) as unwrapped_model:
                    if is_compiled_module(unwrapped_model):
                        state_dict = unwrapped_model._orig_mod.state_dict()
                    else:
                        state_dict = unwrapped_model.state_dict()
                if self.accelerator.is_main_process:
                    llm_model = (
                        self.llm.llm_engine.model_executor.driver_worker.model_runner.model
                    )
                    llm_model.load_weights(state_dict.items())
                self._last_loaded_step = self.state.global_step

            # Generate completions using vLLM: gather all prompts and use them in a single call in the main process
            all_prompts_text = gather_object(prompts_text)
            all_images = gather_object(images)
            # group into pairs
            all_multimodal_inputs = []

            use_naive_loop_sampling = False
            if use_naive_loop_sampling:
                # in this implementation, one sample will repeat `self.num_generations` times
                # it's not a efficient implementation, but safe to keep sampling diversity
                for prompt, image in zip(all_prompts_text, all_images):
                    for _ in range(self.num_generations):
                        all_multimodal_inputs.append({"prompt": prompt, "multi_modal_data": {"image": image}})
                all_completion_ids = [None] * len(all_multimodal_inputs)
                for i in range(self.num_generations):
                    # Get the inputs for the current batch
                    batch_inputs = [all_multimodal_inputs[j] for j in range(i, len(all_multimodal_inputs), self.num_generations)]
                    if self.accelerator.is_main_process:
                        outputs = self.llm.generate(
                            batch_inputs,
                            sampling_params=self.sampling_params,
                            use_tqdm=False,
                            
                        )
                        batch_completion_ids = [out.token_ids for completions in outputs for out in completions.outputs]
                    else:
                        batch_completion_ids = [None] * len(batch_inputs)
                    # Place the results back into their original positions
                    for idx, completion_id in enumerate(batch_completion_ids):
                        all_completion_ids[i + idx * self.num_generations] = completion_id
                # Final completion IDs
                completion_ids = all_completion_ids

            # 2. Refer to TobiasLee's implementation suggestions
            # this is a better implementation for vLLM sampling.
            for prompt, image in zip(all_prompts_text, all_images):
                all_multimodal_inputs.append({"prompt": prompt, "multi_modal_data": {"image": image}})
                
            completion_ids = None #
            generation_time = 0.0
            # Create sampling params with num_generations
            if self.accelerator.is_main_process:
                ########################
                start_gen = time.perf_counter() # start inference
                ########################
                # Clone to avoid modifying original params
                sampling_params = copy.deepcopy(self.sampling_params)
                sampling_params.n = self.num_generations
                # Single generate call with all prompts
                if self.accelerator.is_main_process:
                    outputs = self.llm.generate(
                        all_multimodal_inputs,
                        sampling_params=sampling_params,
                        use_tqdm=False,
                    )
                # Flatten outputs: [prompt1_gen1, prompt1_gen2, ..., prompt2_gen1, prompt2_gen2, ...]
                completion_ids = [out.token_ids for completion in outputs for out in completion.outputs]
                ###################################################################
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                end_gen = time.perf_counter() #Timer Group Inference Stop 
                generation_time = end_gen - start_gen
                ####################################################################
            else:
                completion_ids = [None] * len(all_multimodal_inputs) * self.num_generations
            ####################################################################
            # record inference time for one device
            local_time = torch.tensor([generation_time], device=self.accelerator.device)
            # gather_for_metrics `local_time` tensor
            global_times = self.accelerator.gather_for_metrics(local_time)
            if self.accelerator.is_main_process:
                self._metrics["total_inference_time_main_process"].append(global_times.sum().item())
            ###################################################################
            
            # broadcast and slice
            completion_ids = broadcast_object_list(completion_ids, from_process=0)
            process_slice = slice(
                self.accelerator.process_index * len(prompts) * self.num_generations,
                (self.accelerator.process_index + 1) * len(prompts) * self.num_generations,
            )
            completion_ids = completion_ids[process_slice]

             # --- START: Debug Check After Broadcast and Slice ---
             
            #print(f"[RANK {self.accelerator.process_index} DEBUG] After broadcast & slice:")
            #print(f"  - Type of original completion_ids: {type(completion_ids)}")
            #print(f"  - Number of completion sequences for this rank: {len(completion_ids)}")

            processed_completion_ids = []
            found_locations = []
            # if completion_ids: # Check if the list is not empty
            #     image_token_id_to_check = 151655  # image_token_id for qwen2-vl is 151655
            #     print(f"[RANK {self.accelerator.process_index} DEBUG] Processing completions to remove token {image_token_id_to_check} while keeping list[tuple] structure...")

            #     for idx, completion_tuple in enumerate(completion_ids):
            #         # print(f"  - Original Tuple {idx} (type {type(original_tuple)}): {original_tuple}")
            #         if image_token_id_to_check in completion_tuple:
            #             indices = [i for i, token in enumerate(completion_tuple) if token == image_token_id_to_check]
            #             if indices:
            #                 # location_info = {"seq_idx_local": idx, "indices": indices, "seq_length": len(completion_tuple)}
            #                 # found_locations.append(location_info)
            #                 print(f"  - Found image token in local sequence {idx} at indices: {indices}. Sequence length: {len(completion_tuple)}.")
            #             filtered_list = [self.processing_class.pad_token_id if token_id == image_token_id_to_check else token_id for token_id in completion_tuple]
            #             processed_tuple = tuple(filtered_list)
            #             processed_completion_ids.append(processed_tuple)
            #             # print(f"    -> Filtered Tuple {idx} (len {len(processed_tuple)}): {processed_tuple}")
            #         else:
            #             processed_completion_ids.append(completion_tuple)
            #             # print(f"    -> Kept Original Tuple {idx} (len {len(original_tuple)}): {original_tuple}")

            #     #print(f"[RANK {self.accelerator.process_index} DEBUG] Finished processing completions.")

            # # list[tuple]
            # completion_ids = processed_completion_ids
            # --- END: Debug Check After Broadcast and Slice ---

            # Pad the completions, and concatenate them with the prompts
            completion_ids = [torch.tensor(ids, device=device) for ids in completion_ids]

            completion_ids = pad(
                completion_ids, padding_value=self.processing_class.pad_token_id
            )
            prompt_ids = prompt_ids.repeat_interleave(self.num_generations, dim=0)
            prompt_completion_ids = torch.cat([prompt_ids, completion_ids], dim=1)

            prompt_length = prompt_ids.size(1)
            prompt_ids = prompt_completion_ids[:, :prompt_length]
            completion_ids = prompt_completion_ids[:, prompt_length:]
            prompt_mask = prompt_mask.repeat_interleave(self.num_generations, dim=0)
        else:
            raise ValueError("Only vLLM generation is supported in this version ")
        
        # below are the same with yifan's code
        # Mask everything after the first EOS token
        is_eos = completion_ids == self.processing_class.eos_token_id
        device = self.accelerator.device
        eos_idx = torch.full((is_eos.size(0),), is_eos.size(1), dtype=torch.long, device=device)
        eos_idx[is_eos.any(dim=1)] = is_eos.int().argmax(dim=1)[is_eos.any(dim=1)]
        sequence_indices = torch.arange(is_eos.size(1), device=device).expand(is_eos.size(0), -1)
        completion_mask = (sequence_indices <= eos_idx.unsqueeze(1)).int()

        # Concatenate prompt_mask with completion_mask for logit computation
        attention_mask = torch.cat([prompt_mask, completion_mask], dim=1)  # (B*G, P+C)
        
        # # --- Debug ---
        # if self.accelerator.is_main_process:
        #     print(f"[DEBUG] after truncation, pixel_values shape: {prompt_inputs['pixel_values'].shape}")
        #     print(f"[DEBUG] after truncation, image_grid_thw shape: {prompt_inputs['image_grid_thw'].shape}")
        # # --- End Debug ---
        pixel_values = prompt_inputs["pixel_values"][None].repeat_interleave(self.num_generations, dim=0)
        image_grid_thw = prompt_inputs["image_grid_thw"].repeat_interleave(self.num_generations, dim=0)
        logits_to_keep = completion_ids.size(1)

        with torch.inference_mode():
            if self.ref_model is not None:
                ref_per_token_logps = self._get_per_token_logps(
                    self.ref_model,
                    prompt_completion_ids,
                    attention_mask,
                    pixel_values,
                    image_grid_thw,
                    logits_to_keep,
                )
            else:
                with self.accelerator.unwrap_model(self.model).disable_adapter():
                    ref_per_token_logps = self._get_per_token_logps(
                        self.model,
                        prompt_completion_ids,
                        attention_mask,
                        pixel_values,
                        image_grid_thw,
                        logits_to_keep,
                    )
        # Decode the generated completions
        completions = self.processing_class.batch_decode(
            completion_ids, skip_special_tokens=True
        )
        if is_conversational(inputs[0]):
            completions = [
                [{"role": "assistant", "content": completion}]
                for completion in completions
            ]

        # Compute the rewards
        prompts = [prompt for prompt in prompts for _ in range(self.num_generations)]
        rewards_per_func = torch.zeros(
            len(prompts), len(self.reward_funcs), device=device
        )
        for i, (reward_func, reward_processing_class) in enumerate(
            zip(self.reward_funcs, self.reward_processing_classes)
        ):
            if isinstance(reward_func, PreTrainedModel):
                if is_conversational(inputs[0]):
                    messages = [{"messages": p + c} for p, c in zip(prompts, completions)]
                    texts = [
                        apply_chat_template(x, reward_processing_class)["text"]
                        for x in messages
                    ]
                else:
                    texts = [p + c for p, c in zip(prompts, completions)]
                reward_inputs = reward_processing_class(
                    texts,
                    return_tensors="pt",
                    padding=True,
                    padding_side="right",
                    add_special_tokens=False,
                )
                reward_inputs = super()._prepare_inputs(reward_inputs)
                with torch.inference_mode():
                    rewards_per_func[:, i] = reward_func(**reward_inputs).logits[:, 0]  # Shape (B*G,)
            else:
                ########################################################################################
                if hasattr(reward_func, "reward_type") and reward_func.reward_type == "execution":
                    reward_kwargs = {key: [] for key in inputs[0].keys() if key not in ["prompt", "completion"]}
                    for key in reward_kwargs:
                        for example in inputs:
                            # Repeat each value in the column for `num_generations` times
                            reward_kwargs[key].extend([example[key]] * self.num_generations)
                    # execution reward 
                    exec_reward_list,exec_result_list = reward_func(prompts=prompts, completions=completions, step=self.state.global_step , **reward_kwargs) # completions
                    rewards_per_func[:, i] = torch.tensor(exec_reward_list, dtype=torch.float32, device=device)
                
                elif hasattr(reward_func, "reward_type") and reward_func.reward_type == "accuracy":
                    # ensure there is execution reward
                    if exec_reward_list is None or exec_result_list is None:
                        raise ValueError("No Execution Reward Found before Accuracy Reward!!")
                    
                    # Repeat all input columns (but "prompt" and "completion") to match the number of generations
                    reward_kwargs = {key: [] for key in inputs[0].keys() if key not in ["prompt", "completion"]}
                    for key in reward_kwargs:
                        for example in inputs:
                            # Repeat each value in the column for `num_generations` times
                            reward_kwargs[key].extend([example[key]] * self.num_generations)
                    output_reward_func = reward_func(  # exec_reward list, exec result and QAid
                                      exec_reward_list=exec_reward_list,
                                      exec_result_list=exec_result_list,
                                      step=self.state.global_step,
                                      **reward_kwargs)
                    rewards_per_func[:, i] = torch.tensor(output_reward_func, dtype=torch.float32, device=device)
                #################################################################################################
                else:
                    # Repeat all input columns (but "prompt" and "completion") to match the number of generations
                    reward_kwargs = {
                        key: []
                        for key in inputs[0].keys()
                        if key not in ["prompt", "completion"]
                    }
                    for key in reward_kwargs:
                        for example in inputs:
                            # Repeat each value in the column for `num_generations` times
                            reward_kwargs[key].extend([example[key]] * self.num_generations)
                    output_reward_func = reward_func(
                        prompts=prompts, completions=completions, step=self.state.global_step, **reward_kwargs
                    )
                    rewards_per_func[:, i] = torch.tensor(
                        output_reward_func, dtype=torch.float32, device=device
                    )
        rewards_per_func = gather(rewards_per_func)
        ##################################################
        # Store a clone of the raw, unweighted rewards BEFORE applying weights
        unweighted_rewards_per_func = rewards_per_func.clone()
        if self.reward_weights is not None:
            # Convert weights list to tensor on the correct device
            weights_tensor = torch.tensor(self.reward_weights, dtype=torch.float32, device=device)
            # Perform weighted multiplication using broadcasting
            rewards_per_func = rewards_per_func * weights_tensor
        # (Num_Generation, Num_function) * (N,) -> (Num_Generation, Num_function)
        ##################################################
        
        # Sum the rewards from all reward functions
        rewards = rewards_per_func.sum(dim=1)

        # Compute grouped-wise rewards
        mean_grouped_rewards = rewards.view(-1, self.num_generations).mean(dim=1)
        std_grouped_rewards = rewards.view(-1, self.num_generations).std(dim=1)

        # Normalize the rewards to compute the advantages
        mean_grouped_rewards = mean_grouped_rewards.repeat_interleave(
            self.num_generations, dim=0
        )
        std_grouped_rewards = std_grouped_rewards.repeat_interleave(
            self.num_generations, dim=0
        )
        advantages = (rewards - mean_grouped_rewards) / (std_grouped_rewards + 1e-4)

        # Slice to keep only the local part of the data
        process_slice = slice(
            self.accelerator.process_index * len(prompts),
            (self.accelerator.process_index + 1) * len(prompts),
        )
        advantages = advantages[process_slice]

        # Log the metrics
        reward_per_func = rewards_per_func.mean(0)
        unweighted_reward_per_func = unweighted_rewards_per_func.mean(0) ##
        for i, reward_func in enumerate(self.reward_funcs):
            if isinstance(
                reward_func, nn.Module
            ):  # Module instead of PretrainedModel for compat with compiled models
                reward_func_name = reward_func.config._name_or_path.split("/")[-1]
            else:
                reward_func_name = reward_func.__name__
            self._metrics[f"rewards/weighted_{reward_func_name}"].append(
                reward_per_func[i].item()
            )
            self._metrics[f"rewards/original_{reward_func_name}"].append(unweighted_reward_per_func[i].item()) ##

        self._metrics["reward"].append(rewards.mean().item())
        self._metrics["reward_std"].append(std_grouped_rewards.mean().item())

        return {
            "prompt_ids": prompt_ids,
            "prompt_mask": prompt_mask,
            "completion_ids": completion_ids,
            "completion_mask": completion_mask,
            "ref_per_token_logps": ref_per_token_logps,
            "advantages": advantages,
            "pixel_values": pixel_values,
            "image_grid_thw": image_grid_thw,
        }

    def compute_loss(
        self, model, inputs, return_outputs=False, num_items_in_batch=None
    ):
        if return_outputs:
            raise ValueError("The GRPOTrainer does not support returning outputs")
        # Compute the per-token log probabilities for the model

        prompt_ids, prompt_mask = inputs["prompt_ids"], inputs["prompt_mask"]
        completion_ids, completion_mask = inputs["completion_ids"], inputs["completion_mask"]
        input_ids = torch.cat([prompt_ids, completion_ids], dim=1)
        attention_mask = torch.cat([prompt_mask, completion_mask], dim=1)
        pixel_values = inputs["pixel_values"]
        image_grid_thw = inputs["image_grid_thw"]
        logits_to_keep = completion_ids.size(1)  # we only need to compute the logits for the completion tokens

        per_token_logps = self._get_per_token_logps(
            model,
            input_ids,
            attention_mask,
            pixel_values,
            image_grid_thw,
            logits_to_keep,
        )

        # Compute the KL divergence between the model and the reference model
        ref_per_token_logps = inputs["ref_per_token_logps"]
        per_token_kl = (torch.exp(ref_per_token_logps - per_token_logps)- (ref_per_token_logps - per_token_logps)- 1)

        # x - x.detach() allows for preserving gradients from x
        advantages = inputs["advantages"]
        per_token_loss = torch.exp(per_token_logps - per_token_logps.detach()) * advantages.unsqueeze(1)
        per_token_loss = -(per_token_loss - self.beta * per_token_kl)
        loss = ((per_token_loss * completion_mask).sum(dim=1) / completion_mask.sum(dim=1)).mean()

        # Log the metrics
        completion_length = (
            self.accelerator.gather_for_metrics(completion_mask.sum(1))
            .float()
            .mean()
            .item()
        )
        self._metrics["completion_length"].append(completion_length)

        mean_kl = (
            (per_token_kl * completion_mask).sum(dim=1) / completion_mask.sum(dim=1)
        ).mean()
        self._metrics["kl"].append(
            self.accelerator.gather_for_metrics(mean_kl).mean().item()
        )

        return loss

        
    def log(self, logs: dict[str, float], start_time: Optional[float] = None) -> None:
        metrics = {key: sum(val) / len(val) for key, val in self._metrics.items()}  # average the metrics

        # This method can be called both in training and evaluation. When called in evaluation, the keys in `logs`
        # start with "eval_". We need to add the prefix "eval_" to the keys in `metrics` to match the format.
        if next(iter(logs.keys())).startswith("eval_"):
            metrics = {f"eval_{key}": val for key, val in metrics.items()}

        logs = {**logs, **metrics}
        if version.parse(transformers.__version__) >= version.parse("4.47.0.dev0"):
            super().log(logs, start_time)
        else:  # transformers<=4.46
            super().log(logs)
        self._metrics.clear()