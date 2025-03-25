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

import sys
import time
import os
import re
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
import cv2
import numpy as np
#### free resource after training
import gc
import torch
import shutil
import faulthandler
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor , as_completed
import signal
import runpy
from math_verify import parse, verify
import asyncio
import subprocess
from io import StringIO
import contextlib
import signal
import json
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))))
sys.path.insert(0, root_dir)

#External Tools Modules
from tools.object_detector.tool import Object_Detector_Tool

from datasets import load_dataset, load_from_disk, concatenate_datasets
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
from src.open_r1.trainer import Qwen2VLGRPOTrainer
from trl import GRPOConfig, GRPOTrainer, ModelConfig, ScriptArguments, TrlParser, get_peft_config
from PIL import Image
import traceback

@dataclass
class GRPOScriptArguments(ScriptArguments):
    """
    Script arguments for the GRPO training script.

    Args:
        reward_funcs (`list[str]`):
            List of reward functions. Possible values: 'accuracy', 'format'.
    """
    reward_funcs: list[str] = field(
        default_factory=lambda: ["code","format"], #########记得加回来code
        metadata={"help": "List of reward functions. Possible values: 'code', 'format'"},
    )
    max_pixels: Optional[int] = field(
        default=12845056,
        metadata={"help": "Maximum number of pixels for the image"},
    )
    min_pixels: Optional[int] = field(
        default=3136,
        metadata={"help": "Minimum number of pixels for the image"},
    )
    freeze_llm: bool = field(
        default=False,
        metadata={"help": "Whether to freeze the LLM parameters during training"},
    )
    freeze_vision: bool = field(
        default=False,
        metadata={"help": "Whether to freeze the vision model parameters during training"},
    ) 
###########################################################
#Prepare Function for Code reward

####################################################################
##################CODE ACCURACY and EXECUTION REWARD################
#Asyncio#
def code_exec_acc_reward(completions, solution, **kwargs):
    """
    running code snippets in completions and if result is correct return the rewards.
    If an error occurs during execution, return "0".
    Use asyncio to automatically create and manage event loops.
    """
    if isinstance(completions[0],str):
        contents = [completion for completion in completions]
    else:
        contents = [completion[0]["content"] for completion in completions]
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_dir_path = os.path.join(root_dir, "src/open_r1_multimodal/DEBUGlogs")
    #log_dir_path = os.path.join(root_dir, "src/open_r1_multimodal/Trainlogs")
    os.makedirs(log_dir_path, exist_ok=True)
    ### debug subprocess 
    def run_async_from_sync(coro):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # No loop exists
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        if loop.is_closed():
            # Previously closed loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        return loop.run_until_complete(coro)
    
    def extract_code(completion):
        match = re.search(r"<command>(.*?)</command>", completion , re.DOTALL)
        if match:
            extracted_code = match.group(1).strip()
            return extracted_code
        else:
            return None
#     api_methods = { # python environment in subprocess is isolated from mainprocess
#     "object_detector":  ""# must import one by one to keep more robust
# # """
# # import sys
# # import os
# # import time
# # import torch
# # from transformers import pipeline

