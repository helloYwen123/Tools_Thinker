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
    try:
        reliability_guard()
        buffer = StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            exec_globals = {"final_result": None}
            exec(code, exec_globals)
        output_raw = buffer.getvalue()
        output = exec_globals.get("final_result", None)
        
        reward = 0.0
        if output is not None:
            reward = 1.0
            success_log_path = os.path.join(log_path, "success_execution.log")
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
            with open(debug_log_path, "a+") as df:
                df.write("\n[None RESULT]\n")
                df.write("[Successful Execution but Get None RESULT]\n")
                df.write("[EXEC CODE]\n")
                df.write(code + "\n")
                df.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
        result.append((reward, output))
    except Exception as e:
        debug_log_path = os.path.join(log_path, "bug_exec.log")
        with open(debug_log_path, "a+") as df:
            df.write("\n[Execution Failed]\n")
            df.write(str(e) + "\n")
            df.write(f"code: \n{code}\n")
            df.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
        result.append((0.0, None))
    finally:
        signal.alarm(0)

def execution_reward(predict_str, QAid, step):
    def extract_code(completion):
        match = re.search(r"<command>(.*?)</command>", completion, re.DOTALL)
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

    manager = multiprocessing.Manager()
    result = manager.list()
    p = multiprocessing.Process(target=unsafe_execute, args=(code, 120, result, log_root_dir))
    p.start()
    p.join(121)
    if p.is_alive():
        p.kill()

    final_result = result[0] if result else (0.0, None)
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
        match = re.search(r"<command>(.*?)</command>", completion, re.DOTALL)
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
            f.write(f"\nCompletion Content: \n{predict_str}")
            f.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
    return reward

def format_reward(predict_str, step, QAid):
    """Reward function that checks if the completion has a specific format."""
    pattern1 = r"<command>(.*?)</command>" # no final_result but have correct tags
    pattern2 = r"(?s)<command>(?!\s*\bfinal_result\b).*?\bfinal_result\b\s*=.*?</command>"  # TODO - Done

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

def compute_score(predict_strs: List[str], ground_truths: List[str], format_weight: float = 0.3, 
                  usage_weight: float = 0.4, execution_weight: float = 0.3, 
                  step: Optional[int] = None, QAid: Optional[str] = None) -> List[Dict[str, float]]:
    if step is None:
        print("step is None, please check the input parameters")
    scores = []
    assert format_weight + usage_weight + execution_weight == 1.0, "The sum of weights must be equal to 1.0"
    
    for predict_str, ground_truth in zip(predict_strs, ground_truths):
        format_score = format_reward(predict_str, step, QAid)
        tool_usage_score = tool_usage_reward(predict_str, step, QAid)
        execution_score = execution_reward(predict_str, QAid, step)
        overall_score =  format_weight * format_score + usage_weight * tool_usage_score + execution_weight * execution_score[0]
        
        scores.append(
            {
                "overall": overall_score,
                "format": format_score,
                "tool_usage": tool_usage_score,
                "execution": execution_score[0],
            }
        )
    return scores