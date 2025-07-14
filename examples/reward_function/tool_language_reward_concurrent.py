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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Union
import requests
from math_verify import parse, verify
import time
REMOTE_URL = "http://10.153.51.195:8080/api/sandbox/execute"

def detect_mode(completion: str) -> str:
    """
    1. <think>...</think>  <code>...</code>, without <answer>
    2. <think>...</think>  <answer>...</answer>, without <code>
    other cases are all invalid
    """
    s = completion.strip()
    code_pattern = r'^<think>.*?</think>\s*<code>.*?</code>\s*$'
    answer_pattern = r'^<think>.*?</think>\s*<answer>.*?</answer>\s*$'

    if '<code>' in s and '<answer>' in s:
        return 'invalid'
    if re.fullmatch(code_pattern, s, re.DOTALL):
        return 'code'
    if re.fullmatch(answer_pattern, s, re.DOTALL):
        return 'nl'
    return 'invalid'


def loose_match(a, b):
    # Convert both inputs to string, trim spaces, and lowercase
    a = str(a).strip().lower()
    b = str(b).strip().lower()

    # Remove articles ('the', 'a', 'an')
    def remove_articles(s):
        return re.sub(r'\b(the|a|an)\b', '', s).strip()

    a = remove_articles(a)
    b = remove_articles(b)
    # Remove extra whitespace
    a = re.sub(r'\s+', ' ', a)
    b = re.sub(r'\s+', ' ', b)

    # Map common synonyms to standard values
    synonym_map = {
        "yes": "true",
        "no": "false",
        "correct": "true",
        "incorrect": "false",
        "right": "true",
        "wrong": "false"
    }
    a = synonym_map.get(a, a)
    b = synonym_map.get(b, b)

    return a == b

def extract_boxed_answer(completion: str) -> Optional[str]:
    m = re.search(r"<answer>.*?\\boxed\{(.*?)\}.*?</answer>", completion, re.S)
    return m.group(1).strip() if m and m.group(1) else None

###########################
#### Accuracy Reward ######
###########################
def accuracy_reward(exec_result, response, step, solution, QAid, question, **kwargs):
    """
    """
    # detect output mode(code; nl; invalid)
    mode = detect_mode(response)
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    current_time = datetime.now().strftime("%d-%H-%M-%S")
    split = "validation" if step == "validation" else "train"
    step_str = f"step_{step}" if isinstance(step, int) else f"step_{step}"
    log_root_dir = os.path.join(root_dir, f"grpo_tools_logs/{split}/accuracy/{step_str}")
    
    answer_pred = None
    reward = 0.0
    acc_log_path = os.path.join(log_root_dir, f"invalid_accuracy_{current_time}-{QAid}.log")
    if mode == "code" and exec_result is not None:
        acc_log_path = os.path.join(log_root_dir, f"code_accuracy_{current_time}-{QAid}.log")
        try:
            # try to verify symbolic calculation
            parsed_result = parse(exec_result)
            parsed_solution = parse(solution)
            if float(verify(parsed_result, parsed_solution)) > 0:
                reward = 1.0
        except Exception:
            # symbolic calculation failed
            pass 
        
        if loose_match(exec_result, solution):
            reward = 1.0

    elif mode == "nl":
        acc_log_path = os.path.join(log_root_dir, f"nl_accuracy_{current_time}-{QAid}.log")
        answer_pred = extract_boxed_answer(response)
        if answer_pred is not None:
            try:
                if float(verify(parse(answer_pred), parse(solution))) > 0:
                    reward = 1.0
            except Exception:
                pass

            if loose_match(answer_pred, solution):
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
            f.write(f"nl_result: {answer_pred}\n")
            f.write(f"exec_result: {exec_result}\n")
            f.write(f"expected:    {solution}\n")
            f.write(f"question: \n{question}\n")
            f.write(f"response:\n{response}\n")
            f.write("=" * 30 + "\n\n")

    return reward

accuracy_reward.reward_type = "accuracy"