# # from tools.base import BaseTool
# # from PIL import Image, ImageOps
# # import os
# # import sys
# # import warnings
# # """
# }
    async def run_all_codes(contents, solutions, log_dir_path, current_time):
        """
        Asynchronously run multiple code snippets.
        """
        sema = asyncio.Semaphore(8)  # max n ubprocess
        
        tasks = []
        for content, sol in zip(contents, solutions):
            async def limited_task(content=content, sol=sol):
                extracted_code = extract_code(content)  
                if extracted_code is None:
                    log_path = os.path.join(log_dir_path ,f"{current_time}-evaluation.log")
                    with open(log_path, "w") as f:
                        f.write(f"------------- {current_time} Extract Code Error -------------\n")
                        f.write(f"\nSolution: {solution}\n")
                    return 0.0

                async with sema:
                    code_to_run = (
                        #f"{api_methods['object_detector']}\n" # no need maybe
                        f"{extracted_code}\n"
                        "print('<final_result>', final_result)"
                        )
                    return await run_code_async(code_to_run, sol, log_dir_path,current_time, 120) ## would be better
            tasks.append(limited_task())
        return await asyncio.gather(*tasks)
    
    async def run_code_async(code, solution, log_dir_path, current_time, exec_timeout: int=10) -> float:
        """
        Run a code snippet asynchronously and evaluate the result.
        """
        try:
            # proc = await asyncio.create_subprocess_exec(
            #     'python3', '-c', code,
            #     stdout=asyncio.subprocess.PIPE,
            #     stderr=asyncio.subprocess.PIPE,
            # )
            python_exec = sys.executable
            # print("Python Exec Path:", python_exec)
            proc = await asyncio.create_subprocess_exec(
                python_exec, '-c', code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=exec_timeout)
            if proc.returncode != 0:
                log_path = os.path.join(log_dir_path ,f"{current_time}-evaluation.log")
                with open(log_path, "w") as f:
                    f.write(f"------------- {current_time} Execution Error: {proc.returncode} -------------\n")
                    f.write(f"Error in code execution: \n{stderr.decode().strip()}\n")
                    f.write(f"\nCode: {code}\n\n")
                    f.write(f"\nSolution: {solution}\n")
                return 0.0
            output_raw = stdout.decode().strip()
        except Exception as e:
            log_path = os.path.join(log_dir_path ,f"{current_time}-evaluation.log")
            with open(log_path, "w") as f:
                f.write(f"------------- {current_time} Exception in creating subproess -------------\n")
                f.write(f"Exception: in creating subproess \n{str(e)}\n")
                f.write(f"Code: {code}\n\n")
                f.write(f"Solution: {solution}\n")
            return 0.0
        
        output = None
        
        try:
            for line in output_raw.splitlines():
                if line.startswith("<final_result>"):
                    output = line[len("<final_result>"):].strip()
                    break
        except Exception as e:
            log_path = os.path.join(log_dir_path, f"{current_time}-evaluation.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "w") as f:
                f.write(f"------------- {current_time} Exception in extract final result-------------\n")
                f.write(f"Exception in extract final result: \n{str(e)}\n")
                f.write(f"Code: {code}\n\n")
                f.write(f"Solution: {solution}\n")
            return 0.0
            
        reward = 0.0
        # try to parse the output and solution to do symbolic verification
        try:
            answer = parse(output) # follow Visual Thinker accuracy
            sol_parsed = parse(solution)
            if float(verify(answer, sol_parsed)) > 0:
                reward = 1.0
        except Exception:
            pass

        # 
        if reward == 0.0:
            # get Ground Truth from solution
            ground_truth = solution
            student_answer = output
            if student_answer == ground_truth:
                reward = 1.0

        log_path = os.path.join(log_dir_path, f"{current_time}-evaluation.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write(f"------------- {current_time} Sucessful Execution; Reward: {reward} -------------\n")
            f.write("Traceback:\n")
            f.write(traceback.format_exc())
            f.write(f"Code: {code}\n\n")
            f.write(f"Final Result: {output}\n\n")
            f.write(f"Solution: {solution}\n")
        return reward
    
  
    return run_async_from_sync(run_all_codes(contents=contents,solutions=solution, log_dir_path=log_dir_path, current_time=current_time))

####################################################################
#############################FORMAT REWARD##########################
def format_reward(completions, **kwargs):
    """Reward function that checks if the completion has a specific format."""
    pattern = r"<command>.*?</command>"
    if isinstance(completions[0],str):
        completion_contents = [completion for completion in completions]
    else:
        completion_contents = [completion[0]["content"] for completion in completions]
    matches = [re.fullmatch(pattern, content, re.DOTALL) for content in completion_contents]
    return [1.0 if match else 0.0 for match in matches]
####################################################################
####################################################################

reward_funcs_registry = {
    "code": code_exec_acc_reward, # execution and accuracy reward
    "format": format_reward # format reward
}

######################################################
######################MAIN############################
def main(script_args, training_args, model_args):
    # Get reward functions
    reward_funcs = [reward_funcs_registry[func] for func in script_args.reward_funcs]
    
    # Check if the model is a base model
    base_model_prompt = False
    if model_args.model_name_or_path.split("/")[-1] == "Qwen2-VL-2B" or "Base" in model_args.model_name_or_path:
        base_model_prompt = True
    
    toolbox_metadata = {
    "Object_Detector_Tool":{ 
            "tool_module_name": "object_detector", # a little modify
            "tool_class_name":"Object_Detector_Tool",
            "tool_description":"A tool that detects objects in an image using the Grounding DINO model and saves individual object images with empty padding.",
            "tool_version":"1.0.0",
            "input_types":{
                "image": "str - The path to the image file.",
                "labels": "list - A list of object labels to detect.",
                "threshold": "float - The confidence threshold for detection (default: 0.35).",
                "model_size": "str - The size of the model to use ('tiny' or 'base', default: 'tiny').",
                "padding": "int - The number of pixels to add as empty padding around detected objects (default: 20)."
            },
            "output_type":"list - A list of detected objects dictionaries with ('label';'confidence score';'box';'saved_image_path')keys and their corresponding values",
            "demo_commands":[
                {
                    "command": 'execution = Object_Detector_Tool.execute(image="path/to/image.png", labels=["baseball", "basket"])', # little modify
                    "description": "Detect baseball and basket in an image, save the detected objects with default empty padding, and return their paths."
                },
                {
                    "command": 'execution = Object_Detector_Tool.execute(image="path/to/image.png", labels=["car", "person"], threshold=0.5, model_size="base", padding=15)',
                    "description": "Detect car and person in an image using the base model, save the detected objects with 15 pixels of empty padding, and return their paths."
                }
            ],
            "user_metadata":{
                "limitation": "The model may not always detect objects accurately, and its performance can vary depending on the input image and the associated labels. It typically struggles with detecting small objects, objects that are uncommon, or objects with limited or specific attributes. For improved accuracy or better detection in certain situations, consider using supplementary tools or image processing techniques to provide additional information for verification."
            }
    }
}
    available_tools = ["Object_Detector_Tool"]
    
    PROMPT_TEMPLATE = """
\n Write a Python program to answer the question related to images : {question}.
Enclose the generated code and comments in <command> </command> tags,
i.e. <command> generated python code </command>.
You can include your thoughts on the code and analysis about how to solve the problem as comments between code line.
You need to use the following available tools, which are very helpful for you.
\n Available Tools: {available_tools}
\n Tools Metadata: {toolbox_metadata}
\n In each tool module folder, there is a `python` script `tool.py` containing the class that implements the tool logic.
\n Rules:
\n1.The command MUST be valid Python code.
\n2.If listed available tools are insufficient to obtain the answer, you can use functions from Python's standard library as needed.
\n3.Use the exact parameter names as specified in the tool's input_types.
\n4.If you need, please directly use the PATHs of images: {image_paths}, which are related to Question
\n5.Always make sure to define variables and functions before using them to keep your Python code syntactically correct
\n6.Ensure that the code execution yields a result that directly answers the question.
\n Note:
\nYou must put your code and your thought comments within the tag <command> </command>.
Please assign the final answer to a variable named "final_result".
If needed, please add the following in the libheader: from <tool_module_name>.tool import <tool_class_name>.
please remember to replace <tool_module_name> and <tool_class_name> with their actual names.
"""
    # for Blink Dataset
    def make_conversation_sat(example, prefix, base_model_prompt=False):
        answer_key = example["answer"].strip("()")
        # Answer Index Map
        index_map = {chr(65 + i): i for i in range(len(example["choices"]))}
        # Get Answer
        answer = example["choices"][index_map[answer_key]]
        if base_model_prompt:
            image_paths = [os.path.join(prefix, img_path) for img_path in example["image_paths"]]
            images = [Image.open(path) for path in image_paths ]
           
            prompt = f"""A conversation between User and Assistant. 
            The user asks a question about the image, and the Assistant solves it. 
            The assistant first thinks about the reasoning process in the mind and then provides the user with the answer.
            \nUser: {PROMPT_TEMPLATE.format(question=example["question"],
                                            image_paths = ", ".join(image_paths),
                                            available_tools=available_tools,
                                            toolbox_metadata = toolbox_metadata
                                            )} \nAssistant: <command>"""
            message_content = [ {"type": "image"} for _ in images ]
            message_content.append({
                "type": "text" , "text": "<image>" + prompt
            })
            return {"image": images,
                "prompt": message_content,
                "solution":  answer,  ###
            }
        else:
            image_paths = [os.path.join(prefix, img_path) for img_path in example["image_paths"]]
            images = [Image.open(path) for path in image_paths ]
            message_content = [ {"type": "image"} for _ in images ]
            message_content.append({
                            "type": "text",
                            "text": PROMPT_TEMPLATE.format(
                                question=example["question"],
                                image_paths=", ".join(image_paths),  
                                available_tools=available_tools,
                                toolbox_metadata=toolbox_metadata
                            )
                        })
            return {"image": images,
                "image_path": image_paths,
                "prompt": [
                    {
                        "role": "user",
                        "content": message_content,
                    },
                ],
                "solution":  answer,  ###
            }
            
    dataset_prefix = "/home/stud/wxie/"
    dataset_path = "BLINK_Dataset/Counting/val/Counting_val.json"
    
    # load json file 
    with open(dataset_prefix + dataset_path, 'r') as f:
        dataset = json.load(f)

    dataset = [make_conversation_sat(sample, base_model_prompt, dataset_prefix) for sample in dataset]
    dataset = {'train': dataset} #####

    
    # save_path = "processed_dataset.json"
    # with open(save_path, "w") as f:
    #     json.dump(dataset["train"], f, indent=4, ensure_ascii=False)
        
    trainer_cls = Qwen2VLGRPOTrainer

    # Initialize the GRPO trainer
    trainer = trainer_cls(
        model=model_args.model_name_or_path,
        reward_funcs=reward_funcs,
        args=training_args,
        train_dataset=dataset[script_args.dataset_train_split],
        eval_dataset=dataset[script_args.dataset_test_split] if training_args.eval_strategy != "no" else None,
        peft_config=get_peft_config(model_args),
        attn_implementation=model_args.attn_implementation,
        max_pixels=script_args.max_pixels,
        min_pixels=script_args.min_pixels,
    )
    
    if script_args.freeze_vision:
        trainer.model.visual.requires_grad_ = False
    elif script_args.freeze_llm:
        trainer.model.model.requires_grad_ = False
    # Train and push the model to the Hub
    trainer.train()

    # Save and push to hub
    trainer.save_model(training_args.output_dir)
    if training_args.push_to_hub:
        trainer.push_to_hub(dataset_name=script_args.dataset_name)
    
    
if __name__ == "__main__":
    parser = TrlParser((GRPOScriptArguments, GRPOConfig, ModelConfig))
    script_args, training_args, model_args = parser.parse_args_and_config()
    main(script_args, training_args, model_args)
    # gc.collect()
    # for i in range(torch.cuda.device_count()):
    #     with torch.cuda.device(i):
    #         torch.cuda.empty_cache()
        