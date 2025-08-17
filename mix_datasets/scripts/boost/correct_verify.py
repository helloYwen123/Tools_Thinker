#!/usr/bin/env python3
# coding: utf-8

"""
Usage:
    python check_qa_response.py --in input.jsonl --out checked.jsonl --backend openai
    # or
    python check_qa_response.py --in input.jsonl --out checked.jsonl --backend gemini
"""

import json, os, argparse, re
from pathlib import Path
from typing import Any, Dict, List
import openai
from tqdm import tqdm
import yaml
import base64
import shutil
import random,time
from pathlib import Path
from PIL import Image
from google import genai
from google.genai import types

# ---------------- Review Prompt -----------
REVIEW_PROMPT = """
You are an expert reviewer.

Given the following spatial-reasoning question and a model's response (including code and reasoning), note that the model is attempting to solve a visual problem by writing code that uses visual APIs/tools.

your job is:
1. Critically analyze whether the response is logically sound, and whether the code genuinely solves the task according to the question, not just assigns a value to 'final_result' by subjective guess.
2. If the model assigns a value to 'final_result' without rigorous code or logic, mark it as wrong and explain why.
3. If the response is correct and all reasoning steps and code are well justified, mark as correct and explain why.

Return only in the format:
<review>
result: correct/wrong
reason: <short reason>
</review>
----

The API metadata used by models:
{metadata}

Question:
{question}

Response:
{response}
"""

def build_messages_openai(question, response,api_meta_str):
    prompt = REVIEW_PROMPT.format(question=question, response=response, metadata =api_meta_str)
    return [
        {"role": "system", "content": "You are a careful, detail-oriented reviewer."},
        {"role": "user", "content": prompt}
    ]

def build_messages_gemini(question, response,api_meta_str):
    prompt = REVIEW_PROMPT.format(question=question, response=response, metadata = api_meta_str)
    print("-----PROMPT START-----\n", prompt, "\n-----PROMPT END-----")
    print("-----Question START-----\n", question, "\n-----Question END-----")
    print("-----MODEL OUTPUT-----\n", response, "\n-----END-----")
    return [prompt]

def review_with_openai(question, response, api_meta_str ,client, model="gpt-4o"):
    messages = build_messages_openai(question, response, api_meta_str)
    r = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.3,
        max_tokens=300,
    )
    return r.choices[0].message.content.strip()

def review_with_gemini(question, response, api_meta_str, client, system_prompt):
    contents = build_messages_gemini(question, response, api_meta_str)
    r = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config={
            "system_instruction": system_prompt,
            "temperature": 0.3,
        }
    )
    return r.text.strip()

def load_tool_data(conf):
    active_tool_names = conf.get("available_tools", [])  #
    full_toolbox_metadata = conf.get("toolbox_metadata", {})

    filtered_metadata_dict = {
        tool_name: full_toolbox_metadata[tool_name]
        for tool_name in active_tool_names
        if tool_name in full_toolbox_metadata
    }

    for tool_name in active_tool_names:
        if tool_name not in full_toolbox_metadata:
            print(f"Warning: Tool '{tool_name}' listed in available_tools but not found in toolbox_metadata.")

    return active_tool_names, filtered_metadata_dict

def extract_review_tag(text):
    """提取<review>块、result/reason字段"""
    import re
    m = re.search(r"<review>(.*?)</review>", text, re.S)
    review_block = m.group(1).strip() if m else ""
    res_m = re.search(r"result:\s*(correct|wrong)", review_block, re.I)
    reason_m = re.search(r"reason:\s*(.+)", review_block, re.I)
    return {
        "review_block": review_block,
        "result": res_m.group(1).lower() if res_m else "",
        "reason": reason_m.group(1).strip() if reason_m else "",
        "raw_review": text.strip(),
    }

def main(args):
    # config yaml loading
    conf = "../prompt.yaml"
    with open(conf, "r") as stream:
        conf = yaml.safe_load(stream)
    active_tools, filtered_meta = load_tool_data(conf)
    active_tools = ",".join(active_tools)
    api_meta_str = json.dumps(filtered_meta, indent=2)

    input_path = Path(args.infile)
    output_path = Path(args.outfile)
    progress_path = Path(args.progress) if args.progress else Path(str(output_path) + ".progress.txt")

    backend = args.backend.lower()
    if backend == "openai":
        import openai
        client = openai.OpenAI(api_key="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")
    elif backend == "gemini":
        from google import genai
        client = genai.Client(api_key="AIzaSyBhhjYp_VcfIfu2Fi7rqEcy8I0CbuNVONc")   # assumes env GOOGLE_API_KEY or config
        SYSTEM_TPL = "You are a careful, detail-oriented reviewer."
    else:
        raise ValueError("Backend must be openai or gemini")

    # 断点续跑：读取进度文件
    start_line = 0
    if progress_path.exists():
        with open(progress_path, "r") as pf:
            try:
                start_line = int(pf.read().strip())
            except Exception:
                start_line = 0

    with input_path.open("r", encoding="utf-8") as fin, \
         output_path.open("a", encoding="utf-8") as fout:   # 追加写入
        for idx, line in enumerate(tqdm(fin, desc="Generating answers", initial=start_line)):
            if idx < start_line:
                continue  # 跳过已处理

            item = json.loads(line)
            question = item["question"]
            response = item["answer"] if "answer" in item else item.get("response")  # 兼容不同字段
            # 跳过空
            if not question or not response:
                continue
            try:
                if backend == "openai":
                    review = review_with_openai(question, response, api_meta_str, client)
                else:
                    review = review_with_gemini(question, response, api_meta_str, client, SYSTEM_TPL)
            except Exception as e:
                print(f"API error: {e}")
                review = f"<review>\nresult: wrong\nreason: LLM API error: {e}\n</review>"

            # 提取与追加
            review_info = extract_review_tag(review)
            item["llm_review"] = review_info
            fout.write(json.dumps(item, ensure_ascii=False) + "\n")
            fout.flush()  # 确保及时写入
            # 记录当前进度
            with open(progress_path, "w") as pf:
                pf.write(str(idx + 1))

            print(f"Checked: {review_info['result']} | {review_info['reason'][:60]}")
            # 防止速率限制
            time.sleep(random.uniform(2.5, 5.5))

    print(f"✅ Finished! Results saved to {output_path}")
    print(f"✅ Progress saved to {progress_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="infile", required=True, help="Input jsonl (QA pairs)")
    parser.add_argument("--out", dest="outfile", required=True, help="Output jsonl with review results")
    parser.add_argument("--backend", choices=["openai", "gemini"], required=True, help="LLM provider")
    parser.add_argument("--progress", default=None, help="Progress file path (default: <outfile>.progress.txt)")
    args = parser.parse_args()
    main(args)
    # python correct_verify.py --in output.jsonl --out checked.jsonl --backend gemini
