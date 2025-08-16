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
from collections import defaultdict, Counter
from io import StringIO
import contextlib
import multiprocessing
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Union
import requests
from math_verify import parse, verify
import time
import json


def extract_options(text: str) -> dict:
    # Match patterns like A. xxx, A) xxx, A: xxx, A xxx, etc., supporting multiple options in one line
    # Avoid matching cases like 'AA'
    # Option letters are recognized if they appear alone and are followed by a separator (., :, etc.)
    # Supports both multiple options per line (e.g., A. North, B. South, ...) and one option per line
    # Output format: {"A": "North", ...}
    option_pattern = r"([A-Za-z])\s*[\.．:：\)）、】\]]?\s*([^A-Za-z0-9\n,;，；。]{0,10}[A-Za-z0-9\u4e00-\u9fa5 \-]+)"

    # Find all matches (each option can contain spaces, Chinese characters, digits, hyphens)
    matches = re.findall(option_pattern, text)
    # print(matches) # Uncomment for debugging if needed

    # Clean up trailing punctuation from content
    option_dict = {}
    for label, content in matches:
        label = label.upper()
        content = content.strip(" ,;，；。)")
        # Only add to the dictionary if the content is not empty (to avoid false matches)
        if content:
            option_dict[label] = content

    return option_dict

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
    a = re.sub(r'\s+', ' ', a).strip()
    b = re.sub(r'\s+', ' ', b).strip()

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


###########################
#### Accuracy Reward ######
###########################
def accuracy_reward(response, step, solution, QAid, question, root_dir= "/workspace/models/logs", **kwargs):
    """
    """

    if root_dir is None:
        root_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    current_time = datetime.now().strftime("%d-%H-%M-%S")
    split      = "validation" if step == "validation" else "train"
    step_str   = f"step_{step}" if isinstance(step, int) else f"step_{step}"
    log_root   = os.path.join(root_dir, f"grpo_tools_logs/{split}/accuracy/{step_str}")

    # get options map
    options_map = extract_options(question)

    answer_pred = None
    reward = 0.0
    answer_pred = response

    try:
        if float(verify(parse(answer_pred), parse(solution))) > 0:
            reward = 1.0
    except Exception:
        pass
    if loose_match(answer_pred, solution):
        reward = 1.0

    result_tag = "correct" if reward == 1.0 else "wrong"
    if answer_pred:
        file_prefix = f"{result_tag}_accuracy_{current_time}-{QAid}.log"
    else:  # invalid
        file_prefix = f"invalid_accuracy_{current_time}-{QAid}.log"
    acc_log_path = os.path.join(log_root, file_prefix)


    os.makedirs(log_root, exist_ok=True)
    with open(acc_log_path, "a", encoding="utf-8") as f:
        f.write(f"\nQAid: {QAid}\n")
        f.write("\ncorrect result\n\n" if reward == 1.0 else "\nwrong result\n\n")
        f.write(f"result: {answer_pred}\n")
        f.write(f"expected:    {solution}\n")
        f.write(f"question: \n{question}\n")
        f.write(f"response:\n{response}\n")
        f.write("=" * 30 + "\n\n")

    return reward



def compute_score(
    predict_strs: List[str],
    ground_truths: List[str],
    format_weight: float = 0.2,
    usage_weight: float = 0.1,
    execution_weight: float = 0.2,
    accuracy_weight: float = 0.5,
    nl_accuracy_weight: float = 0.5,
    think_length_weight: float = 0.0,
    code_think_length_weight:float = 0.25,
    step = None,
    QAids = None,
    questions = None,
    root_dir = None,
    index = None,
    diversity_scale = False,
) -> List[Dict[str, float]]:
    scores = []
    n = len(predict_strs)
    for i in range(n):
        predict_str  = predict_strs[i]
        ground_truth = ground_truths[i]
        QAid         = QAids[i]
        question     = questions[i]

        accuracy = accuracy_reward(response=predict_str, step=step, solution = ground_truth, QAid = QAid, question=question, root_dir=root_dir, )
        overall_score = accuracy
        
        scores.append(
            {
                "overall": overall_score,
                "accuracy": accuracy,
            }
        )
    return scores
