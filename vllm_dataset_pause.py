from transformers import Qwen2_5_VLForConditionalGeneration, AutoTokenizer, AutoProcessor
from qwen_vl_utils import process_vision_info
import torch
import os
import json
import requests
import re
import yaml
import time
import torch.distributed as dist
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

def vllm_inference(start=0, end=1 , data_samples = None, output_root="Rollout/Counting", root_prefix = "/datasets", config_file="prompt_configuration_file.yaml"):
    
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
    def make_conversation_sat(example, prefix, conf):
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
            "image_paths": ", ".join(image_paths),
            "available_tools": tools_list,
            "toolbox_metadata": filtered_meta,
        }
        # print(re.findall(r"\{([^}]+)\}", PROMPT_TEMPLATE))
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
                {"role": "system", "content":"You are a helpful assistant who is good at solving vision-based spatial problems with code."},
                {
                    "role": "user",
                    "content": message_content,
                },
            ],
            "solution": answer, 
            "QAid": idx,
            "question": question,
            "kwargs": initial_kwargs,
        }
###################################################################################################################
    # vLLM inference function for SAT-Format dataset
    # Load the dataset
    confiuration_file = config_file
    with open(confiuration_file, "r") as stream:
            conf = yaml.safe_load(stream)
    PROMPT_TEMPLATE = conf.get("prompt_template")

    SourcePrefix_Map = {
            "RealWorld": "RealWorld",
            "Clever":"CLEVER",
            "DARE": "DARE",
            "GQA": "GQA",
            "Spatial457": "Spatial457",
            "mm_visual7w": "mm_visual7w",
            "whatsup":  "whatsup",
        }
    
    root_prefix = root_prefix

    # Load the dataset from the JSON file
    all_samples = []

    spatial_samples_sub  = data_samples # only shuffled once in the outsides of function
    
    
    for sample in spatial_samples_sub:
        dataset_prefix = os.path.join(root_prefix, SourcePrefix_Map[sample["source"]])
        wrapped_data = make_conversation_sat(sample, dataset_prefix, conf)
        all_samples.append(wrapped_data)

    engine_args = EngineArgs(
        model="Qwen/Qwen2.5-VL-7B-Instruct",
        dtype="bfloat16",
        limit_mm_per_prompt={"image": 3},
        enforce_eager=False,
        enable_prefix_caching=True,
        # max_model_len = 8192,
        tensor_parallel_size=1,  # distributed inference
        gpu_memory_utilization = 0.9 # GPU memory utilization
    )
    llm = LLM(**asdict(engine_args))
    
    processor = AutoProcessor.from_pretrained(
        "Qwen/Qwen2.5-VL-7B-Instruct", use_fast=True
    )
    
    sampler_pause = SamplingParams(
        temperature=1.0,
        stop=[TRIGGER_STR],
        include_stop_str_in_output=True,
        max_tokens=1024,
        # seed =42,
        )

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
    
    def run_one_rollout(llm, images, initial_prompt, sample, rolloutid, max_iters=100):
        """
        return assistant complete response, and ones for each step
        """
        history_strs = initial_prompt
        # initialize
        step_outputs = [] # code
        step_records = [] # code + interpreter
        history_snaps = [] # prompts + code + interpreter
        result_correct = "False"
        exe_num = 0
        acc_success, exe_success = 0, 0
        
        for iter in range(max_iters):
            exe_num += 1
            request = {"prompt": history_strs, "multi_modal_data": {"image": [images]}}
            out_text = llm.generate(request, sampler_pause)[0].outputs[0].text
            step_outputs.append(out_text)
            history_strs += out_text
            ori_out_text = out_text
            # <<< TODO: run code in Server: Madeira >>> #
            m = re.search(r"<code>(.*?)</code>", out_text, flags=re.S)
            if m:
                out_text = m.group(1).strip()
                # Check if code still contains markdown-style block
                if out_text.strip().startswith("```"):
                    result = (
                        "FORMAT ERROR: Do not use markdown formatting like ```python  ``` code fence "
                        "Only wrap your code in <code> </code> tags without any other formatting."
                    ) 
                else:
                    payload = {
                    "code": out_text,
                    "timeout": EXECUTION_TIMEOUT_SECONDS,
                    "q_aid": rolloutid
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
                                if filtered.lower() == sample["solution"].lower():
                                    acc_success += 1 # accuracy rate + 1
                                    result = filtered
                                    result_correct = "True"
                                    interp_block = f"<interpreter>{result}</interpreter>"
                                    history_snaps.append(history_strs)
                                    step_records.append(
                                        {"code": out_text,
                                        "interpreter": result}
                                    )
                                    return (step_records, step_outputs, history_snaps,
                                           result_correct, exe_success, acc_success, exe_num)
                                else:
                                    result = f"WRONG RESULT: Though the code ran successfully, the final result: '{filtered.lower()}' does not match the ground truth: '{sample['solution'].lower()}'. Consider debugging and revising your implementation."
                            else:
                                result = filtered
                        else: # problematic code case
                            result = filtered
                        #print(f"[{idx}/{total}] Received status={result_data.get('status')}, filtered result: {repr(filtered)}")
                    except Exception as ex:
                        print(f"[{iter+1}/{max_iters}] Error during request or processing: {ex}")
                        result = str(ex)
            else:
                result = "FORMAT ERROR: Your previous reply was not accepted, because you don't response with ONLY valid Python code wrapped in one pair of <code></code> tags."

            # add exectution result into <interpreter> tags
            interp_block = f"<interpreter>{result}</interpreter>"
            step_records.append({
                "code": ori_out_text.strip(),
                "interpreter": result
            })
            history_strs += interp_block
            if iter != max_iters-1:
                history_strs += "\n<|assistant|>\n"
            history_snaps.append(history_strs)
                
            time.sleep(DELAY_BETWEEN_REQUESTS)
            
        return (step_records, step_outputs, history_snaps,
                result_correct, exe_success, acc_success, exe_num)
    
    # initialization
    total_times = 0
    total_execution_times = 0
    total_accuracy_times = 0
    
    from tqdm.auto import tqdm 
    # iterate all samples data
    # genreate idx from `start` to `end`
    for sample_idx, sample in enumerate(
        tqdm(all_samples, desc="Samples", position=0),
        start=start + 1):
        sample_dir = os.path.join(output_root, f"sample_{sample_idx}")
        os.makedirs(sample_dir, exist_ok=True)
        
        #Preparation for inference
        text = processor.apply_chat_template(
            sample["prompt"], tokenize=False, add_generation_prompt=True
        )
        images = sample["image"]

        # multi-turn outputs
        md_samples, json_samples = [], []
        # For debug
        prompt = all_samples[0]['prompt'][1]["content"][-1]["text"]
        print(f"\nDebug for message prompt:\n{prompt}")
        
        print(f"\n[Sample {sample_idx}]\n")
        for id in range(1):
            # Rollout starting
            step_records,step_outputs,history_snaps,result_correct,exe_success,acc_success,exe_num = run_one_rollout(llm=llm, 
                                                                                                        images=images,
                                                                                                        initial_prompt=text, 
                                                                                                        sample=sample,
                                                                                                        rolloutid = str(id+1))
            total_times += exe_num
            total_execution_times += exe_success
            total_accuracy_times += acc_success
            json_sample = {
                "image": sample["image_path"],
                "question": sample["question"],
                "QAid": sample["QAid"],
                "rolloutID": str(id+1),
                "GT": sample["solution"],
                "code_trace": step_outputs,
                "step_records": step_records,
                "result_correct": result_correct
            }
            # initialize trajectory file
            json_samples.append(json_sample)
            
            # all_outputs.md
            md_samples.append(
                {
                    "question": sample["question"],
                    "gt": sample["solution"],
                    "records": step_records,
                    "prompts": history_snaps,
                    "verdict": result_correct,
                    "rollout_id": id + 1
                }
            )
            
    def save_rollout_outputs(markdown_data, json_samples, sample_dir):
        # Save .md
        
        for roll in markdown_data:
            md_path = os.path.join(sample_dir, f"all_rollouts_{roll['rollout_id']}.md")
            with open(md_path, "w", encoding="utf-8") as f:
                rid = roll["rollout_id"]
                f.write(f"## Rollout {rid}\n\n")
                f.write(f"**Question**: {roll['question']}\n\n")
                f.write(f"**Ground Truth**: `{roll['gt']}`\n\n")

                for idx, rec in enumerate(roll["records"], 1):
                    f.write(f"### Step {idx}\n\n")
                    f.write("**Code**:\n")
                    f.write(rec["code"] + "\n")
                    f.write("\n**/Code**:\n\n")
                    f.write("**Interpreter**\n\n")
                    f.write(rec["interpreter"].rstrip() + "\n")
                    f.write("\n**/Interpreter**:\n\n")

                verdict = "**Correct**" if roll["verdict"] == "True" else "**Incorrect**"
                f.write(f"**Verdict**: {verdict}\n\n---\n\n")
                
                f.write("<details>\n<summary>Full prompts history</summary>\n\n")
                for idx, rec in enumerate(roll["prompts"], 1):
                    f.write(f"\n\n### Step {idx} Prompt\n\n")
                    f.write(rec.strip() + "\n")
                    f.write("\n\n**Prompt**\n\n")

        # Save .json
        json_path = os.path.join(sample_dir, f"rollouts.json")
        with open(json_path, "w", encoding="utf-8") as f_json:
            json.dump(json_samples, f_json, ensure_ascii=False, indent=4)
    
    # save rollout result
    save_rollout_outputs(md_samples, json_samples, sample_dir)

    del llm
    cleanup_dist_env_and_memory()   # vLLM
    torch.cuda.empty_cache() # PyTorch cache clear
    if dist.is_initialized():
        print("Destroying distributed process group...")
        dist.destroy_process_group()

    
if __name__ == "__main__":
    import sys
    from datetime import datetime
    
    # --- Configuration ---
    DELAY_BETWEEN_REQUESTS = 0.5
    EXECUTION_TIMEOUT_SECONDS = 120
    TRIGGER_STR ="</code>"
    MARAJO_SANDBOX_URL = "http://10.153.51.195:8080/api/sandbox/execute"
    # --- End Configuration ---
    
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--json_path", type=str, required=True, help="Path to dataset JSON file")
    parser.add_argument("--output_root", type=str, required=True, help="Path to dataset root directory")
    parser.add_argument("--dataset", type=str, default=10, help="")
    parser.add_argument("--start", type=int, default=0, help="Start index")
    parser.add_argument("--end", type=int, default=10, help="End index")
    args = parser.parse_args()
    
    json_path = args.json_path
    dataset = args.dataset
    start = args.start
    end = args.end
    output_root = args.output_root
    
   
    class Logger(object):
        def __init__(self, filename="pipeline_log.txt"):
            self.terminal = sys.stdout
            self.log = open(filename, "a", encoding="utf-8")
        def write(self, message):
            self.terminal.write(message)
            self.log.write(message)
        def flush(self):
            self.terminal.flush()
            self.log.flush()

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")

    print("Start inference and execution loop...\n")

    prefix = "/nfs/data8/liao/wxie/datasets"
    config_file = "prompt_configuration_file_pause.yaml"
    
    # Load the dataset
    with open(json_path, 'r') as f:
        raw_dataset = json.load(f)
        
    output_indices_file = os.path.join(output_root, f"{output_root}_selected_indices.json")
    # create output directory
    if not os.path.exists(output_root):
        os.makedirs(output_root)
    
    # LOGGING
    print(f"Final output_root: {output_root}")
    log_file = os.path.join(output_root, f"{dataset}_log-{timestamp}.txt")
    sys.stdout = Logger(log_file)
    sys.stderr = sys.stdout
    print(f"Log file created at: {log_file}\n")
    
    # pick spatial reasoning samples from raw_dataset and save indices
    if not os.path.exists(output_indices_file):
        spatial_samples = []
        selected_indices = []
        for sample in raw_dataset:
            if "spatial reasoning" not in sample["response"].lower():
                print(f"Skip the sample {sample['idx']} because of general question.")
            else:
                spatial_samples.append(sample)
        random.shuffle(spatial_samples)
        print("Shuffle spatial_samples finished.\n")
        
        spatial_samples_sub = spatial_samples[start:end]
        selected_indices = [sample["idx"] for sample in spatial_samples_sub]
        with open(output_indices_file, "w", encoding="utf-8") as f_out:
            json.dump(selected_indices, f_out, ensure_ascii=False, indent=4)
        print(f"Save selected indices to {output_indices_file} finished.\n")
    else:
        with open(output_indices_file, "r", encoding="utf-8") as f_in:
            selected_indices = json.load(f_in)
            # 用selected_indices 重建spatial_samples保证顺序一致
            id2sample = {sample["idx"]: sample for sample in raw_dataset}
            spatial_samples_sub = [id2sample[idx] for idx in selected_indices]
            print("Loaded spatial_samples from existing indices, order preserved.\n")

    vllm_inference(start=start,  # end-start: the numbers of qa extracted from all datasets
                    end = end, 
                    data_samples = spatial_samples_sub, 
                    output_root=output_root,
                    root_prefix= prefix, 
                    config_file=config_file,
                    )
    time.sleep(2)
    print("All steps done.")
    sys.stdout.log.close()
