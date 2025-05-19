import os
import json
import requests
import json
import re
# --- Configuration ---
CODE_KEY_PREFIX = "code_ex" # e.g., code_ex01, code_ex02
MAX_CODE_EXECUTIONS_PER_ENTRY = 3 # Max number of code_exNN to check
EXECUTION_TIMEOUT_SECONDS = 120
INTERPRETOR_KEY = "interpreter"
DELAY_BETWEEN_REQUESTS = 0.5
MARAJO_SANDBOX_URL = "http://10.153.51.195:8080/api/sandbox/execute"
# --- End Configuration ---
#--- set random seed for reproduction ---
import transformers
seed = 42
transformers.set_seed(seed)
import random
random.seed(seed)
import torch
torch.manual_seed(seed)
torch.cuda.manual_seed(seed)
# ---------------------------------
root_dir = "./Rollout/Counting"
def numerical_sort_key(name):
        match = re.search(r'(\d+)', name)
        return int(match.group(1)) if match else float('inf')
sample_names = sorted(os.listdir(root_dir), key=numerical_sort_key) # 文件名顺序
total_samples = len(sample_names)


def filter_result(result_data: dict):
    """
    Picks the final result on success or the traceback on error.
    """
    status = result_data.get("status")
    if status == "success":
        if result_data.get("result") is not None:
            if not isinstance(result_data.get("result"), str):
                result_str = str(result_data["result"])
            else:
                result_str = result_data.get("result") # here
            return result_str, True
        stdout = result_data.get("stdout", "").strip()
        m = re.search(r"final_result:?[ \t]*(.+)", stdout)
        if m:
            return m.group(1).strip(), True
        else:
            no_result_finding = "Error: 'final_result' variable not found in output or not printed using the required format: print('final_result:', final_result)."
            return no_result_finding, False
    else:
        raw = result_data.get("error_message") or result_data.get("stderr") or result_data.get("stdout", "")
        return raw.split("\n--- Sys Path")[0].strip(), False
# initialization
exe_success, exe_num = 0, 0
acc_success, acc_num = 0, 0

# iterate through files in folder "./Rollout/Counting"
for i, sample_name in enumerate(sample_names,start=1):  # e.g. sample1,sample2 ...
    print(f"processing {i}/{total_samples} for {sample_name}.\n")
    sample_dir = os.path.join(root_dir, sample_name)
    if not os.path.isdir(sample_dir):
        print(f"The sample's file: {sample_dir} is not a folder! Please Check")
        continue

    idx_rollout = -1 
    import re
    for fname in os.listdir(sample_dir): # 列出当前sample文件夹中所有的rollout trajectory json文件
        m = re.match(r"rollouts_(\d+)\.json$", fname)
        if m:
            idx_rollout = max(idx_rollout, int(m.group(1)))
            
    load_path = os.path.join(sample_dir, f"rollouts_{idx_rollout}.json")
    with open(load_path, 'r', encoding='utf-8') as f: # 加载最新的rollout trajectory json文件
        json_samples = json.load(f) 
    
    total = len(json_samples) 
    # get code from rollouts(n) json file for this sample
    for idx, json_sample in enumerate(json_samples,start=1): # here json_samples is from `rollouts_x.json` file 
        # # after one rollout(json_sample) finished, total executed number +1 & total accurate number +1
        exe_num += 1
        acc_num += 1
        print(f" processing and executing {idx}/{total} code in {sample_name}")
        if "final_solution" in json_sample:
            exe_success += 1
            acc_success += 1
            print(f" The Trajectory stops extension because correct answer.\n")
            continue
        codes_keys = [k for k in json_sample.keys() if k.startswith("code_ex")]
        
        code_idx = -1
        for k in codes_keys:
            idx = int(k.replace("code_ex", ""))
            code_idx = max(code_idx, idx) 
        interpreter_key = INTERPRETOR_KEY + f"{code_idx}"    # the latest `interpreterid`` is consistent with `code_ex_id`
        code_text = json_sample[f"code_ex{code_idx}"]        # 获取最新的code text进行运行 从json文件中提取对应的 `code text`
        
        # remove <code> tags
        if code_text.strip().startswith("<code>"):
            code_text = code_text.replace("<code>", "").replace("</code>", "").strip()
            # Check if code still contains markdown-style block
            if code_text.strip().startswith("```"):
                json_sample[interpreter_key] = (
                    "Error: Do not use markdown formatting like ```python```. "
                    "Only wrap your code in <code> </code> tags without any other formatting."
                ) 
                continue  # Skip execution # 为了避免 <code> ``` python ``` </code> 的情况
            
            payload = {
            "code": code_text,
            "timeout": EXECUTION_TIMEOUT_SECONDS,
            "q_aid": json_sample["rolloutID"]
            }
            try:
                resp = requests.post(MARAJO_SANDBOX_URL, json=payload, timeout=EXECUTION_TIMEOUT_SECONDS)
                resp.raise_for_status()
                result_data = resp.json()
                status = result_data.get("status")
                filtered, result_existing = filter_result(result_data)
                if status == "success":
                    exe_success += 1 # execution rate + 1
                    if result_existing == True:
                        if filtered == json_sample["GT"]:
                            acc_success += 1 # accuracy rate + 1
                            json_sample["final_solution"] = filtered
                            # print(f"The final result of code: {filtered}; and the Ground Truth: {json_sample['GT']}, current acc_success_num: {acc_success}")
                        else:
                            json_sample[interpreter_key] = f"The code ran successfully, but the final result:{filtered} does not match the ground truth:{json_sample['GT']}. Please revise your solution."
                    else: #
                        json_sample[interpreter_key] = filtered
                # print(f"final result of execution: {filtered}\n")
                # print(f"all outputs from server: {result_data}\n")
                else: # problematic code case
                    json_sample[interpreter_key] = filtered
                #print(f"[{idx}/{total}] Received status={result_data.get('status')}, filtered result: {repr(filtered)}")
            except Exception as ex:
                print(f"[{idx}/{total}] Error during request or processing: {ex}")
                json_sample[interpreter_key] = str(ex)
        else:
            json_sample[interpreter_key] = "Error: Use <code> </code> tags only—do not include markdown (e.g., python), text, or explanations."
            
    print(f"up to current {i}-th sample, execution_rate:{exe_success}/{exe_num} and accuracy_rate:{acc_success}/{acc_num}.\n")    
    # save as new json file for rollouts
    new_json_name = f"rollouts_trajectory_{code_idx}.json"
    new_json_path = os.path.join(sample_dir, new_json_name)
    with open(new_json_path, 'w', encoding='utf-8') as f:
        json.dump(json_samples, f, ensure_ascii=False, indent=4)

    print(f"finish: {sample_name}, generating: {new_json_path}")
