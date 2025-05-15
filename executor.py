import os
import json
import subprocess
import sys
import tempfile
import traceback
import re
# --- Configuration ---
ROOT_DIR = "./Rollout/Counting"
CODE_KEY_PREFIX = "code_ex" # e.g., code_ex01, code_ex02
MAX_CODE_EXECUTIONS_PER_ENTRY = 3 # Max number of code_exNN to check
EXECUTION_TIMEOUT_SECONDS = 120
# --- End Configuration ---
import transformers
REMOTE_URL   = "http://10.153.51.195:8080/api/sandbox/execute"

seed = 42
transformers.set_seed(seed)
root_dir = "./Rollout/Counting"
sample_names = os.listdir(root_dir)
total_samples = len(sample_names)
# iterate through files in folder "./Rollout/Counting"
for i, sample_name in enumerate(sample_names):  # e.g. sample1,sample2 ...
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
    

    # get code from rollouts(n) json file for this sample
    for idx, json_sample in enumerate(json_samples):
        # TODO 
        print(f" processing and executing {idx}/{len(json_samples)} code in {sample_name}")
        codes_keys = [k for k in json_sample.keys() if k.startswith("code_ex")]
        
        code_idx = -1
        for k in codes_keys:
            idx = int(k.replace("code_ex", ""))
            code_idx = max(code_idx, idx)
        code_text = json_sample[f"code_ex{code_idx}"] # 获取最新的code text进行运行 从json文件中提取对应的code text
        
        # remove <code> tags
        if code_text.strip().startswith("<code>"):
            code_text = code_text.replace("<code>", "").replace("</code>", "").strip()
            # Check if code still contains markdown-style block
            if code_text.strip().startswith("```"):
                json_sample[f'interpretor{code_idx}'] = (
                    "Error: Do not use markdown formatting like ```python```. "
                    "Only wrap your code in <code> </code> tags without any other formatting."
                ) 
                continue  # Skip execution # 为了避免 <code> ``` python ``` </code> 的情况
            
            # write and create new temporary files
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tmp:
                tmp.write(code_text)
                tmp_path = tmp.name

            try:
                # using python interpreter and use conda env
                proc = subprocess.run(
                    [sys.executable, tmp_path],
                    env=os.environ.copy(),  # current conda env using
                    capture_output=True,
                    text=True,
                    timeout=EXECUTION_TIMEOUT_SECONDS
                )
                if proc.returncode == 0:
                    # success execution
                    output = proc.stdout.strip()
                    # Look for the line containing 'final_result'
                    final_result = None
                    for line in output.splitlines():
                        match = re.match(r"final_result:\s*(.*)", line)
                        if match:
                            final_result = match.group(1)
                            break

                    if final_result is not None:
                        json_sample[f'interpretor{code_idx}'] = final_result
                    else:
                        json_sample[f'interpretor{code_idx}'] = "Error: 'final_result' variable not found in output or not printed using the required format: print('final_result:', final_result)."
                else:
                    json_sample[f'interpretor{code_idx}'] = proc.stderr.strip()
            except Exception:
                # capture error and warning
                json_sample[f'interpretor{code_idx}'] = traceback.format_exc()
            finally:
                # clear temp file
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        else:
            json_sample[f'interpretor{code_idx}'] = "Error: Use <code> </code> tags only—do not include markdown (e.g., python), text, or explanations."

    # save as new json file for rollouts
    new_json_name = f"rollouts_trajectory_{code_idx}.json"
    new_json_path = os.path.join(sample_dir, new_json_name)
    with open(new_json_path, 'w', encoding='utf-8') as f:
        json.dump(json_samples, f, ensure_ascii=False, indent=4)

    print(f"finish: {sample_name}, generating: {new_json_path}")