##########################
#### Execution Reward ####
##########################
def execution_reward(
    predict_str, 
    QAid, 
    step, 
    question,
    log_root_dir=None,
    timeout=120
):
    # detect output mode(code; nl; invalid)
    mode = detect_mode(predict_str)

    # CODE EXTRACTION
    def extract_code(completion):
        match = re.search(r"<code>(.*?)</code>", completion, re.DOTALL)
        return match.group(1) if match else None

    current_time = datetime.now().strftime("%d-%H-%M-%S")

    # logs file setting
    if log_root_dir is None:
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        split = "validation" if step == "validation" else "train"
        step_str = f"step_{step}"
        log_root_dir = os.path.join(root_dir, f"grpo_tools_logs/{split}/execution/{step_str}")

    #########################################
    # Natural Language mode or invalid
    if mode != "code":
        if (isinstance(step, str) and step == "validation") or (isinstance(step, int) and step % 2 == 0):
            os.makedirs(log_root_dir, exist_ok=True)
            non_code_mode_log_path = (
                os.path.join(log_root_dir, f"nl_{current_time}-{QAid}.log")
                if mode == "nl"
                else os.path.join(log_root_dir, f"invalid_{current_time}-{QAid}.log")
            )

            with open(non_code_mode_log_path, "a+", encoding="utf-8") as f:
                f.write(f"------------- non code mode: execution reward: 0.0\n -------------\n")
                f.write(f"question:\n{question}\n")
                f.write(f"model's response:\n{predict_str}\n")
                f.write(f"\nQAid: {QAid}\n")
                f.write("=" * 30 + " end " + "=" * 30 + "\n\n")

        return (0.0, None)
    #########################################
    code = extract_code(predict_str)
    if code is None:
        extraction_failed_log_path = os.path.join(
            log_root_dir, f"code_extraction_failed_{current_time}-{QAid}.log"
        )
        # code extraction failed
        if (isinstance(step, str) and step == "validation") or (isinstance(step, int) and step % 2 == 0):
            os.makedirs(log_root_dir, exist_ok=True)
            with open(extraction_failed_log_path, "a+", encoding="utf-8") as f:
                f.write(f"------------- code extraction failed: execution reward: 0.0\n -------------\n")
                f.write(f"model's response:\n{predict_str}\n")
                f.write(f"\nQAid: {QAid}\n")
                f.write("=" * 30 + " end " + "=" * 30 + "\n\n")
        return (0.0, None)
    #########################################
    def sandbox_execute(code, timeout, log_path, QAid):
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
            execution_time = result_data.get("execution_time")
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

                # Log success only if
                os.makedirs(log_path, exist_ok=True)
                success_log_path = os.path.join(log_path, f"success_execution_{current_time}-{QAid}.log")
                with open(success_log_path, "a+", encoding="utf-8") as df:
                    df.write("\n" + "=" * 30 + " new Completed Execution " + "=" * 30 + "\n")
                    df.write(f"question: \n{question}\n")
                    df.write(f"response: \n{predict_str}\n")
                    df.write("raw output\n" + output_raw + "\n\n")
                    df.write("generated final result\n" + str(output) + "\n\n")
                    df.write(f"\n\nexecution time : {execution_time}\n")
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
                        df.write("=" * 30 + "=" * 30 + "\n\n")
                        df.write(f"question: \n{question}\n")
                        df.write(f"response: \n{predict_str}\n")
                        df.write(f"\n\nexecution time : {execution_time}\n\n")
                        df.write("=" * 30 + " END " + "=" * 30 + "\n\n")
                return result

        except Exception as e:
            if (isinstance(step, str) and step == "validation") or (isinstance(step, int) and step % 2 == 0):
                os.makedirs(log_path, exist_ok=True)
                with open(os.path.join(log_path, f"bug_exec_{current_time}-{QAid}.log"), "a+", encoding="utf-8") as lf:
                    lf.write("\n" + "=" * 30 + f" QAid={QAid} error " + "=" * 30 + "\n")
                    lf.write(f"\n\nsandbox execution reward function failed {e}\n\n")
                    lf.write("code:\n" + code + "\n")
                    lf.write("=" * 30 + "\n\n")
            return (0.0, None)

    final_result = sandbox_execute(code, timeout=timeout, log_path=log_root_dir, QAid=QAid)
    return final_result
    
