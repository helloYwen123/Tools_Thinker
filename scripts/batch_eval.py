from transformers import Qwen2_5_VLForConditionalGeneration, AutoTokenizer, AutoProcessor
from qwen_vl_utils import process_vision_info
import torch
import os
import json
import requests
import re
import yaml
import time
from tqdm.auto import tqdm
import torch.distributed as dist
from concurrent.futures import ThreadPoolExecutor, as_completed
from eval_config.eval_utils import get_rope_index, postprocess_data, pad_2d_list_to_length, get_response_mask
print(torch.cuda.is_available())
print(torch.cuda.device_count())
print(torch.cuda.get_device_name(0))

#--- set random seed for reproduction ---
# import transformers,random
# import numpy as np
# seed = 42
# transformers.set_seed(seed)
# random.seed(seed)
# np.random.seed(seed)
# torch.manual_seed(seed)
# torch.cuda.manual_seed(seed)
# print(f"Random Seed setting finished.")
#---------------------------------

# Import libraries
import os
from PIL import Image
import random
# vLLM related
from vllm import LLM, EngineArgs, SamplingParams
from vllm.distributed import cleanup_dist_env_and_memory
from dataclasses import asdict


def detect_mode(resp: str) -> str:
    """
    Decide whether the model replied in CODE mode, NL mode, or invalid.

    Valid patterns (whitespace/newlines allowed between tags):
      1. <think> … </think> <code> … </code>
      2. <think> … </think> <answer> … </answer>

    Returns:
        'code'      CODE mode (needs sandbox execution)
        'nl'        natural-language answer mode
        'invalid'   anything else
    """
    s = resp.strip()
    code_pat   = r'^<think>.*?</think>\s*<code>.*?</code>\s*$'
    ans_pat    = r'^<think>.*?</think>\s*<answer>.*?</answer>\s*$'
    if '<code>' in s and '<answer>' in s:
        return 'invalid'
    if re.fullmatch(code_pat, s, re.S):
        return 'code'
    if re.fullmatch(ans_pat,  s, re.S):
        return 'nl'
    return 'invalid'

def extract_code(resp: str):
    """Return code string inside <code> … </code>, or None if absent."""
    m = re.search(r"<code>(.*?)</code>", resp, re.S)
    return m.group(1).strip() if m else None


def extract_boxed_answer(resp: str):
    """Return answer string inside \boxed{…} tag under <answer>, or None."""
    m = re.search(r"<answer>.*?\\boxed\{(.*?)\}.*?</answer>", resp, re.S)
    return m.group(1).strip() if m and m.group(1) else None

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


# load selected tooldata from prompt yaml file        
def load_tool_data(conf):
    # --- Tool Metadata Filtering Logic ---
    active_tool_names = conf.get("available_tools", []) # Get the list from YAML
    full_toolbox_metadata = conf.get("toolbox_metadata", {})

    # Create a dictionary containing only the metadata for active tools
    filtered_metadata_dict = {
        tool_name: full_toolbox_metadata[tool_name]
        for tool_name in active_tool_names
        if tool_name in full_toolbox_metadata
    }

    # Warn for missing tools
    for tool_name in active_tool_names:
        if tool_name not in full_toolbox_metadata:
            print(f"Warning: Tool '{tool_name}' listed in available_tools but not found in toolbox_metadata.")

    return active_tool_names, filtered_metadata_dict

# for SAT Dataset
def make_conversation_sat(example, prefix, conf, PROMPT_TEMPLATE):
    # get answer
    # here `prefix` is the prefix of the image path
    # `image_path` is from the dataset json file
    image_paths = [os.path.join(prefix, img_path) for img_path in example["images"]]
    images = [Image.open(path) for path in image_paths]
    idx = example["idx"]  # image name as index
    question=example["messages"][0]["content"].strip()
    question = question.lower().replace("please answer directly with only the letter of the correct option and nothing else.", "please answer directly with only the letter of the correct option")
    answer = example["messages"][1]["content"].strip()
    # get tools
    active_tools, filtered_meta = load_tool_data(conf)
    tools_list = ", ".join(active_tools)
    
    # Format the final prompt text using the provided strings
    initial_kwargs = {
        "question": question,
        "input_images": ", ".join(image_paths),
        "available_tools": tools_list,
        "toolbox_metadata": filtered_meta,
    }
    formatted = PROMPT_TEMPLATE.format(**initial_kwargs)
    
    message_content = [*({'type': 'image'} for _ in range(len(example["images"])))]
    message_content.append({
                    "type": "text",
                    "text": formatted
                })

    return {
        "image": images,
        "image_path": image_paths,
        "prompt": [
            {"role": "system", "content":("You are an expert AI assistant specializing in visual problem-solving. "
            "Your primary goal is to accurately answer questions about images by choosing the most appropriate method: "
            "programmatic analysis with Python tools or direct natural language reasoning.")},
            {
                "role": "user",
                "content": message_content,
            },
        ],
        "solution": answer, 
        "QAid": idx,
        "question": question,
    }

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
                no_result_finding = "OUTPUT VARIABLE MISSING: 'final_result' variable not found in code."
                return no_result_finding, False
        else:
            raw = result_data.get("error_message") or result_data.get("stderr") or result_data.get("stdout", "")
            return raw.split("\n--- Sys Path")[0].strip(), False


