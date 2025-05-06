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

import math
import os
from collections import defaultdict
from io import BytesIO
from typing import Any, Dict, List, Optional, Union

import json
import numpy as np
import torch
from datasets import load_dataset,concatenate_datasets
from jinja2 import Template
from PIL import Image
from PIL.Image import Image as ImageObject
from torch.utils.data import Dataset
from transformers import PreTrainedTokenizer, ProcessorMixin

from ..models.transformers.qwen2_vl import get_rope_index
from . import torch_functional as VF
import yaml

def collate_fn(features: List[Dict[str, Any]]) -> Dict[str, Any]:
    tensors = defaultdict(list)
    non_tensors = defaultdict(list)
    for feature in features:
        for key, value in feature.items():
            if isinstance(value, torch.Tensor):
                tensors[key].append(value)
            else:
                non_tensors[key].append(value)

    for key, value in tensors.items():
        tensors[key] = torch.stack(value, dim=0)

    for key, value in non_tensors.items():
        non_tensors[key] = np.array(value, dtype=object)

    return {**tensors, **non_tensors}


class ImageProcessMixin:
    max_pixels: int
    min_pixels: int

    def process_image(self, image: Union[Dict[str, Any], ImageObject]) -> ImageObject:
        if isinstance(image, dict):
            image = Image.open(BytesIO(image["bytes"]))
        elif isinstance(image, bytes):
            image = Image.open(BytesIO(image))

        if (image.width * image.height) > self.max_pixels:
            resize_factor = math.sqrt(self.max_pixels / (image.width * image.height))
            width, height = int(image.width * resize_factor), int(image.height * resize_factor)
            image = image.resize((width, height))

        if (image.width * image.height) < self.min_pixels:
            resize_factor = math.sqrt(self.min_pixels / (image.width * image.height))
            width, height = int(image.width * resize_factor), int(image.height * resize_factor)
            image = image.resize((width, height))

        if image.mode != "RGB":
            image = image.convert("RGB")

        return image