execution_reward.reward_type = "execution"

### Concurrent Batch Execution Reward

def batch_execution_reward(
    predict_strs, QAids, steps, questions, max_workers=8, log_root_dir=None
):
    # need to loop n times
    n = len(predict_strs)
    assert len(QAids) == n and len(steps) == n and len(questions) == n

    def task(i):
        return execution_reward(
            predict_str=predict_strs[i],
            QAid=QAids[i],
            step=steps[i],
            question=questions[i],
            log_root_dir=log_root_dir
        )
    results = [None] * n
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(task, i): i for i in range(n)}
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()
    return results

###########################
#### Tool Usage Reward ####
###########################
def tool_usage_reward(predict_str, step, QAid):
    """
    Check whether the generated code uses any registered tools:
    - It must import a tool module
    - It must create an instance of a known tool class
    - It must call .execute()
    """
    mode = detect_mode(predict_str)
    start_time = time.time()
    # Create root log directory path like: .../train/tools_usage/reward/step_2/
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    split = "validation" if step == "validation" else "train"
    step_str = f"step_{step}" if isinstance(step, int) else f"step_{step}"
    current_time = datetime.now().strftime("%d-%H-%M-%S")
    if (isinstance(step, str) and step == "validation") or (isinstance(step, int) and step % 2 == 0):
        log_root_dir = os.path.join(root_dir, f"grpo_tools_logs/{split}/tools_usage/{step_str}")
        os.makedirs(log_root_dir, exist_ok=True)

        # Log file path
        tool_log_path = os.path.join(log_root_dir, f"toolusage_{current_time}-{QAid}.log")
    
    # diasble tool usage reward when NL mode: return 0.0
    if mode != "code":
       # nl mode or invalid
        reward = 0.0
        if (isinstance(step, str) and step == "validation") or (isinstance(step, int) and step % 2 == 0):
            elapsed_time = time.time() - start_time
            with open(tool_log_path, "a+") as f:
                f.write(f"\nQAid:{QAid}\n")
                f.write("\nnatural language mode or invalid response\n\n")
                f.write(f"\ncompletion Content: \n{predict_str}\n")
                f.write(f"\n[execution time] {elapsed_time:.2f}s\n")
                f.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")
        return reward
    
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
            elapsed_time = time.time() - start_time
            with open(tool_log_path, "a+") as f:
                f.write(f"\n[QAid]{QAid}\n")
                if execute_found:
                    f.write("\n[Code Includes Tools Usage]\n")
                else:
                    f.write("\n[Code does not include Tools Usage]\n")
                f.write(f"prediction: \n{predict_str}\n")
                f.write(f"\n[execution time] {elapsed_time:.2f}s\n")
                f.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")

    except Exception as e:
        if (isinstance(step, str) and step == "validation") or (isinstance(step, int) and step % 2 == 0):
            elapsed_time = time.time() - start_time
            with open(tool_log_path, "a+") as f:
                f.write(f"\nQAid:{QAid}\n")
                f.write("\nCode Extraction Failed or Parse Failed\n\n")
                f.write(str(e) + "\n")
                f.write(f"\nCompletion Content: \n{predict_str}\n")
                f.write(f"\n[execution time] {elapsed_time:.2f}s\n")
                f.write("\n" + "=" * 30 + " END " + "=" * 30 + "\n\n")

    return reward

#######################
#### Format Reward ####
#######################

