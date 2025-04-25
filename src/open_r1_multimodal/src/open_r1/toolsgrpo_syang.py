# Copyright 2025 The HuggingFace Team. All rights reserved.
# # Licensed under the Apache License, Version 2.0 (the "License");
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
from typing import Optional, List, Any, Dict # Added List, Any, Dict

import cv2
import numpy as np

import gc
import torch
import shutil
# Removed: import faulthandler
# Removed: import multiprocessing
# Kept ThreadPoolExecutor in case it's used elsewhere, but ProcessPoolExecutor removed
from concurrent.futures import ThreadPoolExecutor, as_completed
# Removed: import signal
import runpy
from math_verify import parse, verify

import asyncio
# Removed: import subprocess
# Removed: from io import StringIO
# Removed: import contextlib
# Removed: import signal (duplicate removal)
import json
import traceback # Added
import aiohttp # Added

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))))
# sys.path.insert(0, root_dir)

# !!! --- SANDBOX CONFIGURATION --- !!!
# !!! Replace with the actual URL of your sandbox service API endpoint !!!
SANDBOX_URL = "http://10.153.51.195:8080/api/sandbox/execute"
# !!! Request timeout (seconds) for calls to the sandbox, should be slightly longer than the sandbox's own execution timeout !!!
REQUEST_TIMEOUT = 65

# !!! --- END SANDBOX CONFIGURATION --- !!!


# External Tools Modules (Keep as in original)
# from object_detector import Object_Detector_Tool

from datasets import load_dataset, load_from_disk, concatenate_datasets
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
from open_r1.trainer import Qwen2VLGRPOTrainer, Qwen2VLGRPOVLLMTrainerModified
# from src.open_r1.trainer import Qwen2VLGRPOTrainer
from trl import GRPOConfig, GRPOTrainer, ModelConfig, ScriptArguments, TrlParser, get_peft_config
from PIL import Image
import yaml, argparse # Keep yaml, argparse

