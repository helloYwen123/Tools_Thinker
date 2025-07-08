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
import re
from typing import Dict, List
from datetime import datetime
import os
from typing import Optional
import faulthandler
import ast
import signal
from io import StringIO
import contextlib
import multiprocessing
import asyncio
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor , as_completed
import requests
from math_verify import parse, verify

REMOTE_URL = "http://10.153.51.195:8080/api/sandbox/execute"

def clean_string(val):
    val = str(val).strip()
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        val = val[1:-1].strip()
    return val.lower()  #


def accuracy_reward(exec_result, response, step, solution, QAid, **kwargs):
    """
    """
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    current_time = datetime.now().strftime("%d-%H-%M-%S")
    split = "validation" if step == "validation" else "train"
    step_str = f"step_{step}" if isinstance(step, int) else f"step_{step}"
    log_root_dir = os.path.join(root_dir, f"grpo_tools_logs/{split}/accuracy/reward/{step_str}")
    acc_log_path = os.path.join(log_root_dir, f"accuracy_{current_time}-{QAid}.log")

    reward = 0.0

    try:
        # try to verify symbolic calculation
        parsed_result = parse(exec_result)
        parsed_solution = parse(solution)
        if float(verify(parsed_result, parsed_solution)) > 0:
            reward = 1.0
    except Exception:
        # symbolic calculation failed
        pass 
    
    if clean_string(exec_result) == clean_string(solution):
        reward = 1.0
    
    should_log = (
        (isinstance(step, str) and step == "validation") or
        (isinstance(step, int) and step % 2 == 0) or
        reward == 1.0
    )
    if should_log:
        os.makedirs(log_root_dir, exist_ok=True)
        with open(acc_log_path, "a", encoding="utf-8") as f:
            f.write(f"\nQAid: {QAid}\n")
            if reward == 1.0:
                f.write("\ncorrect result\n\n")
            else:
                f.write("\n wrong result\n\n")
            f.write(f"exec_result: {exec_result}\n")
            f.write(f"expected:    {solution}\n")
            f.write(f"response:{response}")
            f.write("=" * 30 + "\n\n")

    return reward

accuracy_reward.reward_type = "accuracy"