def format_reward(predict_str, step, QAid):
    """Reward function that checks if the completion has a specific format."""
    start_time = time.time()
    # code approach
    pattern_code_loose  = r"(?s)<think>.*?</think>\s*<code>.*?</code>"
    pattern_code_strict = r"(?s)<think>.*?</think>\s*<code>.*?\bfinal_result\b\s*=.*?</code>"
    # nl approach
    pattern_nl_loose    = r"(?s)<think>.*?</think>\s*<answer>.*?</answer>"
    pattern_nl_strict   = r"(?s)<think>.*?</think>\s*<answer>.*?\\boxed\{.*?\}.*?</answer>"

    
    reward = 0.0
    if re.fullmatch(pattern_code_strict, predict_str, re.DOTALL) \
       or re.fullmatch(pattern_nl_strict, predict_str, re.DOTALL):
        reward = 1.0
    elif re.fullmatch(pattern_code_loose, predict_str, re.DOTALL) \
         or re.fullmatch(pattern_nl_loose, predict_str, re.DOTALL):
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
        elapsed_time = time.time() - start_time
        log_root_dir = os.path.join(root_dir, f"grpo_tools_logs/{split}/format/{step_str}")
        os.makedirs(log_root_dir, exist_ok=True)
        format_log_path = os.path.join(log_root_dir, f"format_{current_time}-{QAid}.log")

        with open(format_log_path, "a+") as f:
            f.write(f"--- Completion ---\n")
            f.write(predict_str + "\n")
            f.write(f"reward: {reward}\n\n")
            f.write(f"[execution time] {elapsed_time:.2f}s\n")
    return reward

#############################
# Overall Score Computation #
#############################
def compute_score(predict_strs: List[str], ground_truths: List[str], format_weight: float = 0.2, 
                  usage_weight: float = 0.3, execution_weight: float = 0.2, accuracy_weight: float = 0.3, nl_accuracy_weight: float = 0.5, 
                  step = None, QAids = None, questions = None) -> List[Dict[str, float]]:
    scores = []
    n = len(predict_strs)
    assert format_weight + usage_weight + execution_weight + accuracy_weight == 1.0, "The sum of weights must be equal to 1.0"
    modes = [detect_mode(p) for p in predict_strs]
    
    code_count = sum(m == "code" for m in modes)
    nl_count   = sum(m == "nl" for m in modes)
    invalid_count = sum(m == "invalid" for m in modes)
    code_ratio = code_count / n
    nl_ratio   = nl_count / n
    invalid_ratio = invalid_count / n

    exec_reward = batch_execution_reward(
        predict_strs=predict_strs,
        QAids=QAids,
        steps=[step]*n,
        questions=questions,
        max_workers=24
    )

    for i in range(n):
        predict_str  = predict_strs[i]
        ground_truth = ground_truths[i]
        QAid         = QAids[i]
        question     = questions[i]
        mode         = modes[i]
        # execution_scores[i]： (reward, exec_output or None)
        exec_score, exec_output = exec_reward[i]

        format_score     = format_reward(predict_str, step, QAid)
        tool_usage_score = tool_usage_reward(predict_str, step, QAid)

        # code mode: exec_output，nl / invalid mode: None
        accuracy_score = accuracy_reward(
            exec_output,            # exec_result
            response   = predict_str,
            step       = step,
            solution   = ground_truth,
            QAid       = QAid,
            question   = question
        )
        if mode == "code":
        # 3. overall
            overall_score = (
                format_weight   * format_score     +
                usage_weight    * tool_usage_score +
                execution_weight* exec_score      +
                accuracy_weight * accuracy_score
            )
        elif mode == "nl":
            overall_score = nl_accuracy_weight * accuracy_score + (1 - nl_accuracy_weight) * format_score
        else:
            overall_score = 0.0

        scores.append(
            {
                "overall":    overall_score,
                "format":     format_score,
                "accuracy":   accuracy_score,
                "tool_usage": tool_usage_score, # disabled in natural language
                "execution":  exec_score, # disabled in natural language
                "code_ratio": code_ratio,
                "nl_ratio":   nl_ratio,
                "invalid_ratio": invalid_ratio,
                "mode": mode,
            }
        )
    return scores