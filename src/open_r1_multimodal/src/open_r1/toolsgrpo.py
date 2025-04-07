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
    confile: str = field(
        default=None,
        metadata={
            "help": "relative or absolute path to the configuration file"},
    )
    reward_funcs: list[str] = field(
        default_factory=lambda: ["format","execution","accuracy","tool"], #
        metadata={"help": "List of reward functions. Possible values: 'tool', 'format', 'execution, 'accuracy'"},
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
            debug_log_path = os.path.join(log_path, "debug_exec.log")
            with open(debug_log_path, "a+") as df:
                df.write("\n" + "=" * 30 + " New Completed Execution " + "=" * 30 + "\n")
                df.write("\n[Successful Execution but Get None RESULT]\n")
                df.write("[EXEC CODE]\n")
                df.write(code + "\n")
                df.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
        result.append((reward, output))
    except Exception as e: # if the code problematic
        debug_log_path = os.path.join(log_path, "bug_exec.log")
        with open(debug_log_path, "a+") as df:
            df.write("\n[EXECUTION EXCEPTION]\n\n")
            df.write(str(e) + "\n")
            df.write(f"code: \n{code}\n")
            df.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
        result.append((0.0, None))
    finally:
        signal.alarm(0)

def check_correctness(task: dict, log_path, current_time) -> float:
    start_time = time.perf_counter()  # timer start
    evaluation_log_path = os.path.join(log_path, f"evaluation-{task['QAid']}.log")  # in evaluation includes all cased in reward computation
                                                    # Code extraction,Code Bug and Successfual Execution: Correct(Wrong) result.
    if task["code"] == None:  # 
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
    with ProcessPoolExecutor(max_workers=4) as pool:  # max num Processes 
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

def execution_reward(completions, QAid,**kwargs):
    # based on completions type to constuct
    if isinstance(completions[0], str):
        contents = [completion for completion in completions]
    else:
        contents = [completion[0]["content"] for completion in completions]

    def extract_code(completion):
        match = re.fullmatch(r"<command>(.*?)</command>", completion.strip(), re.DOTALL)
        if match:
            return match.group(1).strip()
        else:
            raise ValueError("No Command Tag Found!!")
    
    tasks = []
    for content, id in zip(contents, QAid):
        try:
            code = extract_code(content)
        except Exception:
            code = None
        tasks.append({
            "code": code,
            "QAid": id
        })
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_root_dir = os.path.join(f"{root_dir}/A+M_split_logs/Execution", f"{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
    
    reward_result = asyncio.run(run_all_checks_async(tasks, log_root_dir, current_time))
    return reward_result

execution_reward.reward_type = "execution"

####################################################################
#                           ACCURACY REWARD                        #
####################################################################
def accuracy_reward(exec_reward_list, exec_result_list, solution, QAid, **kwargs):
    """
    """
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_root_dir = os.path.join(f"{root_dir}/A+M_split_logs/Accuracy", f"{current_time}-logs")
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
                    reward = 5.0
                    with open(acc_log_path, "a") as f:
                        f.write(f"\n[QAid]{id}\n")
                        f.write("\n[Verification Correct Result]\n\n")
            except Exception:
                pass
            
            if result == sol or result == sol.lower():
                reward = 2.0
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
def format_reward(completions, **kwargs):
    """Reward function that checks if the completion has a specific format."""
    pattern = r"<command>.*?</command>"
    if isinstance(completions[0],str):
        completion_contents = [completion for completion in completions]
    else:
        completion_contents = [completion[0]["content"] for completion in completions]
    matches = [re.fullmatch(pattern, content, re.DOTALL) for content in completion_contents]
    return [1.0 if match else 0.0 for match in matches]
#####################################################################

####################################################################
#                         Tool Usage REWARD                        #
####################################################################

import ast

def tool_usage_reward(completions, QAid , **kwargs):
    """
    check whether the generated code containing tool execution
    """
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_root_dir = os.path.join(f"{root_dir}/A+M_split_logs/Tools_usage", f"{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
    rewards = []
    if isinstance(completions[0],str):
        contents = [completion for completion in completions]
    else:
        contents = [completion[0]["content"] for completion in completions]
        
    def extract_code(completion):
        match = re.fullmatch(r"<command>(.*?)</command>", completion.strip(), re.DOTALL)
        if match:
            return match.group(1).strip()
        else:
            raise ValueError("No Command Tag Found!!")
    reward = 0.0
    for content, id in zip(contents, QAid):
        tool_log_path = os.path.join(log_root_dir, f"toolusage-{id}.log")
        try:
            code = extract_code(content)
            tree = ast.parse(code) # Abstract Syntax Tree
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    #  tool.execute or tool_class.execute
                    if isinstance(node.func, ast.Attribute):
                        if node.func.attr == "execute":
                            reward = 2.0
                            with open(tool_log_path, "a+") as f:
                                f.write(f"\n[QAid]{id}\n")
                                f.write("\n[Code Includes Tools Usage]\n")
                                f.write(f"code: \n{code}")
                                f.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
                            break # found execute() calling
        except Exception:
            with open(tool_log_path, "a+") as f:
                f.write(f"\n[QAid]{id}\n")
                f.write("\n[Code Extraction Failed or Parse Failed]\n\n")
        rewards.append(reward)
    return rewards
####################################################################
reward_funcs_registry = {
    #"code": code_exec_acc_reward, # execution and accuracy reward
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
    
    toolbox_metadata = conf.get("toolbox_metadata")
    available_tools = conf.get("available_tools")
    
    PROMPT_TEMPLATE = conf.get("prompt_template")
    # for Blink Dataset
    def make_conversation_sat(example, prefix, base_model_prompt=False):
        # get answer
        answer = example["answer"].strip("()")
        
        if base_model_prompt:
            image_paths = [os.path.join(prefix, img_path) for img_path in example["image_paths"]]
            images = [Image.open(path) for path in image_paths ]
           
            prompt = f"""A conversation between User and Assistant. 
            The user asks a question about the image, and the Assistant solves it. 
            The assistant first thinks about the reasoning process in the mind and then provides the user with the answer.
            \nUser: {PROMPT_TEMPLATE.format(question=example["prompt"],
                                            image_paths = ", ".join(image_paths),
                                            available_tools=available_tools,
                                            toolbox_metadata = toolbox_metadata
                                            )} \nAssistant: <command>"""
            message_content = [ {"type": "image"} for _ in images ]
            message_content.append({
                "type": "text" , "text": "<image>" + prompt
            })
            idx = example["idx"]
            return {"image": images, # images
                "prompt": message_content,
                "solution": answer,  ###
                "QAid": idx
            }
        else:
            image_paths = [os.path.join(prefix, img_path) for img_path in example["image_paths"]]
            images = [Image.open(path) for path in image_paths ]
            message_content = [ {"type": "image"} for _ in images ]
            message_content.append({
                            "type": "text",
                            "text": PROMPT_TEMPLATE.format(
                                question=example["prompt"],
                                image_paths=", ".join(image_paths),  
                                available_tools=available_tools,
                                toolbox_metadata=toolbox_metadata
                            )
                        })
            idx = example["idx"] 
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

    dataset_prefix = "/home/stud/wxie/"
    dataset_path = "BLINK_Dataset/Counting/val/Counting_val.json"
    
    # load json file 
    with open(dataset_prefix + dataset_path, 'r') as f:
        dataset = json.load(f)

    dataset = [make_conversation_sat(sample, dataset_prefix, base_model_prompt) for sample in dataset]
    dataset = {'train': dataset} #####

    # test template and arg
    # save_path = "processed_dataset.json"
    # with open(save_path, "w") as f:
    #     json.dump(dataset["train"], f, indent=4, ensure_ascii=False)
        
    trainer_cls = Qwen2VLGRPOTrainer if not training_args.use_vllm else Qwen2VLGRPOVLLMTrainerModified
    # trainer_cls = Qwen2VLGRPOTrainer
    
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
    parser = TrlParser((GRPOScriptArguments, GRPOConfig, ModelConfig))
    script_args, training_args, model_args = parser.parse_args_and_config()
    #print("Parsed training_args:", training_args)
    #print("Parsed model_args:", model_args)
   
    configuration_file = script_args.confile
    with open(configuration_file, "r") as stream:
        conf = yaml.safe_load(stream)
    main(script_args, training_args, model_args, conf)