def execution_reward(predict_str, QAid, step):
    # SANDBOX EXECUTION #
    def sandbox_execute(code, timeout, result, log_path, QAid):
        current_time = datetime.now().strftime("%d-%H-%M-%S")
        payload = {
            "code": code,
            "timeout": timeout,
            "q_aid": QAid or "unknown"
        }
        try:
            resp = requests.post(REMOTE_URL, json=payload, timeout=timeout + 1)
            resp.raise_for_status()
            result_data = resp.json()
            status = result_data.get("status")
            stdout_raw = result_data.get("stdout", "")
            output_raw = stdout_raw
            output = result_data.get("result")

            if status == "success":
                if output is not None:
                    reward = 1.0
                else:
                    m = re.search(r"final_result:?[ \t]*(.+)", stdout_raw)
                    if m:
                        reward = 1.0
                        output = m.group(1)
                    else:
                        reward = 0.0
                        output = "Error: 'final_result' not found, through successful running"
                result = (reward, output)

                # Log success only if needed
                os.makedirs(log_path, exist_ok=True)
                success_log_path = os.path.join(log_path, f"success_execution_{current_time}-{QAid}.log")
                with open(success_log_path, "a+", encoding="utf-8") as df:
                    df.write("\n" + "=" * 30 + " new Completed Execution " + "=" * 30 + "\n")
                    df.write("[extracted code]\n" + code + "\n\n")
                    df.write("[raw output]\n" + output_raw + "\n\n")
                    df.write("[generated final result]\n" + str(output) + "\n\n")
                    df.write("=" * 30 + " end " + "=" * 30 + "\n\n")
                return result
            else:
                reward = 0.0
                output = result_data.get("error_message") or result_data.get("stderr") or result_data.get("stdout", "")
                output = output.split("\n--- Sys Path")[0].strip()
                result = (reward, output)

                if (isinstance(step, str) and step == "validation") or (isinstance(step, int) and step % 2 == 0):
                    os.makedirs(log_path, exist_ok=True)
                    debug_log_path = os.path.join(log_path, f"bug_exec_{current_time}-{QAid}.log")
                    with open(debug_log_path, "a+", encoding="utf-8") as df:
                        df.write("\n[execution failed]\n")
                        df.write(output + "\n")
                        df.write(f"code: \n{code}\n")
                        df.write("=" * 30 + " END " + "=" * 30 + "\n\n")
                return result

        except Exception as e:
            if (isinstance(step, str) and step == "validation") or (isinstance(step, int) and step % 2 == 0):
                os.makedirs(log_path, exist_ok=True)
                with open(os.path.join(log_path, f"bug_exec_{current_time}-{QAid}.log"), "a+", encoding="utf-8") as lf:
                    lf.write("\n" + "=" * 30 + f" QAid={QAid} error " + "=" * 30 + "\n")
                    lf.write(f"\n\n[sandbox execution reward function failed] {e}\n\n")
                    lf.write("code:\n" + code + "\n")
                    lf.write("=" * 30 + "\n\n")
            return (0.0, None)

    # CODE EXTRACTION #
    def extract_code(completion):
        match = re.search(r"<code>(.*?)</code>", completion, re.DOTALL)
        return match.group(1) if match else None

    code = extract_code(predict_str)
    current_time = datetime.now().strftime("%d-%H-%M-%S")
    # New target structure: reward/step_xx
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    split = "validation" if step == "validation" else "train"
    step_str = f"step_{step}"
    log_root_dir = os.path.join(root_dir, f"grpo_tools_logs/{split}/execution/reward/{step_str}")

    evaluation_log_path = os.path.join(log_root_dir, f"evaluation_{current_time}-{QAid}.log")

    if code is None:
        if (isinstance(step, str) and step == "validation") or (isinstance(step, int) and step % 2 == 0):
            os.makedirs(log_root_dir, exist_ok=True)
            with open(evaluation_log_path, "a+", encoding="utf-8") as f:
                f.write(f"------------- code extraction failed: execution reward: 0.0\n -------------\n")
                f.write(f"model's response:\n{predict_str}\n")
                f.write(f"\nQAid: {QAid}\n")
                f.write("=" * 30 + " end " + "=" * 30 + "\n\n")
        return (0.0, None)

    # Run in sandbox
    timeout = 120
    result = (0.0, None)
    final_result = sandbox_execute(code, timeout=timeout, result=result, log_path=log_root_dir, QAid=QAid)

    if (isinstance(step, str) and step == "validation") or (isinstance(step, int) and step % 2 == 0):
        os.makedirs(log_root_dir, exist_ok=True)
        with open(evaluation_log_path, "a+", encoding="utf-8") as f:
            f.write(f"------------- execution reward: {final_result[0]} -------------\n")
            f.write(f"QAid: {QAid}\n response:\n{predict_str}\n")
            f.write("=" * 30 + " end " + "=" * 30 + "\n\n")

    return final_result

execution_reward.reward_type = "execution"

def tool_usage_reward(predict_str, step, QAid):
    """
    Check whether the generated code uses any registered tools:
    - It must import a tool module
    - It must create an instance of a known tool class
    - It must call .execute()
    """
    # Create root log directory path like: .../train/tools_usage/reward/step_2/
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    split = "validation" if step == "validation" else "train"
    step_str = f"step_{step}" if isinstance(step, int) else f"step_{step}"
    current_time = datetime.now().strftime("%d-%H-%M-%S")
    if (isinstance(step, str) and step == "validation") or (isinstance(step, int) and step % 2 == 0):
        log_root_dir = os.path.join(root_dir, f"grpo_tools_logs/{split}/tools_usage/reward/{step_str}")
        os.makedirs(log_root_dir, exist_ok=True)

        # Log file path
        tool_log_path = os.path.join(log_root_dir, f"toolusage_{current_time}-{QAid}.log")
    
    # Define tool module and class mapping
    tool_modules = {
        'object_detector': 'Object_Detector_Tool',
        'text_detector': 'Text_Detector_Tool',
        'depth_estimator': 'Depth_Estimator_Tool',
        'segmenter': 'Segmenter_Tool',
        'matcher': 'Matcher_Tool'
    }

    def extract_code(completion):
        match = re.search(r"<code>(.*?)</code>", completion, re.DOTALL)
        if match:
            return match.group(1)
        else:
            raise ValueError("No <code>...</code> block found in the completion.")

    reward = 0.0

    try:
        execute_found = False
        imported_modules = set()
        used_tool_classes = set()
        
        code = extract_code(predict_str)
        tree = ast.parse(code)

        for node in ast.walk(tree):
            # import module
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in tool_modules:
                        imported_modules.add(alias.name)

            # from module import ToolClass
            elif isinstance(node, ast.ImportFrom):
                if node.module in tool_modules:
                    for alias in node.names:
                        if alias.name == tool_modules[node.module]:
                            imported_modules.add(node.module)

            # tool class instantiation
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in tool_modules.values():
                        used_tool_classes.add(node.func.id)

                elif isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name):
                        mod = node.func.value.id
                        cls = node.func.attr
                        if mod in tool_modules and tool_modules[mod] == cls:
                            used_tool_classes.add(cls)

                    # check for .execute()
                    if node.func.attr == "execute":
                        execute_found = True

        # Reward only if all conditions are met
        if execute_found and used_tool_classes and imported_modules:
            # Match class usage with correct import
            for mod, cls in tool_modules.items():
                if mod in imported_modules and cls in used_tool_classes:
                    reward = 1.0
                    break

        if (isinstance(step, str) and step == "validation") or (isinstance(step, int) and step % 2 == 0):
            with open(tool_log_path, "a+") as f:
                f.write(f"\n[QAid]{QAid}\n")
                if execute_found:
                    f.write("\n[Code Includes Tools Usage]\n")
                else:
                    f.write("\n[Code does not include Tools Usage]\n")
                f.write(f"code: \n{code}")
                f.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")

    except Exception as e:
        if (isinstance(step, str) and step == "validation") or (isinstance(step, int) and step % 2 == 0):
            with open(tool_log_path, "a+") as f:
                f.write(f"\nQAid:{QAid}\n")
                f.write("\nCode Extraction Failed or Parse Failed\n\n")
                f.write(str(e) + "\n")
                f.write(f"\nCompletion Content: \n{predict_str}\n")
                f.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")

    return reward

