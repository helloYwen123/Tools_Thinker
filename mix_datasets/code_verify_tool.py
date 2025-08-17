import json
import re
import requests
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
import textwrap

JSONL_PATH = 'mix_train/multi_tools_qa_dirty_correct(106).jsonl'  # 替换你的文件路径
MARAJO_SANDBOX_URL = "http://10.153.51.195:8080/api/sandbox/execute"  # 替换成你的服务器url
EXECUTION_TIMEOUT_SECONDS = 120
FAILED_LIST_PATH = "failed_cases.json"
MAX_WORKERS = 8

def normalize_code(raw: str) -> str:
    """只做一次 textwrap.dedent,然后去掉首尾空行。"""
    code = textwrap.dedent(raw)
    lines = code.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)

def filter_result(result_data: dict):
    import re
    status = result_data.get("status")
    if status == "success":
        if result_data.get("result") is not None:
            if not isinstance(result_data.get("result"), str):
                result_str = str(result_data["result"])
            else:
                result_str = result_data.get("result")
            return result_str, True
        stdout = result_data.get("stdout", "").strip()
        m = re.search(r"final_result:?[ \t]*(.+)", stdout)
        if m:
            return m.group(1).strip(), True
        else:
            no_result_finding = "OUTPUT VARIABLE MISSING: 'final_result' variable not found in code."
            return no_result_finding, False
    else:
        raw = result_data.get("error_message") or result_data.get("stderr") or result_data.get("stdout", "")
        return raw.split("\n--- Sys Path")[0].strip(), False

# Step 1: start loading
with open(JSONL_PATH, 'r', encoding='utf-8') as f:
    entries = [json.loads(line) for line in f]

def single_entry_task(idx_entry):
    idx, entry = idx_entry
    out_text = entry.get("messages", [])[-1]["content"]
    m = re.search(r"<code>(.*?)</code>", out_text, flags=re.S)
    if not m:
        return {
            "idx": idx,
            "conversation_id": entry.get("conversation_id", f"entry_{idx}"),
            "reason": "missing <code> block"
        }, False

    raw_code = m.group(1)
    code = normalize_code(raw_code) 

    if code.strip().startswith("```"):
        return {
            "idx": idx,
            "conversation_id": entry.get("conversation_id", f"entry_{idx}"),
            "reason": "FORMAT ERROR: Markdown code block detected"
        }, False
    payload = {
        "code": code,
        "timeout": EXECUTION_TIMEOUT_SECONDS,
        "q_aid": entry.get("conversation_id", f"entry_{idx}")
    }
    try:
        resp = requests.post(MARAJO_SANDBOX_URL, json=payload, timeout=EXECUTION_TIMEOUT_SECONDS)
        resp.raise_for_status()
        result_data = resp.json()
        filtered, result_existing = filter_result(result_data)
        if result_data.get("status") == "success" and result_existing:
            return None, True
        else:
            return {
                "idx": idx,
                "conversation_id": entry.get("conversation_id", f"entry_{idx}"),
                "code": code,
                "filter_result": filtered,
                "result_existing": result_existing,
                "status": result_data.get("status"),
                "raw_result": result_data,
            }, False
    except Exception as ex:
        return {
            "idx": idx,
            "conversation_id": entry.get("conversation_id", f"entry_{idx}"),
            "code": code,
            "exception": str(ex),
            "status": "exception",
        }, False

# Step 2: concurrently processing
success_count = 0
failed_list = []

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    all_futures = []
    for idx_entry in enumerate(entries):
        all_futures.append(executor.submit(single_entry_task, idx_entry))
    for future in tqdm(as_completed(all_futures), total=len(all_futures), desc="Concurrent Processing"):
        failed_case, success = future.result()
        if success:
            success_count += 1
        elif failed_case is not None:
            failed_list.append(failed_case)

total_count = len(entries)

print(f"\nExecution success rate: {success_count}/{total_count} = {success_count/total_count:.2%}")

# 保存失败案例
if failed_list:
    with open(FAILED_LIST_PATH, "w", encoding="utf-8") as fw:
        json.dump(failed_list, fw, ensure_ascii=False, indent=2)

    print(f"Failed cases saved to {FAILED_LIST_PATH}")
    print(f"Number of failed cases: {len(failed_list)}")
    print("Sample failed case:")
    print(json.dumps(failed_list[0], ensure_ascii=False, indent=2))