class RLHFDataset(Dataset, ImageProcessMixin):
    """
    We assume the dataset contains a column that contains prompts and other information
    """

    def __init__(
        self,
        data_path: str,
        tokenizer: PreTrainedTokenizer,
        processor: Optional[ProcessorMixin],
        prompt_key: str = "prompt",
        answer_key: str = "answer",
        image_key: str = "images",
        max_prompt_length: int = 1024,
        truncation: str = "error",
        format_prompt: Optional[str] = None,
        max_pixels: Optional[int] = None,
        min_pixels: Optional[int] = None,
        filter_overlong_prompts: bool = True,
        subtasks: Optional[list[str]] = None, # specific for BLINK dataset and CV-Bench
        dataset_prefix: Optional[str] = None, # specific for BLINK and CV-Bench
        tools_config: Optional[str] = None, # specific for tools
    ):
        self.tokenizer = tokenizer
        self.processor = processor
        self.prompt_key = prompt_key
        self.answer_key = answer_key
        self.image_key = image_key
        self.max_prompt_length = max_prompt_length
        self.truncation = truncation
        self.max_pixels = max_pixels
        self.min_pixels = min_pixels
        self.filter_overlong_prompts = filter_overlong_prompts
        self.data_path = data_path ####
        self.configuration_file = tools_config ####
        
        if "@" in data_path:
            data_path, data_split = data_path.split("@")
        else:
            data_split = "train"
        if not ("BLINK" in data_path or "SAT" in data_path or "CV-Bench" in data_path): # original implementation
            if os.path.isdir(data_path):
                # when we use dataset builder, we should always refer to the train split
                self.dataset = load_dataset("parquet", data_dir=data_path, split="train")
            elif os.path.isfile(data_path):
                self.dataset = load_dataset("parquet", data_files=data_path, split="train")
            else:
                # load remote dataset from huggingface hub
                self.dataset = load_dataset(data_path, split=data_split)
        else:
            if "BLINK" in data_path:
                all_datasets = []
                print(f"loading dataset: {data_path}\n")
                for subtask in subtasks: # because in BLINK there is subtasks(e.g. Counting)
                    blink_ds = load_dataset(f"{data_path}", f"{subtask}", split="val") # e.g. BLINK-Benchmark/BLINK val
                    blink_ds = blink_ds.map(lambda x: {"sub_task": subtask})
                    all_datasets.append(blink_ds)
                    
                blink_ds = concatenate_datasets(all_datasets)
                
                all_subtasks_json = []
                for task in subtasks: # here json file should be in correct path
                    subtask_json_path = f"BLINK_Dataset/{task}/val/{task}_val.json" # only val has ground truth
                    subtask_json_path = os.path.join(dataset_prefix, subtask_json_path)
                    
                    with open(subtask_json_path, 'r') as f: # to obtain the image paths for each QA(saved in json file) 
                        raw_dataset = json.load(f) 
                        subtask_json  = [sample for sample in raw_dataset]
                        
                    all_subtasks_json.extend(subtask_json)

                self.dataset = blink_ds # converted to be consistent with original setting    
                self.all_subtasks_json = all_subtasks_json
                self.dataset_prefix = dataset_prefix

            if "SAT" in data_path:
                # TODO
                print(f"Loading dataset: {data_path}\n")

                dataset_json_path = "SAT_subtasks/SAT_Counting.json" # TODO Better
                full_path = os.path.join(dataset_prefix, dataset_json_path)
                with open(full_path, 'r') as f:
                    raw_dataset = json.load(f)
                self.dataset = raw_dataset  # json format in SAT
                self.dataset_prefix = dataset_prefix

            if "CV-Bench" in data_path:
                pass # TODO

        self.format_prompt = None
        if format_prompt:
            with open(format_prompt, encoding="utf-8") as f:
                self.format_prompt = f.read()

        if self.filter_overlong_prompts:
            self.dataset = self.dataset.filter(self._filter_overlong_prompts, desc="Filtering overlong prompts")

    ###################################################################
    # load selected tooldata from prompt yaml file        
    def _load_tool_data(self, conf_file):
        
        # load config file from path
        with open(conf_file, "r") as stream:
            conf = yaml.safe_load(stream)
        # --- Tool Metadata Filtering Logic ---
        active_tool_names = conf.get("available_tools", []) # Get the list from YAML
        full_toolbox_metadata = conf.get("toolbox_metadata", {})

        # Create a dictionary containing only the metadata for active tools
        filtered_metadata_dict = {
            tool_name: full_toolbox_metadata[tool_name]
            for tool_name in active_tool_names
            if tool_name in full_toolbox_metadata
        }

        # Warn for missing tools
        for tool_name in active_tool_names:
            if tool_name not in full_toolbox_metadata:
                print(f"Warning: Tool '{tool_name}' listed in available_tools but not found in toolbox_metadata.")

        return active_tool_names, filtered_metadata_dict
    ###################################################################
    
    def _build_messages(self, example: Dict[str, Any]) -> List[Dict[str, Any]]:
        prompt_str: str = example[self.prompt_key]
        if ("BLINK" in self.data_path or "SAT" in self.data_path or "CV-Bench" in self.data_path):
            image_paths = example["image_paths"]
            active_tool_names, filtered_metadata_dict = self._load_tool_data(self.configuration_file)
            format_prompt = Template(self.format_prompt.strip())
            prompt_str = format_prompt.render(question=prompt_str,
                                              image_paths=image_paths,
                                              available_tools=active_tool_names,
                                              toolbox_metadata=filtered_metadata_dict,
                                              )
            content_list = []
            for i in range(len(image_paths)+1):
                if i != len(image_paths):
                    content_list.append({"type": "image"})
                else:
                    content_list.append({"type": "text", "text": prompt_str})
            return [{"role": "user", "content": content_list}]
        else:
            if self.format_prompt:
                format_prompt = Template(self.format_prompt.strip())
                prompt_str = format_prompt.render(content=prompt_str)

            if self.image_key in example:
                # https://huggingface.co/docs/transformers/en/tasks/image_text_to_text
                content_list = []
                for i, content in enumerate(prompt_str.split("<image>")):
                    if i != 0:
                        content_list.append({"type": "image"})

                    if content:
                        content_list.append({"type": "text", "text": content})

                return [{"role": "user", "content": content_list}]
            else:
                return [{"role": "user", "content": prompt_str}]

    def _filter_overlong_prompts(self, example: Dict[str, Any]) -> bool:
        messages = self._build_messages(example)
        processing_class = self.processor if self.processor is not None else self.tokenizer
        return (
            len(processing_class.apply_chat_template(messages, add_generation_prompt=True)) <= self.max_prompt_length
        )

    def __len__(self):
        return len(self.dataset)
    
