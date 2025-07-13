import torch
import json
import requests
from oumi.core.configs import InferenceConfig, EvaluationConfig
from oumi.core.types import Conversation, Message, Role
from oumi.inference import VLLMInferenceEngine
from oumi.builders import build_processor, build_tokenizer
from oumi.core.configs import ModelParams
from oumi.datasets import VLJsonlinesDataset
from oumi.core.registry import register_evaluation_function
from oumi.core.evaluation import Evaluator
from oumi.core.evaluation import Evaluator
import re
import os
from tqdm import tqdm 
#--- set random seed for reproduction ---
import transformers,random
import numpy as np
seed = 42
transformers.set_seed(seed)
random.seed(seed)
np.random.seed(seed)
torch.manual_seed(seed)
torch.cuda.manual_seed(seed)
print(f"Random Seed setting finished.")
#---------------------------------
from datetime import datetime

model_name = "Qwen/Qwen2.5-VL-7B-Instruct"
tokenizer = build_tokenizer(ModelParams(model_name=model_name))
processor = build_processor(model_name, tokenizer, trust_remote_code=True)

# Load the dataset
evaluation_dataset = VLJsonlinesDataset(dataset_path="/workspace/ywen_ws/mix_datasets/sft_training_doublemodes.jsonl",
                             tokenizer=tokenizer,
                             processor=processor)

# Iterate through the dataset and print conversations
for i in range(1):
   print(evaluation_dataset.conversation(i))

# For Debug
EXECUTION_TIMEOUT_SECONDS = 120
MARAJO_SANDBOX_URL = "http://10.153.51.195:8080/api/sandbox/execute"
def server_api(payload):
    try:
        resp = requests.post(MARAJO_SANDBOX_URL, json=payload, timeout=EXECUTION_TIMEOUT_SECONDS)
        resp.raise_for_status()
        result_data = resp.json()
        status = result_data.get("status")
        if status == "success":
            if result_data.get("result") is not None:
                    exec_result = result_data.get("result") # here
                    return exec_result,0
            stdout = result_data.get("stdout", "").strip()
            m = re.search(r"final_result:?[ \t]*(.+)", stdout)
            if m:
                exec_result = m.group(1).strip()
                
                return exec_result,1
            else:
                exec_result = "Error: 'final_result' variable not found in output."
                return exec_result,2
        else:
            exec_result = result_data.get("error_message") or result_data.get("stderr") or result_data.get("stdout", "")
            return exec_result,3
    except Exception as ex:
        print(f"Error during request or processing: {ex}")
        exec_result = "Error during request or processing"
        return exec_result,4

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

def detect_mode(txt: str) -> str:
    """: code / nl / invalid"""
    txt = txt.strip()
    code_ok = re.fullmatch(r"<think>.*?</think>\s*<code>.*?</code>", txt, re.S)
    ans_ok  = re.fullmatch(r"<think>.*?</think>\s*<answer>.*?</answer>", txt, re.S)
    if code_ok and "<answer>" not in txt:
        return "code"
    if ans_ok and "<code>" not in txt:
        return "nl"
    return "invalid"

def extract_boxed_answer(txt: str):
    m = re.search(r"<answer>.*?\\boxed\{(.*?)\}.*?</answer>", txt, re.S)
    return m.group(1).strip() if m else None

@register_evaluation_function("Counting_tools_evaluation")
def Counting_tools_evaluation(inference_engine, dataset):
    """Custom evaluation that同时处理 code / nl 两种模式."""
    conversations = inference_engine.infer(dataset.conversations())

    success_cnt, acc_cnt = 0, 0
    logs = []

    # 统计三种模式数量
    mode_counter = {"code": 0, "nl": 0, "invalid": 0}

    for conv in tqdm(conversations, desc="Evaluating", unit="conv"):
        response: str = conv.last_message().content.strip()
        mode = detect_mode(response)
        mode_counter[mode] += 1

        correctness = False
        success = False
        exec_result, case = "N/A", 5      # 默认 case=5: 格式 / 其它错误

        # -------- code 模式 --------
        if mode == "code":
            code_block = re.search(r"<code>(.*?)</code>", response, re.S)
            if code_block:
                code = code_block.group(1).strip()
                payload = {"code": code, "timeout": EXECUTION_TIMEOUT_SECONDS, "q_aid": None}
                exec_result, case = server_api(payload)
            else:
                exec_result = "Code Extraction Error"
                case = 5

            # 成功判定：case 不在 3/4/5
            if case not in (3, 4, 5):
                success = True
                success_cnt += 1

        # -------- nl 模式 --------
        elif mode == "nl":
            answer_pred = extract_boxed_answer(response)
            exec_result = answer_pred if answer_pred is not None else "Answer Extraction Error"
            success = True               # 无执行过程，一律成功
            success_cnt += 1

        # -------- invalid --------
        else:
            exec_result = "Format Error"
            # case=5 已保留，success=False

        # -------- accuracy 计算 --------
        if exec_result is not None:
            if loose_match(exec_result, conv.metadata["ground_truth"]):
                correctness = True
                acc_cnt += 1

        user_msg = conv.messages[1]
        question = user_msg.text_content_items[0].content if user_msg.text_content_items else None

        logs.append({
            "conversation_id": conv.conversation_id,
            "mode": mode,
            "question": question,
            "response": response,
            "exec_result": exec_result,
            "label": conv.metadata["ground_truth"],
            "case": case,
            "correctness": correctness,
            "success": success
        })

    n = len(conversations)
    exe_rate = success_cnt / n
    acc_rate = acc_cnt / n

    # 比例统计
    ratios = {f"{m}_ratio": mode_counter[m] / n for m in mode_counter}

    # 写日志
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    os.makedirs("./output", exist_ok=True)
    with open(f"./output/eval_log-{ts}.json", "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)

    # 统一返回
    return {"exe_rate": exe_rate, "acc_rate": acc_rate, **ratios}


yaml_path = "evaltools.yaml"
config = EvaluationConfig.from_yaml(yaml_path)

evaluator = Evaluator()
results = evaluator.evaluate(config, dataset=evaluation_dataset)

custom_task_results = results[0].get_results()
print("exe_rate:", custom_task_results["exe_rate"])
print("acc_rate:", custom_task_results["acc_rate"])
print("code_ratio:", custom_task_results["code_ratio"])
print("nl_ratio:", custom_task_results["nl_ratio"])
print("invalid_ratio:", custom_task_results["invalid_ratio"])
print("Execution duration in sec:", results[0].elapsed_time_sec)

