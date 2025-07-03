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

def accuracy_reward(exec_result, step, solution, QAid, **kwargs):
    """
    """
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_root_dir = os.path.join(f"{root_dir}/Grpo_Tools_Logs/Accuracy", f"step_{step}-{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
    reward = 0.0
    acc_log_path = os.path.join(log_root_dir, f"accuracy-{QAid}.log")

    try:
        # try to verify symbolic calculation
        parsed_result = parse(exec_result)
        parsed_solution = parse(solution)
        if float(verify(parsed_result, parsed_solution)) > 0:
            reward = 1.0
            with open(acc_log_path, "a") as f:
                f.write(f"\n[QAid]{QAid}\n")
                f.write("\n[Verification Correct Result]\n\n")
    except Exception:
        # symbolic calculation failed
        pass 

    if exec_result == solution or exec_result.lower() == solution.lower():
        reward = 1.0
        with open(acc_log_path, "a") as f:
            f.write(f"\n[QAid]{QAid}\n")
            f.write("\n[Correct Result]\n\n")
    else:
        with open(acc_log_path, "a") as f:
            f.write(f"\n[QAid]{QAid}\n")
            f.write("\n[Wrong Result]\n\n")
    
    return reward

accuracy_reward.reward_type = "accuracy"


def execution_reward(predict_str, QAid, step):
    # SANDBOX EXECUTION #   
    def sandbox_execute(code, timeout, result, log_path, QAid):
        payload = {
            "code": code,
            "timeout": timeout,
            "q_aid": QAid or "unknown"
        }
        try:
            resp = requests.post(REMOTE_URL, json=payload, timeout=timeout + 1)
            resp.raise_for_status()
            data = resp.json()

            status     = data.get("status")
            stdout_raw = data.get("stdout", "")
            stderr_raw = data.get("stderr", "")
            output     = data.get("result", None)
            err_msg    = data.get("error_message")
            # 
            output_raw = stdout_raw.strip()
            stderr_raw = stderr_raw.strip()
            err_msg = err_msg.strip()

            if status == "success": # code executed successfully
                if output is not None:
                    reward = 1.0
                    output = output
                else: # output is none
                    stdout = stdout_raw.strip()
                    m = re.search(r"final_result:?[ \t]*(.+)", stdout)
                    if m:
                        reward = 1.0
                        output = m.group(1).strip()
                    else:
                        reward = 0.0
                        output = "Error: 'final_result' variable not found in output or not printed using the required format: print('final_result:', final_result).\n"
                result = (reward, output)
                success_log_path = os.path.join(log_path, "success_execution.log")
                with open(success_log_path, "a+") as df:
                    df.write("\n" + "=" * 30 + " New Completed Execution " + "=" * 30 + "\n")
                    df.write("[EXEC CODE]\n")
                    df.write(code + "\n")
                    df.write("[THE RAW OUTPUT]\n")
                    df.write(output_raw + "\n")
                    df.write("[GENERATE VALID FINAL_RESULT]\n")
                    df.write(str(output) + "\n")
                    df.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
                return result
            else:  # code executed with error
                reward = 0.0
                output = err_msg or stderr_raw or output_raw
                debug_log_path = os.path.join(log_path, "bug_exec.log")
                result = (reward, output)
                with open(debug_log_path, "a+") as df:
                    df.write("\n[Execution Failed]\n")
                    df.write(output + "\n")
                    df.write(f"code: \n{code}\n")
                    df.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
                return result

        except Exception as e:
            with open(os.path.join(log_path, "bug_exec.log"), "a+") as lf:
                lf.write("\n" + "=" * 30 + f" QAid={QAid} ERROR " + "=" * 30 + "\n")
                lf.write(f"[Sandbox Failed] {e}\n")
                lf.write("CODE:\n" + code + "\n")
                lf.write("=" * 30 + "\n\n")
            result = (0.0, None)
            return result
            
    # CODE EXTRACTION #        
    def extract_code(completion):
        match = re.search(r"<code>(.*?)</code>", completion, re.DOTALL)
        return match.group(1) if match else None

    code = extract_code(predict_str)
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_root_dir = os.path.join(f"{root_dir}/Grpo_Tools_Logs/Execution", f"step_{step}-{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
    
    evaluation_log_path = os.path.join(log_root_dir, f"evaluation-{QAid}.log")
    if code is None:
        with open(evaluation_log_path, "a+") as f:
            f.write(f"------------- {current_time} Code Extraction Failed -------------\n")
            f.write(f"Reward: 0.0\nQAid: {QAid}\nCode: [EMPTY]\n")
            f.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
        return (0.0, None)
    
    # code extracted success
    result = (0.0, None)
    time_out = 120
    final_result = sandbox_execute(code, timeout=time_out, result=result, log_path=log_root_dir, QAid=QAid)
    with open(evaluation_log_path, "a+") as f:
        f.write(f"------------- {current_time} Execution reward: {final_result[0]} -------------\n")
        f.write(f"QAid: {QAid}\nCode: \n{code}\n")
        f.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")

    return final_result

execution_reward.reward_type = "execution"


def tool_usage_reward(predict_str, step, QAid):
    """
    check whether the generated code containing tool execution
    """
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_root_dir = os.path.join(f"{root_dir}/Grpo_Tools_Logs/Tools_usage", f"step_{step}-{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
        
    def extract_code(completion):
        match = re.search(r"<code>(.*?)</code>", completion, re.DOTALL)
        if match:
            return match.group(1)  # TODO
        else:
            raise ValueError("No Python code block found in completion.")
    reward = 0.0
    tool_log_path = os.path.join(log_root_dir, f"toolusage-{QAid}.log")
    
    try:
        execute_found = False
        code = extract_code(predict_str)
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
            f.write(f"\n[QAid]{QAid}\n")
            if execute_found:
                f.write("\n[Code Includes Tools Usage]\n")
            else:
                f.write("\n[Code does not include Tools Usage]\n")
            f.write(f"code: \n{code}")
            f.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
    except Exception as e:
        with open(tool_log_path, "a+") as f:
            f.write(f"\n[QAid]{QAid}\n")
            f.write("\n[Code Extraction Failed or Parse Failed]\n\n")
            f.write(str(e) + "\n")
            f.write(f"\nCompletion Content: \n{predict_str}")
            f.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
    return reward

def format_reward(predict_str, step, QAid):
    """Reward function that checks if the completion has a specific format."""
    pattern1 = r"<code>(.*?)</code>" # no final_result but have correct tags
    pattern2 = r"(?s)<code>(?!\s*\bfinal_result\b).*?\bfinal_result\b\s*=.*?</code>"  # TODO - Done

    reward = 0.0
    if re.fullmatch(pattern2, predict_str, re.DOTALL):
        reward = 1.0    
    elif re.fullmatch(pattern1, predict_str, re.DOTALL):
        reward = 0.5  
    else:
        reward = 0.0
    # create timepoints as part of log names
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    # create log file
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_root_dir = os.path.join(f"{root_dir}/Grpo_Tools_Logs/Format", f"step_{step}-{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
    format_log_path = os.path.join(log_root_dir, f"format-{QAid}.log")
    with open(format_log_path, "a+") as f:
        f.write(f"--- Completion ---\n")
        f.write(predict_str + "\n")
        f.write(f"Reward: {reward}\n\n")
    return reward

def compute_score(predict_strs: List[str], ground_truths: List[str], format_weight: float = 0.2, 
                  usage_weight: float = 0.3, execution_weight: float = 0.2, accuracy_weight: float = 0.3,
                  step: Optional[int] = None, QAid: Optional[str] = None) -> List[Dict[str, float]]:
    if step is None:
        print("step is None, please check the input parameters")
    scores = []
    assert format_weight + usage_weight + execution_weight + accuracy_weight == 1.0, "The sum of weights must be equal to 1.0"
    
    for predict_str, ground_truth in zip(predict_strs, ground_truths):
        format_score = format_reward(predict_str, step, QAid)
        tool_usage_score = tool_usage_reward(predict_str, step, QAid)
        execution_score = execution_reward(predict_str, QAid, step)
        
        # execution_score[1] is the result of execution
        if execution_score[0] != 0.0:
            accuracy_score = accuracy_reward(execution_score[1], step=step, solution=ground_truth, QAid=QAid)
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