# ------------ Streaming logging helpers ------------
def append_jsonl(path: str, record: dict):
    """Append one dict as a JSON-Line (1 line / sample)."""
    with open(path, "a", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
        f.write("\n")


def append_markdown(path: str, record: dict):
    """Append one sample block to a markdown file."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"## QAid: {record['QAid']}\n")
        f.write(f"**Q:** {record['question']}\n")
        f.write(f"**GT:** {record['gt']}\n")
        f.write(f"**Result:** {record['result']}\n")
        f.write(f"**Correctness:** {record['correctness']}\n")
        f.write(f"**Execution/Accuracy:** {record['execution_accuracy']}\n\n")

def vllm_inference(
    start: int = 0,
    end: int = 1,
    data_samples=None,
    output_root: str = "Rollout/",
    prefix: str = "/datasets",
    config_file: str = "prompt_configuration_file.yaml",
    model: str = None,
    max_prompt_length:int = 8192
):
    # ---------- init ----------
    os.makedirs(output_root, exist_ok=True)
    with open(config_file, "r") as f:
        conf = yaml.safe_load(f)
    prompt_tmpl = conf["prompt_template"]

    # build wrapped samples
    images_prefix = prefix
    wrapped = [
        make_conversation_sat(s, images_prefix, conf, prompt_tmpl)
        for s in data_samples
    ][start:end]

    # ---------- vLLM engine ----------
    engine_args = EngineArgs(
        model=model,
        dtype="bfloat16",
        limit_mm_per_prompt={"image": 3},
        enforce_eager=False,
        enable_prefix_caching=True,
        max_model_len=10240,
        max_num_batched_tokens=20480,
        tensor_parallel_size=1,
        gpu_memory_utilization=0.9,
    )
    llm = LLM(**asdict(engine_args))
    processor = AutoProcessor.from_pretrained(model, trust_remote_code=True)
    tokenizer = processor.tokenizer
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    sampling_params = SamplingParams(temperature=0.1, max_tokens=2048, seed=42)

    # ---------- files ----------
    md_path, jsonl_path = (
        os.path.join(output_root, "all_outputs.md"),
        os.path.join(output_root, "all_outputs.jsonl"),
    )
    open(md_path, "w").close()
    open(jsonl_path, "w").close()

    # ---------- 1️⃣ FIRST PASS: GENERATION ----------
    print("\n*** Stage 1 — multimodal generation ***")

    gen_outputs = []                                 # [(sample, raw_text), …]
    results = [] # preprocessing results
    for sample in tqdm(wrapped, desc="Preprocess"):
        # build prompt string
        prompt = processor.apply_chat_template(sample["prompt"], add_generation_prompt=True, tokenize=False)

        # *** multi-modal requests ***
        images = sample["image"]
        for i in range(len(images)):
            if images[i].mode != "RGB":
                images[i] = images[i].convert("RGB")

        model_inputs = processor(images, [prompt], add_special_tokens=False, return_tensors="pt")   
        input_ids = model_inputs.pop("input_ids")[0]
        attention_mask = model_inputs.pop("attention_mask")[0]
        position_ids = model_inputs.get("position_ids", None)
        image_grid_thw = model_inputs.get("image_grid_thw", None)
        if position_ids is None:
            position_ids = get_rope_index(
                processor=processor,
                input_ids=input_ids,
                attention_mask=attention_mask,
                image_grid_thw=image_grid_thw,
            )

        input_ids, attention_mask, position_ids = postprocess_data(
            input_ids=input_ids,
            attention_mask=attention_mask,
            position_ids=position_ids,
            max_length=max_prompt_length,
            pad_token_id=tokenizer.pad_token_id,
            left_pad=True,
            truncation="right",
        )
        raw_prompt_ids = tokenizer.encode(prompt, add_special_tokens=False)
        raw_prompt_ids = raw_prompt_ids[:max_prompt_length] if len(raw_prompt_ids) > max_prompt_length else raw_prompt_ids

        results.append({
            "attention_mask": attention_mask,
            "raw_prompt_ids": raw_prompt_ids,
            "multi_modal_data": {"image": images},
        })
    
    # batch inputs
    vllm_inputs = [
        {"prompt_token_ids": r["raw_prompt_ids"], "multi_modal_data": r["multi_modal_data"]}
        for r in results
    ]
    # batch inference
    completions: List[RequestOutput] = llm.generate(prompts=vllm_inputs, sampling_params=sampling_params, use_tqdm=True)

    response_ids = [output.token_ids for completion in completions for output in completion.outputs]
    response_ids = pad_2d_list_to_length(response_ids, pad_token_id=tokenizer.pad_token_id, max_length=2048).to(device)

    # Build attention mask from eos
    response_mask = get_response_mask(response_ids, eos_token_id=tokenizer.eos_token_id, dtype=torch.long)
    response_mask = response_mask.to(device)
    attention_mask = torch.cat([r["attention_mask"].unsqueeze(0).to(device) for r in results], dim=0)  # => [B, prompt_len]
    final_attention_mask = torch.cat([attention_mask, response_mask], dim=-1)

    # Decode response ids
    response_str = []
    response_length = response_mask.sum(dim=-1)
    for i in range(response_ids.size(0)):
        valid_ids = response_ids[i][: response_length[i]]
        response_str.append(tokenizer.decode(valid_ids.cpu(), skip_special_tokens=True))

    gen_outputs = []
    assert len(wrapped) == len(response_str), "error: length of `wrapped` and `response_str`"
    for sample, text in zip(wrapped, response_str):
        gen_outputs.append((sample, text))

    # === Save or return ===
    # for (sample, text) in zip(wrapped, response_str):
    #     with open(os.path.join(output_root, "all_outputs.md"), "a") as f:
    #         f.write(f"## Q: {sample['question']}\n\n response:\n {text}\n\n")

    #     with open(os.path.join(output_root, "all_outputs.jsonl"), "a") as f:
    #         f.write(json.dumps({"QAid": sample["QAid"], "response": text}) + "\n")
    print("\n*** Stage 2 — evaluation + logging ***")

    def call_sandbox(sample, txt):
        code = extract_code(txt) or ""
        payload = {"code": code, "timeout": EXECUTION_TIMEOUT_SECONDS, "q_aid": str(sample["QAid"])}
        try:
            r = requests.post(MARAJO_SANDBOX_URL, json=payload, timeout=EXECUTION_TIMEOUT_SECONDS)
            r.raise_for_status()
            data = r.json()
            output_str, ok_flag = filter_result(data)
        except Exception as e:
            output_str, ok_flag = f"sandbox error: {e}", False

        exe = 1
        acc = 1 if ok_flag and loose_match(output_str, sample["solution"]) else 0
        result = output_str

        # logging
        append_jsonl(
            jsonl_path,
            {
                "image": sample.get("image_path", None),
                "question": sample.get("question", None),
                "response": txt,
                "QAid": sample.get("QAid", None),
                "GT": sample.get("solution", None),
                "result": result,
            },
        )
        append_markdown(
            md_path,
            {
                "QAid": sample.get("QAid", None),
                "question": sample.get("question", None),
                "gt": sample.get("solution", None),
                "result": result,
                "correctness": "True" if acc else "False",
            },
        )
        return exe, acc

    def call_nl(sample, txt):
        ans = extract_boxed_answer(txt)
        exe = 1 if ans else 0
        acc = 1 if ans and loose_match(ans, sample["solution"]) else 0
        result = ans or "FORMAT ERROR: <answer> requires \\boxed{}"

        # logging
        append_jsonl(
            jsonl_path,
            {
                "image": sample.get("image_path", None),
                "question": sample.get("question", None),
                "response": txt,
                "QAid": sample.get("QAid", None),
                "GT": sample.get("solution", None),
                "result": result,
            },
        )
        append_markdown(
            md_path,
            {
                "QAid": sample.get("QAid", None),
                "question": sample.get("question", None),
                "gt": sample.get("solution", None),
                "result": result,
                "correctness": "True" if acc else "False",
            },
        )
        return exe, acc

    def dummy_fail(sample, txt):
        # invalid
        result = "FORMAT ERROR"
        append_jsonl(
            jsonl_path,
            {
                "image": sample.get("image_path", None),
                "question": sample.get("question", None),
                "response": txt,
                "QAid": sample.get("QAid", None),
                "GT": sample.get("solution", None),
                "result": result,
            },
        )
        append_markdown(
            md_path,
            {
                "QAid": sample.get("QAid", None),
                "question": sample.get("question", None),
                "gt": sample.get("solution", None),
                "result": result,
                "correctness": "False",
            },
        )
        return 0, 0

    tot = exe_ok = acc_ok = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        future2idx = {}
        for idx, (sample, txt) in enumerate(gen_outputs):
            mode = detect_mode(txt)
            if mode == "code":
                future = pool.submit(call_sandbox, sample, txt)
            elif mode == "nl":
                future = pool.submit(call_nl, sample, txt)
            else:
                future = pool.submit(dummy_fail, sample, txt)
            future2idx[future] = idx

        for fut in as_completed(future2idx):
            exe, acc = fut.result()
            tot += 1
            exe_ok += exe
            acc_ok += acc

    # 
    exec_acc = exe_ok / tot if tot else 0
    acc = acc_ok / tot if tot else 0
    stats_path = os.path.join(output_root, "accuracy_log.txt")
    with open(stats_path, "w") as f:
        f.write(f"Total samples: {tot}\n")
        f.write(f"Execution accuracy: {exec_acc:.4f}\n")
        f.write(f"Final accuracy: {acc:.4f}\n")

    print(f"overall execution: {exec_acc}, accuracy: {acc}")



    # ---------- cleanup ----------
    del llm
    cleanup_dist_env_and_memory()
    torch.cuda.empty_cache()
    if dist.is_initialized():
        dist.destroy_process_group()


    
if __name__ == "__main__":
    import sys
    from datetime import datetime

    DELAY_BETWEEN_REQUESTS = 1.0
    EXECUTION_TIMEOUT_SECONDS = 300
    MARAJO_SANDBOX_URL = "http://10.153.51.195:8080/api/sandbox/execute"

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--json_path", type=str, nargs="+", required=True, help="Path(s) to dataset JSON file(s), support multiple paths")
    parser.add_argument("--output_root", type=str, required=True, help="Root output directory")
    parser.add_argument("--dataset", type=str, default="Spatial457", help="Dataset name")
    parser.add_argument("--start", type=int, default=0, help="Start index")
    parser.add_argument("--end", type=int, default=0, help="End index")
    parser.add_argument("--prefix", type=str, default="/nfs/data8/liao/wxie/datasets", help="Dataset prefix path")
    parser.add_argument("--config_file", type=str, default="prompt_configuration_file_pause.yaml", help="Prompt config yaml")
    parser.add_argument("--model", type=str, default="Qwen/Qwen2.5-VL-7B-Instruct", help="model")
    args = parser.parse_args()

    json_paths = args.json_path   
    dataset = args.dataset
    start = args.start
    end = args.end
    output_root = args.output_root
    prefix = args.prefix
    config_file = args.config_file
    model = args.model

    for json_path in json_paths:
        
        json_base = os.path.splitext(os.path.basename(json_path))[0]
        
        sub_output_root = os.path.join(output_root, json_base, "logs")
        os.makedirs(sub_output_root, exist_ok=True)

        image_prefix = os.path.join(prefix, dataset)

        print(f"\n=== Evaluating: {json_path}")
        print(f"    Output: {sub_output_root}\n")

        with open(json_path, "r") as f:
            samples = json.load(f)
        if start == 0 and end == 0:
            end = len(samples) - 1

        vllm_inference(
            start=start,
            end=end,
            data_samples=samples,
            output_root=sub_output_root,
            prefix=image_prefix,
            config_file=config_file,
            model=model,
        )
        time.sleep(2)
        print(f"Done: {json_path}")

    print("All steps done.")

# python 