######################################################################
    ### Adapt to `Blink` dataset for post-processing
    ### load multi-images; add <image> tags into prompts; add image_paths for tools usage
    def _blink_format(self, example, json_file):
        # collect Un-None images
        images = [example[k] for k in ['image_1', 'image_2', 'image_3', 'image_4'] if example.get(k) is not None]
        num_images = len(images)

        # add <image> tag into original prompts
        full_prompt = example["prompt"]
        for sample in json_file:
            if sample["idx"] == example["idx"]:
                image_paths = [os.path.join(self.dataset_prefix, img_path) for img_path in sample["image_paths"]]
        answer = example["answer"].strip("()")
        return {
            "images": images,
            "problem": full_prompt,
            "answer": answer,
            "idx": example["idx"],
            "image_paths": image_paths
        }
    def _sat_format(self, example):
        image_paths = [os.path.join(self.dataset_prefix, path) for path in example["images"]]
        images = [Image.open(path) for path in image_paths]
        full_prompt = example["messages"][0]["content"].strip()
        full_prompt = full_prompt.replace("<image> Answer in natural language. ", "")
        answer = example["messages"][1]["content"].strip()
        idx = os.path.splitext(os.path.basename(example["images"][0]))[0]  # image name as index
        
        return {
            "images": images,
            "problem": full_prompt,
            "answer": answer,
            "idx": idx,
            "image_paths" : image_paths
        }
    def _cv_bench_format(self, example):
        # TODO
        pass
######################################################################
    
    def __getitem__(self, index):
        example: dict = self.dataset[index]
        
        ###
        if "BLINK" in self.data_path:
            example = self._blink_format(example, self.all_subtasks_json)
        if "SAT" in self.data_path:
            example = self._sat_format(example)
        if "CV-Bench" in self.data_path:
            pass #TODO
        ###
        
        messages = self._build_messages(example)
        example["message"] = messages # for debug
        
        if self.image_key in example:
            prompt = self.processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
            images = [self.process_image(image) for image in example.pop(self.image_key)]
            model_inputs = self.processor(images, [prompt], add_special_tokens=False, return_tensors="pt")
            input_ids = model_inputs.pop("input_ids")[0]
            attention_mask = model_inputs.pop("attention_mask")[0]
            example["multi_modal_data"] = {"image": images}
            example["multi_modal_inputs"] = dict(model_inputs)
        else:
            prompt = self.tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
            model_inputs = self.tokenizer([prompt], add_special_tokens=False, return_tensors="pt")
            input_ids = model_inputs.pop("input_ids")[0]
            attention_mask = model_inputs.pop("attention_mask")[0]

        if self.processor is not None and self.processor.image_processor.__class__.__name__ == "Qwen2VLImageProcessor":
            # qwen2vl mrope
            position_ids = get_rope_index(
                self.processor,
                input_ids=input_ids,
                image_grid_thw=model_inputs.get("image_grid_thw"),
                attention_mask=attention_mask,
            )  # (3, seq_length)
        else:
            position_ids = torch.clip(attention_mask.cumsum(dim=0) - 1, min=0, max=None)  # (seq_length,)

        input_ids, attention_mask, position_ids = VF.postprocess_data(
            input_ids=input_ids,
            attention_mask=attention_mask,
            position_ids=position_ids,
            max_length=self.max_prompt_length,
            pad_token_id=self.tokenizer.pad_token_id,
            left_pad=True,
            truncation=self.truncation,
        )
        raw_prompt_ids = self.tokenizer.encode(prompt, add_special_tokens=False)
        if len(raw_prompt_ids) > self.max_prompt_length:
            if self.truncation == "left":
                raw_prompt_ids = raw_prompt_ids[-self.max_prompt_length :]
            elif self.truncation == "right":
                raw_prompt_ids = raw_prompt_ids[: self.max_prompt_length]
            elif self.truncation == "error":
                raise RuntimeError(f"Prompt length {len(raw_prompt_ids)} is longer than {self.max_prompt_length}.")

        example["input_ids"] = input_ids
        example["attention_mask"] = attention_mask
        example["position_ids"] = position_ids
        example["raw_prompt_ids"] = raw_prompt_ids
        example["ground_truth"] = example.pop(self.answer_key)
        return example