def format_reward(predict_str, step, QAid):
    """Reward function that checks if the completion has a specific format."""
    pattern1 = r"<think>(.*?)</think>(\n*)<code>(.*?)</code>" # no final_result but have correct tags
    # TODO - Done <code>(?!\s*\bfinal_result\b).*?\bfinal_result\b\s*=.*?</code>
    pattern2 = r"(?s)<think>.*?</think>\n*<code>.*?\bfinal_result\b\s*=.*?</code>"

    reward = 0.0
    if re.fullmatch(pattern2, predict_str, re.DOTALL):
        reward = 1.0    
    elif re.fullmatch(pattern1, predict_str, re.DOTALL):
        reward = 0.5  
    else:
        reward = 0.0
    # create timepoints as part of log names
    current_time = datetime.now().strftime("%d-%H-%M-%S")
    # create log file
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    split = "validation" if step == "validation" else "train"
    step_str = f"step_{step}"
    
    if (isinstance(step, str) and step == "validation") or (isinstance(step, int) and step % 2 == 0):
        log_root_dir = os.path.join(root_dir, f"grpo_tools_logs/{split}/format/reward/{step_str}")
        os.makedirs(log_root_dir, exist_ok=True)
        format_log_path = os.path.join(log_root_dir, f"format_{current_time}-{QAid}.log")

        with open(format_log_path, "a+") as f:
            f.write(f"--- Completion ---\n")
            f.write(predict_str + "\n")
            f.write(f"reward: {reward}\n\n")
    return reward

def compute_score(predict_strs: List[str], ground_truths: List[str], format_weight: float = 0.2, 
                  usage_weight: float = 0.3, execution_weight: float = 0.2, accuracy_weight: float = 0.3,
                  step = None, QAid: Optional[str] = None) -> List[Dict[str, float]]:
    scores = []
    assert format_weight + usage_weight + execution_weight + accuracy_weight == 1.0, "The sum of weights must be equal to 1.0"
    
    for predict_str, ground_truth in zip(predict_strs, ground_truths):
        format_score = format_reward(predict_str, step, QAid)
        tool_usage_score = tool_usage_reward(predict_str, step, QAid)
        execution_score = execution_reward(predict_str, QAid, step)
        
        # execution_score[1] is the result of execution
        if execution_score[0] != 0.0:
            accuracy_score = accuracy_reward(execution_score[1], response=predict_str, step=step, solution=ground_truth, QAid=QAid)
        else:
            accuracy_score = 0.0 # default: execution failed then accuracy is failed
            
        overall_score =  format_weight * format_score + usage_weight * tool_usage_score + execution_weight * execution_score[0] + accuracy_weight * accuracy_score
        
        scores.append(
            {
                "overall": overall_score,
                "format": format_score,
                "tool_usage": tool_usage_score,
                "execution": execution_score[0],
                "accuracy": accuracy_score
            }
        )
    return scores