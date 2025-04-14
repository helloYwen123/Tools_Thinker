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
# sys.path.insert(0, root_dir)

# External Tools Modules
# from object_detector import Object_Detector_Tool

from datasets import load_dataset, load_from_disk, concatenate_datasets
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
from open_r1.trainer import Qwen2VLGRPOTrainer, Qwen2VLGRPOVLLMTrainerModified
# from src.open_r1.trainer import Qwen2VLGRPOTrainer
from trl import GRPOConfig, GRPOTrainer, ModelConfig, ScriptArguments, TrlParser, get_peft_config
from PIL import Image
import traceback
import yaml,argparse

@dataclass
class GRPOScriptArguments(ScriptArguments):
    """
    Script arguments for the GRPO training script.

    Args:
        reward_funcs (`list[str]`):
            List of reward functions. Possible values: 'accuracy', 'format'.
    """
    reward_weights: list[float] = field(
        default_factory=lambda: [1.0, 1.0, 2.0, 2.0],
        metadata={
            "help": "Weights for the reward functions specified in --reward_funcs, in the *same order*. \
            Example: if --reward_funcs format execution accuracy tool, \
            then weights correspond to [format_weight, execution_weight, accuracy_weight, tool_weight]."
            },
    )
    
    reward_funcs: list[str] = field(
        default_factory=lambda: ["format","execution","accuracy","tool"], #
        metadata={"help": "List of reward functions. Possible values: 'tool', 'format', 'execution, 'accuracy'"},
    )
    
    confile: str = field(
        default=None,
        metadata={
            "help": "relative or absolute path to the configuration file"},
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
#################################################################
#                    Preparation For Execution                  #
#################################################################
#Prepare Function for Code reward
def reliability_guard():
    faulthandler.disable()
    import builtins
    builtins.exit = None
    builtins.quit = None
    import os
    os.kill = None
    os.system = None
    os.remove = None
    os.rmdir = None
    import shutil
    shutil.rmtree = None
    import subprocess
    subprocess.Popen = None
    import sys
    sys.modules["ipdb"] = None

def unsafe_execute(code, timeout, result, log_path):
    def timeout_handler(signum, frame):
        raise TimeoutError("Execution timed out")
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(int(timeout))
    try: # if the code is bugfree
        reliability_guard() # follow human-eval evaluation script
        buffer = StringIO() # save all output when execution
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            # TODO # here add external tool module and can be better
            exec_globals = {
                "final_result": None
            }
            exec(code, exec_globals)  # # python dynamic execution environment
        output_raw = buffer.getvalue() # seems to get all output/print in code execution
        output = exec_globals.get("final_result", None)
        
        reward = 0.0
        if output != None: # OUTPUT exist then reward is 1.0
            success_log_path = os.path.join(log_path, "success_execution.log")
            reward = 1.0 # add parameters to scale
            with open(success_log_path, "a+") as df:
                df.write("\n" + "=" * 30 + " New Completed Execution " + "=" * 30 + "\n")
                df.write("[EXEC CODE]\n")
                df.write(code + "\n")
                df.write("[THE PRINT OUTPUT]\n")
                df.write(output_raw + "\n")
                df.write("[GENERATE VALID FINAL_RESULT]\n")
                df.write(str(output) + "\n")
                df.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
        else:
            debug_log_path = os.path.join(log_path, "bug_exec.log")
            reward = 0.0
            with open(debug_log_path, "a+") as df:
                df.write("\n[None RESULT]\n\n")
                df.write("\n[Successful Execution but Get None RESULT]\n")
                df.write("[EXEC CODE]\n")
                df.write(code + "\n")
                df.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
        result.append((reward, output))
    except Exception as e: # if the code problematic
        debug_log_path = os.path.join(log_path, "bug_exec.log")
        with open(debug_log_path, "a+") as df:
            df.write("\n[Exctuion Failed]\n\n")
            df.write(str(e) + "\n")
            df.write(f"code: \n{code}\n")
            df.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
        result.append((0.0, None))
    finally:
        signal.alarm(0)

def check_correctness(task: dict, log_path, current_time) -> float:
    start_time = time.perf_counter()  # timer start
    evaluation_log_path = os.path.join(log_path, f"evaluation-{task['QAid']}.log")
    # in evaluation includes all cased in reward computation
    # Code extraction,Code Bug and Successfual Execution: Correct(Wrong) result.
    if task["code"] == None:
        with open(evaluation_log_path, "a+") as f:
            f.write(f"------------- {current_time} Code Extraction Failed -------------\n")
            f.write(f"Reward: 0.0\n")
            f.write(f"QAid: {task['QAid']}\n")
            f.write(f"Code: [EMPTY]\n")
            f.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
        result = (0.0, None)  # code reward is 0.0
    else:
        manager = multiprocessing.Manager()
        result = manager.list()
        ########################################################################################
        p = multiprocessing.Process(target=unsafe_execute, args=(task["code"], 60, result, log_path)) 
        # here unsafe execute part could be replaced with communication between Executor Server and Reward function(Evaluator Client)
        ###########################################################################################
        p.start()
        p.join(61)
        if p.is_alive():
            p.kill()
        result = result[0] if result else (0.0, None)
        end_time = time.perf_counter()  # timer stop
        elapsed = end_time - start_time
        with open(evaluation_log_path, "a+") as f:
            f.write(f"------------- {current_time} Execution reward: {result[0]} -------------\n")
            f.write(f"[Reward computation time: {elapsed:.4f} seconds]\n")
            f.write(f"QAid: {task['QAid']}\n")
            f.write(f"Code: \n{task['code']}\n")
            f.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
    return result

async def run_all_checks_async(tasks, log_root_dir, current_time):
    loop = asyncio.get_event_loop()
    rewards = []
    # mp_context = multiprocessing.get_context('spawn')  mp_context=mp_context
    with ProcessPoolExecutor(max_workers=1) as pool:  # max num Processes 
        futures = [
            loop.run_in_executor(pool, check_correctness, task, log_root_dir, current_time)
            for task in tasks
        ]
        rewards = await asyncio.gather(*futures) # keep same sequence as tasks(completions code)
    reward_list = [r for r, _ in rewards] 
    result_list = [res for _, res in rewards]
    return (reward_list, result_list)
##########################################################################
#                          EXECUTION REWARD                              #
##########################################################################

def execution_reward(completions, QAid, step,**kwargs):
    # based on completions type to constuct
    if isinstance(completions[0], str):
        contents = [completion for completion in completions]
    else:
        contents = [completion[0]["content"] for completion in completions]

    def extract_code(completion):
            match = re.search(r"<command>(.*?)</command>", completion, re.DOTALL)
            if match:
                return match.group(1)
            else:
                return None
    
    tasks = []
    for content, id in zip(contents, QAid):
        code = extract_code(content)
        tasks.append({
            "code": code,
            "QAid": id
        })
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_root_dir = os.path.join(f"{root_dir}/A+M_split_logs/Execution", f"step_{step}-{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
    
    reward_result = asyncio.run(run_all_checks_async(tasks, log_root_dir, current_time))
    return reward_result

execution_reward.reward_type = "execution"

####################################################################
#                           ACCURACY REWARD                        #
####################################################################
def accuracy_reward(exec_reward_list, exec_result_list, step, solution, QAid, **kwargs):
    """
    """
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_root_dir = os.path.join(f"{root_dir}/A+M_split_logs/Accuracy", f"step_{step}-{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
    rewards = []
    for exec_r, result, sol, id in zip(exec_reward_list, exec_result_list, solution, QAid):
        reward = 0.0
        acc_log_path = os.path.join(log_root_dir, f"accuracy-{id}.log")
        if exec_r == 0:
            with open(acc_log_path, "a") as f:
                f.write(f"\n[QAid]{id}\n")
                f.write("\n[EXECUTION EXCEPTION]\n\n")
        else:
            try:
                # try to verify symbolic calculation
                parsed_result = parse(result)
                parsed_solution = parse(sol)
                if float(verify(parsed_result, parsed_solution)) > 0:
                    reward = 1.0
                    with open(acc_log_path, "a") as f:
                        f.write(f"\n[QAid]{id}\n")
                        f.write("\n[Verification Correct Result]\n\n")
            except Exception:
                pass

            if result == sol or result == sol.lower():
                reward = 1.0
                with open(acc_log_path, "a") as f:
                    f.write(f"\n[QAid]{id}\n")
                    f.write("\n[Correct Result]\n\n")
            else:
                with open(acc_log_path, "a") as f:
                    f.write(f"\n[QAid]{id}\n")
                    f.write("\n[Wrong Result]\n\n")
        rewards.append(reward)
    return rewards
accuracy_reward.reward_type = "accuracy"

####################################################################
#                            FORMAT REWARD                         #
####################################################################
def format_reward(completions,step, **kwargs):
    """Reward function that checks if the completion has a specific format."""
    pattern = r"(?s)<command>(?!\s*\bfinal_result\b).*?\bfinal_result\b\s*=.*?</command>"  # TODO - Done
    if isinstance(completions[0],str):
        completion_contents = [completion for completion in completions]
    else:
        completion_contents = [completion[0]["content"] for completion in completions]
    matches = [re.fullmatch(pattern, content, re.DOTALL) for content in completion_contents]
    rewards = [1.0 if match else 0.0 for match in matches]
    
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_root_dir = os.path.join(f"{root_dir}/A+M_split_logs/Format", f"step_{step}-{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
    format_log_path = os.path.join(log_root_dir, f"format-{id}.log")
    with open(format_log_path, "a+") as f:
        for i, (content, reward) in enumerate(zip(completion_contents, rewards)):
            f.write(f"--- Completion {i+1} ---\n")
            f.write(content + "\n")
            f.write(f"Reward: {reward}\n\n")
    return rewards
#####################################################################

####################################################################
#                         Tool Usage REWARD                        #
####################################################################
import ast

def tool_usage_reward(completions, QAid, step , **kwargs):
    """
    check whether the generated code containing tool execution
    """
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_root_dir = os.path.join(f"{root_dir}/A+M_split_logs/Tools_usage", f"step_{step}-{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
    rewards = []
    if isinstance(completions[0],str):
        contents = [completion for completion in completions]
    else:
        contents = [completion[0]["content"] for completion in completions]
        
    def extract_code(completion):
        match = re.search(r"<command>(.*?)</command>", completion, re.DOTALL)
        if match:
            return match.group(1)  # TODO
        else:
            raise ValueError("No Python code block found in completion.")
        
    for content, id in zip(contents, QAid):
        reward = -1.0
        tool_log_path = os.path.join(log_root_dir, f"toolusage-{id}.log")
        try:
            execute_found = False
            code = extract_code(content)
            tree = ast.parse(code) # Abstract Syntax Tree
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    #  tool.execute or tool_class.execute
                    if isinstance(node.func, ast.Attribute):
                        if node.func.attr == "execute":
                            reward = 1.0
                            execute_found = True
                            break # found execute() calling
            with open(tool_log_path, "a+") as f:
                f.write(f"\n[QAid]{id}\n")
                if execute_found:
                    f.write("\n[Code Includes Tools Usage]\n")
                else:
                    f.write("\n[Code does not include Tools Usage]\n")
                f.write(f"code: \n{code}")
                f.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
        except Exception as e:
            with open(tool_log_path, "a+") as f:
                f.write(f"\n[QAid]{id}\n")
                f.write("\n[Code Extraction Failed or Parse Failed]\n\n")
                f.write(str(e) + "\n")
                f.write(f"\nCompletion Content: \n{content}")
                f.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
                
        rewards.append(reward)
    return rewards
####################################################################
reward_funcs_registry = {
    "execution": execution_reward, # note here sequency
    "accuracy": accuracy_reward,
    "format": format_reward, # format reward
    "tool": tool_usage_reward
}
#####################################################################

########global asyncio to avoid frequently open-close#######
# import asyncio
# try:
#     global_loop = asyncio.get_event_loop()
# except RuntimeError:
#     global_loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(global_loop)
############################################################

######################MAIN############################
def main(script_args, training_args, model_args,conf):
    # Get reward functions
    reward_funcs = [reward_funcs_registry[func] for func in script_args.reward_funcs]
    
    # Check if the model is a base model
    base_model_prompt = False
    if model_args.model_name_or_path.split("/")[-1] == "Qwen2-VL-2B" or "Base" in model_args.model_name_or_path:
        base_model_prompt = True
    
    PROMPT_TEMPLATE = conf.get("prompt_template")
    # for Blink Dataset
    def make_conversation_sat(example, prefix,
                        available_tools_str: str,
                        filtered_metadata_str: str,
                        base_model_prompt=False):
        # get answer
        answer = example["messages"][1]["content"].strip()
        image_paths = [os.path.join(prefix, img_path) for img_path in example["images"]]
        images = [Image.open(path) for path in image_paths]
        idx = os.path.splitext(os.path.basename(example["images"][0]))[0] # image name as index
        
         # Format the final prompt text using the provided strings
        formatted_question_part = PROMPT_TEMPLATE.format(
        question=example["messages"][0]["content"].strip(),
        image_paths=",".join(image_paths),
        available_tools=available_tools_str,        # Use the pre-formatted string
        toolbox_metadata=filtered_metadata_str      # Use the filtered metadata string
        )

        if base_model_prompt:
            prompt = f"""A conversation between User and Assistant. 
            The user asks a question about the image, and the Assistant solves it. 
            The assistant first thinks about the reasoning process in the mind and then provides the user with the answer.
            \nUser: {formatted_question_part} \nAssistant: <command>"""
            
            image_paths = [os.path.join(prefix, img_path) for img_path in example["images"]]
            images = []
            images = [Image.open(path) for path in image_paths]
            for img in images:
                try:
                    # Ensure minimum dimensions of 28 pixels
                    w, h = img.size
                    if w < 28 or h < 28:
                    # Calculate new dimensions maintaining aspect ratio
                        if w < h:
                            new_w = 28
                            new_h = int(h * (28/w))
                        else:
                            new_h = 28
                            new_w = int(w * (28/h))
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                except:
                    pass
                images.append(img)
            message_content = [ *({'type': 'image', 'text': None} for _ in range(len(example["images"])))]
            message_content.append({
                "type": "text" , "text": "<image>" + prompt
            })
            idx = example["idx"]
            return {"image": images, # images
                "image_path": image_paths,
                "prompt": message_content,
                "solution": answer,  ###
                "QAid": idx
            }
        else:
            image_paths = [os.path.join(prefix, img_path) for img_path in example["images"]]
            images = [Image.open(path) for path in image_paths]
            message_content = [*({'type': 'image', 'text': None} for _ in range(len(example["images"])))]
            message_content.append({
                            "type": "text",
                            "text": formatted_question_part
                        })
            
            return {"image": images, # images 
                "image_path": image_paths,
                "prompt": [
                    {
                        "role": "user",
                        "content": message_content,
                    },
                ],
                "solution": answer, ###
                "QAid": idx
            }
    # load selected tooldata from prompt yaml file        
    def load_tool_data(conf):
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

        # indent=2 makes it readable
        filtered_metadata_str = json.dumps(filtered_metadata_dict, indent=2)

        available_tools_str = ", ".join(active_tool_names)

        return available_tools_str, filtered_metadata_str

    #################### Data Loading Start ####################

    dataset_prefix = "/nfs/data8/liao/wxie/SAT" #"/home/stud/wxie/"

    # SAT Dataloader
    dataset = {}
    all_samples = []
    
    dataset_path = f"filtered_output_file.json"

    full_path = os.path.join(dataset_prefix, dataset_path)
    with open(full_path, 'r') as f:
        raw_dataset = json.load(f)
        available_tools_str, filtered_metadata_str = load_tool_data(conf=conf)
        processed_dataset = [make_conversation_sat(sample, dataset_prefix, available_tools_str, filtered_metadata_str,base_model_prompt) for sample in raw_dataset]
        all_samples.extend(processed_dataset)

    dataset = {"train": all_samples}

    # test template and arg
    # save_path = "processed_dataset.json"
    # with open(save_path, "w") as f:
    #     json.dump(dataset["train"], f, indent=4, ensure_ascii=False)

    trainer_cls = Qwen2VLGRPOTrainer if not training_args.use_vllm else Qwen2VLGRPOVLLMTrainerModified


    # Initialize the GRPO trainer
    trainer = trainer_cls(
        model=model_args.model_name_or_path,
        reward_funcs=reward_funcs,
        args=training_args,
        train_dataset=dataset[script_args.dataset_train_split],
        eval_dataset=dataset[script_args.dataset_test_split] if training_args.eval_strategy != "no" else None,
        peft_config=get_peft_config(model_args),
        attn_implementation=model_args.attn_implementation,
        torch_dtype = model_args.torch_dtype,  # Debug: origianlly parameters can not passed
        reward_weights = script_args.reward_weights,
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

    # global_loop.close()  # close Global loop for `Asyncio` approach

if __name__ == "__main__":
    # Debug for sub-process CUDA issue
    # try:
    #     multiprocessing.set_start_method('spawn', force=True)
    #     print("Set multiprocessing start method to 'spawn'")
    # except RuntimeError:
    #     print("Multiprocessing context already set.")
    #     pass

    parser = TrlParser((GRPOScriptArguments, GRPOConfig, ModelConfig))
    script_args, training_args, model_args = parser.parse_args_and_config()
    print("Parsed training_args:", training_args)
    #print("Parsed model_args:", model_args)
   
    configuration_file = script_args.confile
    with open(configuration_file, "r") as stream:
        conf = yaml.safe_load(stream)
    main(script_args, training_args, model_args, conf)