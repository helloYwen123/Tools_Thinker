import requests
import json
import time
import re

# --- Configuration ---
MARAJO_SANDBOX_URL = "http://10.153.51.195:8080/api/sandbox/execute"
EXECUTION_TIMEOUT = 60  # seconds
INPUT_JSON_PATH = "/home/stud/syang/docker_dataset/Rollout—7BQwen2.5/Counting/sample_0/rollouts_2.json"
# Change this name to whatever key you need (e.g., "interpretor1")
INTERPRETOR_KEY = "remote_sandbox"
CODE_FIELD = "code_ex1"
OUTPUT_JSON_PATH = "/home/stud/syang/docker_dataset/Rollout—7BQwen2.5/Counting/sample_0/syang_rollouts_1.json"
DELAY_BETWEEN_REQUESTS = 0.5  # seconds


def extract_code(wrapper: str) -> str:
    """
    Extracts the inner content between <code> and </code> tags.
    Raises ValueError if no such section is found.
    """
    match = re.search(r"<code>\s*(.*?)\s*</code>", wrapper, re.S)
    if not match:
        raise ValueError("No <code>...</code> section found")
    return match.group(1)


def filter_result(result_data: dict):
    """
    Picks the final result on success or the traceback on error.
    """
    status = result_data.get("status")
    if status == "success":
        if result_data.get("result") is not None:
            return result_data["result"]
        stdout = result_data.get("stdout", "").strip()
        m = re.search(r"final_result:?[ \t]*(.+)", stdout)
        if m:
            return m.group(1).strip()
        return stdout
    else:
        raw = result_data.get("error_message") or result_data.get("stderr") or result_data.get("stdout", "")
        return raw.split("\n--- Sys Path")[0].strip()


def main():
    # Load the rollout file containing many code_ex1 entries
    with open(INPUT_JSON_PATH, 'r', encoding='utf-8') as f:
        entries = json.load(f)

    total = len(entries)
    print(f"Starting processing of {total} entries...")

    for idx, entry in enumerate(entries, start=1):
        try:
            wrapper = entry.get(CODE_FIELD, "")
            code_to_run = extract_code(wrapper)
            print(f"[{idx}/{total}] Extracted code snippet (first 60 chars): {repr(code_to_run[:60])}...")
        except ValueError as e:
            print(f"[{idx}/{total}] Skipping entry: {e}")
            entry[INTERPRETOR_KEY] = ""
            continue

        # Build a simple counter-based request ID
        request_id = f"req_{idx}"
        payload = {
            "code": code_to_run,
            "timeout": EXECUTION_TIMEOUT,
            "q_aid": request_id
        }
        print(f"[{idx}/{total}] Sending payload with request_id={request_id}")

        try:
            resp = requests.post(MARAJO_SANDBOX_URL, json=payload, timeout=EXECUTION_TIMEOUT + 15)
            resp.raise_for_status()
            result_data = resp.json()
            filtered = filter_result(result_data)
            entry[INTERPRETOR_KEY] = filtered
            print(f"[{idx}/{total}] Received status={result_data.get('status')}, filtered result: {repr(filtered)}")
        except Exception as ex:
            print(f"[{idx}/{total}] Error during request or processing: {ex}")
            entry[INTERPRETOR_KEY] = str(ex)

        time.sleep(DELAY_BETWEEN_REQUESTS)

    # Write out the augmented JSON
    print(f"Writing results to {OUTPUT_JSON_PATH}")
    with open(OUTPUT_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)

    print("Done.")


if __name__ == '__main__':
    main()