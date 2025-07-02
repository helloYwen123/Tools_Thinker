from openai import OpenAI
import time
# Import libraries
import os
from PIL import Image
import random
import yaml
import base64
import re
import requests

import json



def gpt_inference(start=0, end=1 , data_samples = None, output_root="Rollout/Counting", root_prefix = "/datasets", config_file="prompt_configuration_file.yaml"):
    """
    Function to perform inference using vLLM.
    
    Args:
        start (int): Start index for data samples.
        end (int): End index for data samples.
        data_samples (list): List of data samples to process.
        output_root (str): Root directory for output files.
        root_prefix (str): Prefix for dataset paths.
        config_file (str): Path to the configuration file.
    """
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
    
    # Function to convert image to data URL
    def image_to_data_url(image_path):
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        base64_str = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:image/jpeg;base64,{base64_str}"
    
    # for SAT Dataset
    def make_conversation_sat_gpt(example, prefix, conf):
        # get answer
        # here `prefix` is the prefix of the image path
        # `image_path` is from the dataset json file
        image_paths = [os.path.join(prefix, img_path) for img_path in example["images"]]
        images = [image_to_data_url(path) for path in image_paths] # from local image path to data url
        idx = example["idx"]  # image name as index
        question=example["messages"][0]["content"].strip()
        question = question.lower().replace("and nothing else.", "")
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
        
        message_content = [{"type": "image_url", "image_url": {"url": image_url}} for image_url in images]
        message_content.append({
                        "type": "text",
                        "text": formatted
                    })
        return {
            "image_path": image_paths,
            "prompt": [
                {"role": "system", "content":
                (
            "You are a helpful AI assistant who is good at solving vision-based spatial problems through coding.",
            "You can effectively analyze the execution results of code, identify potential issues, and refine the code accordingly to ensure it runs correctly"
                )},
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
    # Load the dataset from the JSON file
    all_samples = []

    spatial_samples_sub  = data_samples # only shuffled once in the outsides of function
    
    
    for sample in spatial_samples_sub:
        dataset_prefix = os.path.join(root_prefix, SourcePrefix_Map[sample["source"]])
        if "spatial reasoning question" in sample["response"]:
            wrapped_data = make_conversation_sat_gpt(sample, dataset_prefix, conf)
            all_samples.append(wrapped_data)
            
    def filter_result(result_data: dict, tool: str):
        """
        Picks the final result on success or the traceback on error.
        """
        status = result_data.get("status")
        if status == "success":
            if result_data.get("tool_return") is not None:
                result = result_data.get("tool_return")
                # here should identify: whether to pick path (segmentor or depth estimator)\original variable;
                if tool == "others":
                    result =  f"The full output for tool usage: {result}"
                    return result
                elif tool == "segment":
                    masks_paths = list(result.keys())
                    result = f"The Paths to saved `npy` segmentation masks file: {masks_paths}"
                    return result
                elif tool == "depth":
                    depth_paths = list(result.keys())
                    result = f"The Paths to saved `npy` depth maps file: {depth_paths}"
                    return result
                else:
                    raise ValueError("Unknown Used Tool Names!\n")
            else:
                no_tool_return_finding = "OUTPUT VARIABLE MISSING: 'tool_return' variable not found in code. Please assign the output with it!"
                return no_tool_return_finding
        else:
            raw = result_data.get("error_message") or result_data.get("stderr") or result_data.get("stdout", "")
            return raw.split("\n--- Sys Path")[0].strip()
    
    def run_one_rollout(client, initial_prompt, sample, rolloutid, max_iters=3):
        """
        return assistant complete response, and ones for each step
        """
        history_strs = initial_prompt
        
        # initialize
        step_records = [] # code + interpreter
        history_snaps = [] # prompts + code + interpreter
        result_correct = "False"
        exe_num = 0 # 
        acc_success, exe_success = 0, 0
        # exe_num: The total times of tool usage execution for current QA.
        # acc_success:  whether the current QA answer correctly(bool: True/False)
        # exe_success:  The times of successful tool usage execution for current QA
        for iter in range(max_iters):
            exe_num += 1

            resp = client.chat.completions.create(
            model="gpt-4o",
            messages=history_strs,
            stop=["</code>"],
            stream=False
            )
            # how to exclude the case of no code output?
            if resp.choices[0].finish_reason == "stop":
                out_text = resp.choices[0].message.content + "</code>"
            else:
                out_text = resp.choices[0].message.content
            
            history_strs.append({"role": "assistant", "content": out_text})
            ori_out_text = out_text
            # <<< TODO: run code in Server: Madeira >>> #
            code_match = re.search(r"<code>(.*?)</code>", out_text, flags=re.S)
            ans_match = re.search(r"<answer>\s*\\boxed\{(.*?)\}.*?</answer>", out_text, flags=re.S)

            matches = [m for m in [code_match, ans_match] if m is not None]
            if len(matches) == 1:
                if ans_match and not code_match: # outputting the final answer
                    m = matches[0]
                    out_text = m.group(1).strip() # here is the content extracted from \boxed{}
                    if out_text.lower() == sample["solution"].lower() or out_text.strip("\"'") == sample["solution"].strip("\"'"):
                        result_correct = "True"
                        acc_success += 1
                        result = out_text
                        history_snaps.append(history_strs)
                        step_records.append(
                            {"code": ori_out_text,
                            "interpreter": "Code executed successfully, and the final result matches the ground truth.",
                            "step": iter + 1,
                            "correct answer": True}
                        )
                        return (step_records, history_snaps,
                            result_correct, exe_success, acc_success, exe_num)
                    else:
                        result = f"WRONG RESULT: Though the code ran successfully, the final result: {out_text.lower()}, does not match the ground truth."
                else:  # outputting code snippets
                    m = matches[0]
                    out_text = m.group(1).strip()
                    # Check if code still contains markdown-style block
                    if out_text.strip().startswith("```"):
                        result = (
                            "FORMAT ERROR: Do not use markdown formatting like ```python  ``` code fence "
                            "Only wrap your code in <code> </code> tags without any other formatting."
                        )
                    else:
                        segment = out_text.count("Segmenter_Tool") >= 2
                        depth   = out_text.count("Depth_estimator") >= 2
                        if segment:
                            tool = "segment"
                        elif depth:
                            tool = "depth"      
                        else:
                            tool = "others"
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
                            filtered= filter_result(result_data, tool)
                            if status == "success":
                                exe_success += 1
                            result = filtered # includes successful execution and failed execution
                            #print(f"[{idx}/{total}] Received status={result_data.get('status')}, filtered result: {repr(filtered)}")
                        except Exception as ex:
                            print(f"[{iter+1}/{max_iters}] Error during request or processing: {ex}")
                            result = str(ex)
            elif len(matches) == 2:
                result = "FORMAT ERROR: Detected both <code> and <answer> in output. This is ambiguous. Remember to still include the <Think> tags."
            else:
                result = "FORMAT ERROR: Failed to detect <code>...</code> tags, or <answer>\\boxed{...}</answer> Tags from your response. Remember to still include the <Think> tags."

            # add exectution result into <interpreter> tags
            interp_block = f"<inter>{result}</inter>"
            step_records.append({
                "code": ori_out_text.strip(),
                "interpreter": result,
                "step": iter + 1
            })
            
            history_strs.append({"role": "user", "content": interp_block})
            history_snaps.append(history_strs)
                
            time.sleep(DELAY_BETWEEN_REQUESTS)
            
        return (step_records, history_snaps,
                result_correct, exe_success, acc_success, exe_num)
        
    # initialization
    total_times = 0
    total_execution_times = 0
    total_accuracy_times = 0
    
    from tqdm import tqdm
    # iterate all samples data
    # genreate idx from `start` to `end`
    for sample_idx, sample in enumerate(
        tqdm(all_samples, desc="Samples", position=0),
        start=start + 1):
        sample_dir = os.path.join(output_root, f"sample_{sample_idx}")
        os.makedirs(sample_dir, exist_ok=True)
        
        # multi-turn outputs
        md_samples, json_samples = [], []
        # For debug
        prompt = all_samples[0]['prompt'][1]["content"][-1]["text"]
        print(f"\nDebug for message prompt:\n{prompt}")
        
        print(f"\n[Sample {sample_idx}]\n")
        for id in range(1): # determine rollouts time for single sample
            # Rollout starting
            step_records,history_snaps,result_correct,exe_success,acc_success,exe_num = run_one_rollout(
                                                                                                        client=client,
                                                                                                        initial_prompt=sample["prompt"], 
                                                                                                        sample=sample,
                                                                                                        rolloutid = str(id+1)
                                                                                                        )
            total_times += exe_num
            total_execution_times += exe_success
            total_accuracy_times += acc_success
            json_sample = {
                "image": sample["image_path"],
                "question": sample["question"],
                "QAid": sample["QAid"],
                "rolloutID": str(id+1),
                "GT": sample["solution"],
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
                    f.write(f"\n\n### Step {idx} chat formatted history\n\n")
                    f.write(str(rec) + "\n") # there prompts are chat formatted history(e.g. role + content)


        # Save .json
        json_path = os.path.join(sample_dir, f"rollouts.json")
        with open(json_path, "w", encoding="utf-8") as f_json:
            json.dump(json_samples, f_json, ensure_ascii=False, indent=4)
    
    # save rollout result
    save_rollout_outputs(md_samples, json_samples, sample_dir)
    
if __name__ == "__main__":
    import sys
    from datetime import datetime
    os.environ["OPENAI_API_KEY"] = \
    "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"

    client = OpenAI()
    
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
    parser.add_argument("--prefix", type=str, default="/nfs/data8/liao/wxie/datasets", help="Start index")
    parser.add_argument("--config_file", type=str, default="./config/prompt_configuration_file_incre.yaml", help="End index")
    args = parser.parse_args()
    
    json_path = args.json_path
    dataset = args.dataset
    start = args.start
    end = args.end
    output_root = args.output_root
    prefix = args.prefix
    config_file = args.config_file
    
    
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
    
    # Load the dataset
    with open(json_path, 'r') as f:
        raw_dataset = json.load(f)
        
    output_indices_file = os.path.join(output_root, f"selected_indices.json")
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

    gpt_inference( start=start,  # end-start: the numbers of qa extracted from all datasets
                    end = end, 
                    data_samples = spatial_samples_sub, 
                    output_root=output_root,
                    root_prefix= prefix, 
                    config_file=config_file,
                    )
    print("All steps done.")
    sys.stdout.log.close()