# --- GRPOScriptArguments Dataclass (Keep as in original) ---
@dataclass
class GRPOScriptArguments(ScriptArguments):
    """
    Script arguments for the GRPO training script.
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
#          REMOVED Local Execution Preparation Functions        #
#################################################################
# Functions `reliability_guard`, `unsafe_execute`, `check_correctness` are REMOVED.


##########################################################################
#             NEW Remote Sandbox Execution Functions                     #
##########################################################################

async def _call_sandbox_task(session: aiohttp.ClientSession, task: Dict, log_root_dir: str, current_time_str: str) -> tuple[float, Any]:
    """
    Internal async function: Calls the sandbox for a single task and processes the result.
    (Same as provided in the previous correct answer)
    """
    q_aid = task.get("QAid", "unknown_qaid")
    code = task.get("code")
    task_log_file = os.path.join(log_root_dir, f"sandbox_comm_{q_aid}_{current_time_str}.log")

    if code is None:
        log_entry = f"[{datetime.now()}] Task {q_aid}: Skipped - Code is None.\n"
        try:
            with open(task_log_file, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception as log_e:
            print(f"Error writing skip log for {q_aid}: {log_e}")
        return (0.0, None)

    payload = {
        "code": code,
        "timeout": REQUEST_TIMEOUT,  # Match sandbox default or configure as needed
        "q_aid": q_aid
    }

    log_entry = f"[{datetime.now()}] Task {q_aid}: Sending request to sandbox.\n"
    log_entry += f"Payload: {json.dumps(payload, indent=2)}\n"

    response_text = ""
    try:
        async with session.post(SANDBOX_URL, json=payload, timeout=REQUEST_TIMEOUT) as response:
            response_text = await response.text()
            log_entry += f"[{datetime.now()}] Task {q_aid}: Received response (Status: {response.status}).\n"
            log_entry += f"Raw Response Body:\n{response_text}\n"

            response.raise_for_status() # Check for HTTP errors (4xx, 5xx)
            sandbox_result = json.loads(response_text) # Parse JSON response

            # --- Map sandbox result to reward ---
            sandbox_status = sandbox_result.get("status")
            sandbox_final_result = sandbox_result.get("result")

            reward = 0.0
            result_value = None

            if sandbox_status == "success":
                if sandbox_final_result is not None:
                    reward = 1.0
                    result_value = sandbox_final_result

            log_entry += f"[{datetime.now()}] Task {q_aid}: Mapping successful.\n"
            log_entry += f"  Mapped Reward: {reward}\n"
            log_entry += f"  Mapped Result Value: {repr(result_value)}\n"

            try:
                with open(task_log_file, "a", encoding="utf-8") as f:
                    f.write(log_entry)
            except Exception as log_e:
                print(f"Error writing success log for {q_aid}: {log_e}")

            return (reward, result_value)

    except aiohttp.ClientResponseError as e:
        error_msg = f"HTTP Error for QAid {q_aid}: Status {e.status}, Message: {e.message}"
        log_entry += f"[{datetime.now()}] Task {q_aid}: Communication Error - {error_msg}\nResponse Text (if available):\n{response_text}\n"
        print(f"Error for {q_aid}: {error_msg}")
    except asyncio.TimeoutError:
        error_msg = f"Timeout Error for QAid {q_aid} after {REQUEST_TIMEOUT}s calling sandbox."
        log_entry += f"[{datetime.now()}] Task {q_aid}: Communication Error - {error_msg}\n"
        print(f"Error for {q_aid}: {error_msg}")
    except aiohttp.ClientError as e: # Includes connection errors
        error_msg = f"Client Connection Error for QAid {q_aid}: {e}"
        log_entry += f"[{datetime.now()}] Task {q_aid}: Communication Error - {error_msg}\n"
        print(f"Error for {q_aid}: {error_msg}")
    except json.JSONDecodeError as e:
        error_msg = f"JSON Decode Error for QAid {q_aid}: {e}. Received text: {response_text[:200]}..."
        log_entry += f"[{datetime.now()}] Task {q_aid}: Communication Error - {error_msg}\n"
        print(f"Error for {q_aid}: {error_msg}")
    except Exception as e: # Catch unexpected errors during the process
        error_msg = f"Unexpected Error during sandbox call for QAid {q_aid}: {e}\n{traceback.format_exc()}"
        log_entry += f"[{datetime.now()}] Task {q_aid}: Unexpected Error - {error_msg}\n"
        print(f"Error for {q_aid}: {error_msg}")

    try:
        with open(task_log_file, "a", encoding="utf-8") as f:
            f.write(log_entry) # Write log entry containing the error details
    except Exception as log_e:
        print(f"Error writing error log for {q_aid}: {log_e}")

    return (0.0, None)

# --- Rewritten run_all_checks_async ---
async def run_all_checks_async(tasks: List[Dict], log_root_dir: str, current_time_str: str) -> tuple[List[float], List[Any]]:
    """
    Concurrently calls the remote sandbox to execute a batch of tasks.
    (Same as provided in the previous correct answer)
    """
    results = []
    async with aiohttp.ClientSession() as session:
        coroutines = [
            _call_sandbox_task(session, task, log_root_dir, current_time_str)
            for task in tasks
        ]
        results = await asyncio.gather(*coroutines)

    reward_list = [r for r, _ in results]
    result_list = [res for _, res in results]

    return (reward_list, result_list)

##########################################################################
#                    MODIFIED EXECUTION REWARD                           #
##########################################################################

def execution_reward(completions, QAid, step, **kwargs):
    """
    Calculates execution reward by extracting code and calling the remote sandbox.
    """
    # --- Code Extraction Logic (Keep as in original) ---
    # Determine content type based on completions structure
    if not completions: # Handle empty list
        return ([], [])
    if isinstance(completions[0], str):
        contents = [completion for completion in completions]
    elif isinstance(completions[0], list) and completions[0] and isinstance(completions[0][0], dict) and "content" in completions[0][0]:
         # Assuming structure like [{'role': '...', 'content': '...'}]
        contents = [completion[0]["content"] for completion in completions]
    else:
         # Fallback or error for unexpected structure
         print(f"Warning: Unhandled completion structure in execution_reward: {type(completions[0])}")
         # Return zero rewards for all items as a safe default
         return ([0.0] * len(completions), [None] * len(completions))

    def extract_code(completion_content):
            """Extracts code from <command> tags."""
            if not isinstance(completion_content, str): return None # Handle non-string content
            match = re.search(r"<command>(.*?)</command>", completion_content, re.DOTALL)
            if match:
                # Strip() is good practice here
                return match.group(1).strip()
            else:
                # Return None if no <command> tags found
                return None

    tasks = []
    for content, qid in zip(contents, QAid): # Use qid to avoid shadowing built-in id
        code = extract_code(content)
        tasks.append({
            "code": code, # code can be None if extraction fails
            "QAid": qid
        })

    current_time = datetime.now()
    current_time_str_log = current_time.strftime("%Y%m%d-%H%M%S-%f") # Log-friendly format
    current_time_str_display = current_time.strftime("%d-%H-%M-%S-%f") # Original display format if needed elsewhere

    # --- MODIFIED Log Directory ---
    # Use a different subdirectory name to distinguish from local execution logs
    log_root_dir = os.path.join(root_dir, "A+M_split_logs", "Sandbox_Comm", f"step_{step}-{current_time_str_log}-logs")
    try:
        os.makedirs(log_root_dir, exist_ok=True)
    except OSError as e:
         print(f"ERROR: Failed to create log directory {log_root_dir}: {e}")
         # Handle error appropriately, maybe return default rewards
         return ([0.0] * len(tasks), [None] * len(tasks))

    # --- Call the NEW run_all_checks_async ---
    try:
        # Get or create an asyncio event loop
        loop = asyncio.get_event_loop_policy().get_event_loop()
        if loop.is_closed():
             loop = asyncio.new_event_loop()
             asyncio.set_event_loop(loop)
        # Pass the log-friendly timestamp string
        reward_result = loop.run_until_complete(
            run_all_checks_async(tasks, log_root_dir, current_time_str_log)
        )
    except RuntimeError as e:
        print(f"ERROR running asyncio task in execution_reward: {e}")
        # Fallback if asyncio.run fails (e.g., nested loops)
        reward_result = ([0.0] * len(tasks), [None] * len(tasks))

    return reward_result # Should be tuple (reward_list, result_list)

# Keep the reward_type attribute
execution_reward.reward_type = "execution"

####################################################################
#           ACCURACY REWARD (Keep as in original)                  #
#   (Depends on output of execution_reward, logic remains the same) #
####################################################################
def accuracy_reward(exec_reward_list, exec_result_list, step, solution, QAid, **kwargs):
    """
    (Function body kept identical to your original script)
    """
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_root_dir = os.path.join(f"{root_dir}/A+M_split_logs/Accuracy", f"step_{step}-{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
    rewards = []
    for exec_r, result, sol, id in zip(exec_reward_list, exec_result_list, solution, QAid):
        reward = 0.0
        acc_log_path = os.path.join(log_root_dir, f"accuracy-{id}.log")
        if exec_r == 0:
            # Log execution failure/invalid result
            with open(acc_log_path, "a", encoding="utf-8") as f: # Added encoding
                f.write(f"\n[QAid]{id} | Timestamp: {datetime.now()}\n")
                f.write(f"Execution Reward: {exec_r}\n")
                f.write("[Result]: Execution failed or yielded invalid result (None).\n")
                f.write("[Accuracy Reward]: 0.0\n")
                f.write("="*30 + "\n")
        else:
            # Log successful execution attempt
            log_content = f"\n[QAid]{id} | Timestamp: {datetime.now()}\n"
            log_content += f"Execution Reward: {exec_r}\n"
            log_content += f"Execution Result: {repr(result)}\n" # Use repr for logging
            log_content += f"Ground Truth Solution: {sol}\n"
            is_correct = False
            try:
                # Try symbolic verification
                parsed_result = parse(str(result)) # Convert result to string for parse
                parsed_solution = parse(sol)
                # Verify returns 1.0 if approximately equal
                # if verify(parsed_result, parsed_solution) >= 1.0:
                #<CHANGE>
                if float(verify(parsed_result, parsed_solution)) > 0:
                    reward = 1.0
                    is_correct = True
                    log_content += "[Result]: Correct (Verified Symbolically/Numerically).\n"
            except Exception as verify_e:
                # Symbolic verification failed, log info and try string comparison
                log_content += f"[Info]: Symbolic verification failed ({verify_e}), trying string comparison.\n"
                pass # Continue to string check

            # String comparison (only if symbolic check didn't confirm correctness)
            if not is_correct:
                match = False
                if isinstance(result, str) and isinstance(sol, str):
                    if result.lower() == sol.lower():
                        match = True
                elif str(result) == str(sol): # Fallback string representation check
                    match = True

                if match:
                    reward = 1.0
                    is_correct = True
                    log_content += "[Result]: Correct (String Match).\n"

            if not is_correct:
                reward = 0.0
                log_content += "[Result]: Incorrect.\n"

            log_content += f"[Accuracy Reward]: {reward}\n"
            log_content += "="*30 + "\n"
            # Write the log entry
            try:
                with open(acc_log_path, "a", encoding="utf-8") as f:
                    f.write(log_content)
            except Exception as log_e:
                print(f"Error writing accuracy log for {id}: {log_e}")

        rewards.append(reward)
    return rewards
accuracy_reward.reward_type = "accuracy" # Keep attribute

####################################################################
#              FORMAT REWARD (Keep as in original)                 #
####################################################################
def format_reward(completions,step,QAid, **kwargs):
    """Reward function that checks if the completion has a specific format."""
    # Original pattern check: Requires <command>...</command> and final_result = inside
    # pattern = r"<command>.*?\bfinal_result\s*=.*?</command>" # Simplified from original complex negative lookahead
    # Note: Original pattern was: r"(?s)<command>(?!\s*\bfinal_result\b).*?\bfinal_result\b\s*=.*?</command>"
    # The simplified one is usually sufficient: requires <command> and final_result= inside.
    #<CHANGE>
    pattern = r"(?s)<command>(?!\s*\bfinal_result\b).*?\bfinal_result\b\s*=.*?</command>"

    # Handle completion structure (same logic as execution_reward)
    if not completions: return []
    if isinstance(completions[0], str):
        completion_contents = completions
    elif isinstance(completions[0], list) and completions[0] and isinstance(completions[0][0], dict) and "content" in completions[0][0]:
        completion_contents = [completion[0]["content"] for completion in completions]
    else:
        print(f"Warning: Unhandled completion structure in format_reward: {type(completions[0])}")
        return [0.0] * len(completions)

    rewards = []
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f") # Original timestamp format
    log_root_dir = os.path.join(f"{root_dir}/A+M_split_logs/Format", f"step_{step}-{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)

    for i, (content, qid) in enumerate(zip(completion_contents, QAid)): # Use qid
        reward = 0.0
        format_log_path = os.path.join(log_root_dir, f"format-{qid}.log") # Use qid
        log_content = f"--- Completion {i+1} (QAid: {qid}) ---\n"
        if isinstance(content, str):
            log_content += content + "\n"
            # Use re.search as the pattern doesn't need to match the *entire* string
            # match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            match = re.fullmatch(pattern, content, re.DOTALL) # Added IGNORECASE just in case
            if match:
                reward = 1.0
                log_content += "[Format Check]: Passed\n"
            else:
                reward = 0.0
                log_content += "[Format Check]: Failed\n"
        else:
            # Handle case where content extraction failed
            log_content += "[Content Error]: Could not extract string content.\n"
            log_content += "[Format Check]: Failed\n"
            reward = 0.0

        rewards.append(reward)
        log_content += f"Reward: {reward}\n\n"
        try:
            with open(format_log_path, "a+", encoding="utf-8") as f: # Added encoding
                f.write(log_content)
        except Exception as log_e:
             print(f"Error writing format log for {qid}: {log_e}")
    return rewards
format_reward.reward_type = "format" # Keep attribute


####################################################################
#             Tool Usage REWARD (Keep as in original)              #
####################################################################
import ast # Keep import

def tool_usage_reward(completions, QAid, step , **kwargs):
    """
    Checks whether the generated code contains a '.execute(...)' call using AST.
    (Function body kept identical to your original script, added minor logging/robustness)
    """
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f") # Original format
    log_root_dir = os.path.join(f"{root_dir}/A+M_split_logs/Tools_usage", f"step_{step}-{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
    rewards = []

    # Handle completion structure (same logic as execution_reward)
    if not completions: return []
    if isinstance(completions[0], str):
        contents = completions
    elif isinstance(completions[0], list) and completions[0] and isinstance(completions[0][0], dict) and "content" in completions[0][0]:
        contents = [completion[0]["content"] for completion in completions]
    else:
        print(f"Warning: Unhandled completion structure in tool_usage_reward: {type(completions[0])}")
        # Default reward for tool usage is often -1 or 0 if parsing fails
        return [-1.0] * len(completions)

    def extract_code(completion_content):
        """Extracts code block from <command> tags."""
        if not isinstance(completion_content, str): return None
        match = re.search(r"<command>(.*?)</command>", completion_content, re.DOTALL)
        if match:
            return match.group(1).strip()
        else:
            # Original code raised ValueError, returning None is safer for batch processing
            # raise ValueError("No Python code block found in completion.")
            return None

    for content, qid in zip(contents, QAid): # Use qid
        reward = -1.0 # Default: failure to parse or no tool use
        tool_log_path = os.path.join(log_root_dir, f"toolusage-{qid}.log") # Use qid
        log_content = f"\n--- QAid: {qid} | Timestamp: {datetime.now()} ---\n"
        log_content += f"Completion Content:\n{content}\n\n"

        code = extract_code(content)

        if code:
            log_content += f"Extracted Code:\n{code}\n\n"
            try:
                execute_found = False
                tree = ast.parse(code) # Abstract Syntax Tree
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        # Check for attribute call like obj.execute()
                        if isinstance(node.func, ast.Attribute):
                            if node.func.attr == "execute":
                                reward = 1.0 # Found tool use
                                execute_found = True
                                log_content += "[Tool Check]: Passed (Found '.execute()' call via AST)\n"
                                break # Found it, no need to search further
                if not execute_found:
                    # reward = 0.0 # Parsed successfully, but no .execute() call found
                    #<CHNGE>
                    reward = -1.0
                    log_content += "[Tool Check]: Failed (Code parsed, but no '.execute()' call found)\n"

            except SyntaxError as e:
                # Code extraction worked, but AST parsing failed
                reward = -1.0
                log_content += f"[Tool Check]: Failed (SyntaxError during AST parsing: {e})\n"
            except Exception as e:
                # Other potential errors during AST parsing
                reward = -1.0
                log_content += f"[Tool Check]: Failed (Exception during AST parsing: {e})\n"
        else:
            # Code extraction failed
            reward = -1.0
            log_content += "[Tool Check]: Failed (Could not extract code from <command> tags)\n"

        rewards.append(reward)
        log_content += f"Tool Usage Reward: {reward}\n"
        log_content += "=" * 30 + "\n"
        try:
            with open(tool_log_path, "a+", encoding="utf-8") as f: # Added encoding
                f.write(log_content)
        except Exception as log_e:
             print(f"Error writing tool usage log for {qid}: {log_e}")
    return rewards
tool_usage_reward.reward_type = "tool" # Keep attribute

####################################################################
#                Reward Function Registry (Keep as in original)     #
####################################################################
reward_funcs_registry = {
    "execution": execution_reward, # Uses remote sandbox now
    "accuracy": accuracy_reward,
    "format": format_reward,
    "tool": tool_usage_reward
}
#####################################################################

######## Global asyncio loop setup (Keep as in original) ########
# import asyncio
# try:
#     global_loop = asyncio.get_event_loop()
# except RuntimeError:
#     global_loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(global_loop)
############################################################

###################### MAIN Function (Keep as in original) ############################
def main(script_args, training_args, model_args, conf):
    """
    Main training orchestration function.
    (Function body kept identical to your original script)
    """
    # Get reward functions
    try: # Added try-except for safety
        reward_funcs = [reward_funcs_registry[func] for func in script_args.reward_funcs]
        if len(reward_funcs) != len(script_args.reward_weights):
             raise ValueError(f"Mismatch between reward_funcs ({len(reward_funcs)}) and reward_weights ({len(script_args.reward_weights)})")
    except KeyError as e:
         print(f"ERROR: Invalid reward function name '{e}' specified in --reward_funcs. Available: {list(reward_funcs_registry.keys())}")
         sys.exit(1)
    except ValueError as e:
         print(f"ERROR: {e}")
         sys.exit(1)

    # Check if the model is a base model
    base_model_prompt = False
    # Added check if model_name_or_path exists
    if model_args.model_name_or_path and \
       (model_args.model_name_or_path.split("/")[-1] == "Qwen2-VL-2B" or \
        "Base" in model_args.model_name_or_path):
        base_model_prompt = True
        print("Info: Detected base model name, using base model prompt format.")

    PROMPT_TEMPLATE = conf.get("prompt_template")
    if not PROMPT_TEMPLATE:
         print("ERROR: 'prompt_template' not found in the configuration file.")
         sys.exit(1)

    # --- Data Processing Function (Keep as in original) ---
    def make_conversation_sat(example, prefix,
                        available_tools_str: str,
                        filtered_metadata_str: str,
                        base_model_prompt=False):
        """Processes a single data sample."""
        # Basic structure validation
        if not all(k in example for k in ["messages", "images"]) or len(example["messages"]) < 2:
             print(f"Warning: Skipping example due to missing keys or insufficient messages. Keys: {list(example.keys())}")
             return None

        try:
            answer = example["messages"][1]["content"].strip()
            image_paths = [os.path.join(prefix, img_path) for img_path in example["images"]]

            images = []
            for path in image_paths:
                try:
                    with Image.open(path) as img_opened:
                        img_copy = img_opened.copy() # 复制图像数据
                    # 使用复制后的数据
                    images.append(img_copy)
                    # img = Image.open(path)
                    # # Optional: Add validation/resizing based on script_args.min/max_pixels here if needed
                    # images.append(img)
                except FileNotFoundError:
                    print(f"Warning: Image file not found '{path}'. Skipping example.")
                    return None
                except Exception as img_e:
                    print(f"Warning: Error loading image '{path}': {img_e}. Skipping example.")
                    return None

            # Safely get idx, provide fallback if missing
            idx = example.get("idx")
            if idx is None:
                 # Create a fallback ID (e.g., from first image name)
                 idx = os.path.splitext(os.path.basename(image_paths[0]))[0] if image_paths else f"no_idx_{time.time()}"
                #  print(f"Warning: 'idx' key missing in example. Using fallback ID: {idx}")

            # Format the question part
            formatted_question_part = PROMPT_TEMPLATE.format(
                question=example["messages"][0]["content"].strip(),
                image_paths=",".join(image_paths), # Pass paths if template needs them
                available_tools=available_tools_str,
                toolbox_metadata=filtered_metadata_str
            )

            # Prepare prompt structure based on model type
            if base_model_prompt:
                prompt_text = f"""A conversation between User and Assistant.
                The user asks a question about the image, and the Assistant solves it.
                The assistant first thinks about the reasoning process in the mind and then provides the user with the answer.
                \nUser: {formatted_question_part} \nAssistant: <command>"""
                # Adapt image handling for base model if needed (original code had resizing logic here)
                processed_images = []
                for img in images:
                    try:
                        # Original resizing logic - keep if necessary for base model
                        w, h = img.size
                        target_min_dim = 28 # Example minimum dimension
                        if w < target_min_dim or h < target_min_dim:
                            if w < h:
                                new_w = target_min_dim
                                new_h = int(h * (target_min_dim / w))
                            else:
                                new_h = target_min_dim
                                new_w = int(w * (target_min_dim / h))
                            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        processed_images.append(img)
                    except Exception as resize_e:
                        print(f"Warning: Failed to resize image for base model: {resize_e}. Using original.")
                        processed_images.append(img) # Use original on error

                # Construct multimodal message content for base model
                # The exact format depends on how the trainer/processor expects it
                message_content = [ {'type': 'image'} ] * len(processed_images) # Placeholders for images
                # Add image tags matching the number of images before the text
                message_content.append({
                    "type": "text",
                    "text": "<image>" * len(processed_images) + prompt_text
                })
                prompt_data = message_content # This might need further processing by the tokenizer/processor

            else: # Instruct/Chat model prompt
                processed_images = images # Use original images
                message_content = [ {'type': 'image'} ] * len(processed_images) # Placeholders
                message_content.append({ # Text part
                    "type": "text",
                    "text": formatted_question_part
                })
                # Standard chat format expected by most instruct models/processors
                prompt_data = [
                    {
                        "role": "user",
                        "content": message_content,
                    },
                ]

            return {"image": processed_images,
                    "image_path": image_paths,
                    "prompt": prompt_data, # This is the data that will be processed by the tokenizer
                    "solution": answer,
                    "QAid": str(idx) # Ensure QAid is string
                   }
        except Exception as e:
             # Log error for the specific example but continue processing others
             print(f"ERROR processing example (ID: {example.get('idx', 'N/A')}): {e}\n{traceback.format_exc()}")
             return None


    # --- Tool Loading Function (Keep as in original) ---
    def load_tool_data(conf):
        """Loads tool metadata from configuration."""
        active_tool_names = conf.get("available_tools", [])
        full_toolbox_metadata = conf.get("toolbox_metadata", {})
        filtered_metadata_dict = {
            tool_name: full_toolbox_metadata[tool_name]
            for tool_name in active_tool_names if tool_name in full_toolbox_metadata
        }
        missing_tools = [tn for tn in active_tool_names if tn not in full_toolbox_metadata]
        if missing_tools:
            print(f"Warning: Tools listed in available_tools but not found in toolbox_metadata: {missing_tools}")
        filtered_metadata_str = json.dumps(filtered_metadata_dict, indent=2)
        available_tools_str = ", ".join(active_tool_names)
        return available_tools_str, filtered_metadata_str

    #################### Data Loading Start (Keep as in original) ####################
    # Make dataset_prefix configurable via yaml?
    dataset_prefix = conf.get("dataset_prefix", "/nfs/data8/liao/wxie/SAT") # Get from conf or use default
    print(f"Using dataset prefix: {dataset_prefix}")

    # SAT Dataloader
    dataset = {}
    all_samples = []

    # Make dataset path configurable via yaml?
    dataset_path_config = conf.get("dataset_path", "filtered_output_file.json") # Default path
    full_path = os.path.join(dataset_prefix, dataset_path_config)
    print(f"Attempting to load dataset from: {full_path}")

    if not os.path.exists(full_path):
         print(f"ERROR: Dataset file not found at {full_path}")
         sys.exit(1)

    try:
        with open(full_path, 'r', encoding='utf-8') as f: # Added encoding
            raw_dataset = json.load(f) # Assumes a list of samples
            print(f"Loaded {len(raw_dataset)} raw samples.")
            available_tools_str, filtered_metadata_str = load_tool_data(conf=conf)
            # Process samples, handling potential None returns from make_conversation_sat
            processed_dataset = [
                processed_sample for sample in raw_dataset
                if (processed_sample := make_conversation_sat(
                        sample, dataset_prefix, available_tools_str,
                        filtered_metadata_str, base_model_prompt)) is not None
            ]
            all_samples.extend(processed_dataset)
            print(f"Successfully processed {len(all_samples)} samples.")
            if len(all_samples) < len(raw_dataset):
                 print(f"Note: {len(raw_dataset) - len(all_samples)} samples were skipped during processing.")

    except json.JSONDecodeError as e:
         print(f"ERROR: Failed to decode JSON from {full_path}: {e}")
         sys.exit(1)
    except Exception as e:
         print(f"ERROR during data loading or processing: {e}\n{traceback.format_exc()}")
         sys.exit(1)


    # Basic train/test split (Consider making this more robust, e.g., using config)
    # This assumes 'all_samples' is now populated
    # split_point = int(len(all_samples) * DATASET_SPLIT) # Simple 90/10 split
    # dataset = {
    #     "train": all_samples[:split_point],
    #     "test": all_samples[split_point:] # Use 'test' split name
    # }
    # print(f"Dataset split: Train {len(dataset['train'])}, Test {len(dataset['test'])}")
    dataset = {"train": all_samples}
    print(f"Dataset loaded: {len(all_samples)} samples (train split only)")

    # Check if splits are valid
    if not dataset["train"]:
        print("ERROR: No training data available after processing and splitting.")
        sys.exit(1)
    if training_args.eval_strategy != "no" and not dataset["test"]:
         print("Warning: Evaluation is enabled, but no test data is available after processing.")
         # Decide whether to proceed or exit based on requirements
         # sys.exit(1)


    #################### Data Loading End ####################


    # --- Trainer Initialization (Keep as in original) ---
    trainer_cls = Qwen2VLGRPOTrainer if not training_args.use_vllm else Qwen2VLGRPOVLLMTrainerModified
    print(f"Using Trainer class: {trainer_cls.__name__}")

    # Ensure dataset split names match arguments
    train_split_name = script_args.dataset_train_split # e.g., "train"
    eval_split_name = script_args.dataset_test_split # e.g., "test"

    # Convert torch_dtype string to actual torch dtype object
    try:
        torch_dtype = getattr(torch, model_args.torch_dtype) if model_args.torch_dtype else None
    except AttributeError:
        print(f"Warning: Invalid torch_dtype '{model_args.torch_dtype}' specified. Using default.")
        torch_dtype = None

    # Initialize the GRPO trainer
    try:
        trainer = trainer_cls(
            model=model_args.model_name_or_path,
            reward_funcs=reward_funcs, # The list of function objects
            args=training_args,
            train_dataset=dataset[train_split_name], # Use split name from args
            # Use .get for eval_dataset in case the split doesn't exist
            eval_dataset=dataset.get(eval_split_name) if training_args.eval_strategy != "no" else None,
            peft_config=get_peft_config(model_args),
            attn_implementation=model_args.attn_implementation,
            torch_dtype=torch_dtype, # Use the converted dtype object
            reward_weights = script_args.reward_weights, # Pass weights
            max_pixels=script_args.max_pixels,
            min_pixels=script_args.min_pixels,
        )
        print("Trainer initialized successfully.")
    except KeyError as e:
         print(f"ERROR: Dataset split '{e}' not found. Available splits: {list(dataset.keys())}")
         sys.exit(1)
    except Exception as e:
         print(f"ERROR initializing trainer: {e}\n{traceback.format_exc()}")
         sys.exit(1)


    # --- Freezing Logic (Keep as in original) ---
    if script_args.freeze_vision:
        print("Freezing vision model parameters.")
        # Check if visual attribute exists
        if hasattr(trainer.model, 'visual') and trainer.model.visual is not None:
             for param in trainer.model.visual.parameters():
                 param.requires_grad = False
             # Verification print
             vision_trainable = sum(p.numel() for p in trainer.model.visual.parameters() if p.requires_grad)
             print(f"Trainable parameters in visual encoder after freezing: {vision_trainable}")
        else:
             print("Warning: Model does not have a 'visual' attribute to freeze.")

    # Enhanced freezing logic for LLM part
    if script_args.freeze_llm:
        print("Freezing LLM parameters.")
        llm_module = None
        # Try common attribute names for the language model part
        potential_llm_attrs = ['language_model', 'model', 'text_model', 'llm']
        for attr_name in potential_llm_attrs:
            if hasattr(trainer.model, attr_name) and getattr(trainer.model, attr_name) is not None:
                llm_module = getattr(trainer.model, attr_name)
                print(f"Found LLM module under attribute: '{attr_name}'")
                break
        if llm_module:
            for param in llm_module.parameters():
                param.requires_grad = False
            # Verification print
            llm_trainable = sum(p.numel() for p in llm_module.parameters() if p.requires_grad)
            print(f"Trainable parameters in LLM ('{attr_name}') after freezing: {llm_trainable}")
        else:
            print("Warning: Could not automatically identify LLM module to freeze. Check model structure.")

    # Total trainable parameters check
    total_trainable = sum(p.numel() for p in trainer.model.parameters() if p.requires_grad)
    print(f"Total trainable parameters in the model: {total_trainable}")


    # --- Training (Keep as in original) ---
    print("Starting training...")
    try:
        train_result = trainer.train()
        # Optional: Log training results (e.g., train_result.training_loss)
        print(f"Training completed. Result: {train_result}")
    except Exception as e:
        print(f"ERROR during training: {e}\n{traceback.format_exc()}")
        # Consider saving a checkpoint here on error if possible/desired
        # trainer.save_model(os.path.join(training_args.output_dir, "checkpoint-error"))
        sys.exit(1) # Exit after training error


    # --- Saving and Pushing (Keep as in original) ---
    print(f"Saving final model to: {training_args.output_dir}")
    try:
        trainer.save_model(training_args.output_dir)
        print("Model saved successfully.")
    except Exception as e:
        print(f"ERROR saving model: {e}\n{traceback.format_exc()}")
        # Decide if execution should continue if saving fails

    if training_args.push_to_hub:
        print(f"Pushing model to Hub repository: {training_args.hub_model_id or 'default'}")
        try:
            # Pass dataset name if provided, otherwise it might use default from output_dir
            trainer.push_to_hub(dataset_name=script_args.dataset_name)
            print("Model pushed to Hub successfully.")
        except Exception as e:
            print(f"ERROR pushing model to Hub: {e}\n{traceback.format_exc()}")

    print("Script finished.")
    # Optional: Close global loop if it was explicitly managed
    # if 'global_loop' in locals() and not global_loop.is_closed():
    #     global_loop.close()


if __name__ == "__main__":
    # --- Argument Parsing (Keep as in original) ---
    parser = TrlParser((GRPOScriptArguments, GRPOConfig, ModelConfig))
    script_args, training_args, model_args = parser.parse_args_and_config()

    # --- Configuration File Loading (Keep as in original, added safety checks) ---
    if not script_args.confile:
        print("ERROR: Configuration file path (--confile) is mandatory.")
        sys.exit(1)

    configuration_file = script_args.confile
    # Resolve path if it's relative (relative to the script location)
    if not os.path.isabs(configuration_file):
        config_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
        configuration_file = os.path.join(config_root, configuration_file)

    print(f"Loading configuration from: {configuration_file}")
    if not os.path.exists(configuration_file):
        print(f"ERROR: Configuration file not found at '{configuration_file}'")
        sys.exit(1)

    try:
        with open(configuration_file, "r", encoding="utf-8") as stream: # Added encoding
            conf = yaml.safe_load(stream)
        if not isinstance(conf, dict):
             print(f"ERROR: Configuration file '{configuration_file}' did not load as a dictionary.")
             sys.exit(1)
    except yaml.YAMLError as exc:
        print(f"ERROR parsing YAML configuration file '{configuration_file}': {exc}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR loading configuration file '{configuration_file}': {e}")
        sys.exit(1)

    # --- Call Main Function (Keep as in original) ---
    main(script_args, training_args, model_args, conf)