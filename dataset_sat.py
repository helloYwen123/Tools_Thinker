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

# #--- set random seed for reproduction ---
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
        question = question.lower()
        answer = example["messages"][1]["content"].strip()
        # get tools
        active_tools, filtered_meta = load_tool_data(conf)
        tools_list = ", ".join(active_tools)
        # get clear json file
        # meta_json = json.dumps(filtered_meta, ensure_ascii=False, indent=2)
        # toolbox_block = f"```json\n{meta_json}\n```"
        # Format the final prompt text using the provided strings
        initial_kwargs = {
            "question": question,
            "image_paths": ", ".join(image_paths),
            "available_tools": tools_list,
            "toolbox_metadata": filtered_meta,
            "code_example1": "<empty>",
            "interpreter1":  "<empty>",
            "code_example2": "<empty>",
            "interpreter2":  "<empty>",
            "code_example3": "<empty>",
            "interpreter3":  "<empty>",
        }
        # print(re.findall(r"\{([^}]+)\}", PROMPT_TEMPLATE))
        formatted = PROMPT_TEMPLATE.format(**initial_kwargs)
        
        message_content = [*({'type': 'image'} for _ in range(len(example["images"])))]
        message_content.append({
                        "type": "text",
                        "text": formatted
                    })

        return {
            "image": images, # images 
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
            "mm_visual7w": "mm_visual7w",
            "whatsup":  "whatsup"
        }
    
    root_prefix = root_prefix

    # Load the dataset from the JSON file
    all_samples = []

    spatial_samples_sub  = data_samples # only shuffled once in the outsides of function
    
    
    for sample in spatial_samples_sub:
        dataset_prefix = os.path.join(root_prefix, SourcePrefix_Map[sample["source"]])
        wrapped_data = make_conversation_sat(sample, dataset_prefix, conf)
        all_samples.append(wrapped_data)

    # print(f"\nThe first sample:\n {all_samples[0]}\n")
    # # Print the first sample for debugging
    # print(f"\nThe first sample image path:\n {all_samples[0]['image_path']}\n")

    engine_args = EngineArgs(
        model="Qwen/Qwen2.5-VL-7B-Instruct",
        dtype="bfloat16",
        limit_mm_per_prompt={"image": 3},
        enforce_eager=False,
        enable_prefix_caching=True,
        max_model_len = 8192,
        tensor_parallel_size=1,  # distributed inference
        gpu_memory_utilization = 0.7 # GPU memory utilization
    )
    llm = LLM(**asdict(engine_args))

    sampling_params = SamplingParams(
        temperature=1.0, # highly diverse
        max_tokens=1024,
    )

    processor = AutoProcessor.from_pretrained(
        "Qwen/Qwen2.5-VL-7B-Instruct", use_fast=True
    )

    # 开始历遍所有samples data
    PROMPT_SHOW = True
    # genreate idx from `start` to `end`
    for sample_idx, sample in zip(range(start+1, end+1), all_samples):
        sample_dir = os.path.join(output_root, f"sample_{sample_idx}")
        os.makedirs(sample_dir, exist_ok=True)
        
        #Preparation for inference
        text = processor.apply_chat_template(
            sample["prompt"], tokenize=False, add_generation_prompt=True
        )
        
        images = sample["image"]
        
        # create multi-modal inputs for text-image pairs
        request = {
            "prompt": text,
            "multi_modal_data": {"image": [images]},
        }
        # _ = llm.generate(request, sampling_params) # warmup kv-cache

        # multi-turn outputs
        all_outputs = [] # 当前这个sample的rollout outputs(create n trajectory ; extent n trajectory)
        
        rollout_files = []
        for fname in os.listdir(sample_dir): # 列出当前sample文件夹中所有的rollout trajectory json文件
            m = re.match(r"rollouts_trajectory_(\d+)\.json$", fname)
            if m:
                idx = int(m.group(1))
                rollout_files.append((idx, fname))
        # 如果上述确定trajectory json文件失败则确定是第一轮rollout 否则进入读取rollout json读取阶段
        # 用json中的code text 更新 prompt template
        if rollout_files:
            phase = 2 # trajectory extent phase
            max_idx, latest_fname = max(rollout_files, key=lambda x: x[0]) # 找到最新的轨迹json文件 并加载
            # json_samples = {"image", "question", "QAid", "GT", "code_ex_i","RolloutID"}
            load_path = os.path.join(sample_dir, latest_fname)
            with open(load_path, 'r', encoding='utf-8') as f:
                json_samples = json.load(f)
            print(f"\n[Sample {sample_idx}] Phase 2: load {latest_fname}\n")
        else:
            phase = 1 # rollout seeds phase
            json_samples = []
            
        if phase == 1:
            # For debug
            prompt = all_samples[0]['prompt'][0]["content"][-1]["text"]
            print(f"\nDebug for message prompt:\n{prompt}")
            
            print(f"\n[Sample {sample_idx}] Phase 1: start initial rollouts\n")
            for id in range(10):
                # 开始创建轨迹trajectory n
                # every sample(1 qa) rollout 20 times; 大循环下对单个QA进行读取； 小循环对这个qa用模型(vLLM)推理20轮
                ###### here to control the number of rollouts, e.g. 20
                # Rollout starting
                outputs = llm.generate(request, sampling_params)
                out_text = outputs[0].outputs[0].text

                json_sample = {
                    "image": sample["image_path"],
                    "question": sample["question"],
                    "QAid": sample["QAid"],
                    "rolloutID": str(id+1),
                    "GT": sample["solution"],
                    "code_ex1": out_text
                }
                # 初始化轨迹 json 文件
                json_samples.append(json_sample)
                # all_outputs.txt 文件填充
                all_outputs.append(out_text)
                # Rollout ending
                
        elif phase == 2:
            max_idx = min(max_idx, 3)
            # 开始延展轨迹`trajectory.json`
            prompt_kwargs = sample["kwargs"]
            for json_sample in json_samples: # here `json_samples` is from trajectory.json files
                if "final_solution" in json_sample:
                    print(f"The Trajectory stops extension because of the correct answer.")
                    continue
                codes = [k for k in json_sample.keys() if k.startswith("code_ex")]
                if max_idx != 3:
                    for k in codes:
                        # 从已有的json trajectory中更新prompt; 用新生成的code 更新prompt template
                        idx = int(k.replace("code_ex", ""))
                        #code_text = json_sample[k].replace("\n", "\\n") # TODO check whether is better
                        code_text = json_sample[k]
                        if re.fullmatch(r"<code>.*?</code>", code_text.strip(), re.DOTALL):
                            code_text = code_text.replace("<code>", "").replace("</code>", "").strip()
                        prompt_kwargs[f"code_example{idx}"] = code_text

                    # Note：
                    # interpreter 的添加在code执行端(medeira端)
                    interpreters = [k for k in json_sample.keys() if k.startswith("interpreter")] # here is from json files
                    # print(f"{interpreters} while {list(json_sample.keys())}")
                    for k in interpreters:
                        # 从已有的json trajectory中更新prompt; 用新生成的interpreter 更新prompt template
                        idx = int(k.replace("interpreter", ""))
                        # code_text = json_sample[k].replace("\n", "\\n") # TODO check whether is better
                        interpreter_text = json_sample[k]
                        prompt_kwargs[f"interpreter{idx}"] = interpreter_text
                else: # 防止最后一次rollout时`trajactory3`存在情况的bug
                    for i in [1, 2]:
                        code_key = f"code_ex{i}"
                        interpreter_key = f"interpreter{i}"
                        if code_key in json_sample:
                            prompt_kwargs[f"code_example{i}"] = json_sample[code_key]
                        if interpreter_key in json_sample:
                            prompt_kwargs[f"interpreter{i}"] = json_sample[interpreter_key]

                new_formatted = PROMPT_TEMPLATE.format(**prompt_kwargs)
                if PROMPT_SHOW:
                    print(f"new_formatted: {new_formatted}\n")
                    PROMPT_SHOW = False
                    # break

                message_content = [*({'type': 'image'} for _ in range(len(json_sample["image"])))]
                message_content.append({
                        "type": "text",
                        "text": new_formatted})
                
                llm_prompt = [{"role":"user", "content": message_content}]
                text_phase_2 = processor.apply_chat_template(
                    llm_prompt, tokenize=False, add_generation_prompt=True
                )

                request = {
                    "prompt": text_phase_2,
                    "multi_modal_data": {"image": [images]},
                }
                outputs = llm.generate(request, sampling_params)
                out_text = outputs[0].outputs[0].text
                
                last_idx = min(len(codes) + 1, 3) # 累积 在json 文件中的 code_id
                key = f"code_ex{last_idx}"
                json_sample[key] = out_text # 添加新的code text到json_sample json文件
                all_outputs.append(out_text)
        else:
            raise ValueError
        
        
        def save_rollout_outputs(all_outputs, json_samples, sample_dir, sample_idx, max_idx):
            # Save .txt
            txt_path = os.path.join(sample_dir, f"all_rollouts_{max_idx}.txt")
            with open(txt_path, "w", encoding="utf-8") as f_txt:
                for i, out in enumerate(all_outputs, start=1):
                    f_txt.write(f"=== Rollout {i} ===\n")
                    f_txt.write(f"{out}\n\n")

            # Save .py scripts
            script_dir = os.path.join(sample_dir, f"scripts_turn_{max_idx}")
            os.makedirs(script_dir, exist_ok=True)
            for i, out in enumerate(all_outputs, start=1):
                script_path = os.path.join(script_dir, f"rollout_{i}.py")
                with open(script_path, "w", encoding="utf-8") as f_py:
                    f_py.write(f'# Sample {sample_idx} — Rollout {i}\n')
                    f_py.write(f'{out}\n\n')

            # Save .json
            json_path = os.path.join(sample_dir, f"rollouts_{max_idx}.json")
            with open(json_path, "w", encoding="utf-8") as f_json:
                json.dump(json_samples, f_json, ensure_ascii=False, indent=4)
                
        if phase == 1:
            max_idx = 1
            save_rollout_outputs(all_outputs, json_samples, sample_dir, sample_idx, max_idx)
        else:
            max_idx += 1
            max_idx = min(max_idx, 3)
            save_rollout_outputs(all_outputs, json_samples, sample_dir, sample_idx, max_idx)
            if max_idx == 3:
                print("!!!!!!The number of turns has been up to the limit!!!!!!!! \n")


    del llm
    cleanup_dist_env_and_memory()   # vLLM
    torch.cuda.empty_cache() # PyTorch cache clear
    if dist.is_initialized():
        print("Destroying distributed process group...")
        dist.destroy_process_group()

def Trajectory_extension(start=0 , end = 1 , root_dir = "Rollout/Counting"): # 以 rollout 最新的名字进行 给 trajectory 命名
    def numerical_sort_key(name):
        match = re.search(r'(\d+)', name)
        return int(match.group(1)) if match else float('inf')
    
    sample_names = sorted(os.listdir(root_dir), key=numerical_sort_key) # 文件名顺序
    
    sample_nums = []
    for name in sample_names:
        m = re.match(r'sample_(\d+)$', name)
        if m:
            sample_nums.append(int(m.group(1)))
            
    # 检查(start,end)内的sample_N是否全部存在
    for n in range(start+1, end+1):
        if n not in sample_nums:
            raise FileNotFoundError(f"file sample_{n} doesn't exists in {root_dir}")

    # 只保留start到end区间的文件名，并且顺序排序
    selected_sample_names = [f"sample_{n}" for n in range(start+1, end+1)]
    
    total_samples = len(selected_sample_names)
    print(f"Total {total_samples} samples to process .\n")
    # For server execution.
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
    # iterate through files in folder default: "./Rollout/Counting"
    for i, sample_name in enumerate(selected_sample_names, start=1):  # e.g. sample1,sample2 ...
        print(f"####processing {i}/{total_samples} for {sample_name}####\n")
        sample_dir = os.path.join(root_dir, sample_name)
        if not os.path.isdir(sample_dir):
            print(f"The sample's file: {sample_dir} is not a folder! Please Check")
            continue

        idx_rollout = -1 
        for fname in os.listdir(sample_dir): # 列出当前sample文件夹中所有的rollout json文件
            m = re.match(r"rollouts_(\d+)\.json$", fname)
            if m:
                idx_rollout = max(idx_rollout, int(m.group(1)))

        load_path = os.path.join(sample_dir, f"rollouts_{idx_rollout}.json")
        with open(load_path, 'r', encoding='utf-8') as f: # 加载最新的rollout json文件
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
                print(f" The Trajectory stops extension due to correct answer.\n")
                continue
            codes_keys = [k for k in json_sample.keys() if k.startswith("code_ex")]
            
            code_idx = -1
            for k in codes_keys:
                idx = int(k.replace("code_ex", ""))
                code_idx = max(code_idx, idx)
            interpreter_key = INTERPRETOR_KEY + f"{code_idx}"    # the latest `interpreterid`` is consistent with `code_ex_id`
            code_text = json_sample[f"code_ex{code_idx}"]        # 获取最新的code text进行运行 从json文件中提取对应的 `code text`
            
            # remove <code> tags
            if re.fullmatch(r"<code>.*?</code>", code_text.strip(), re.DOTALL):
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
                            if filtered.lower() == json_sample["GT"].lower():
                                acc_success += 1 # accuracy rate + 1
                                json_sample["final_solution"] = filtered
                                # print(f"The final result of code: {filtered}; and the Ground Truth: {json_sample['GT']}, current acc_success_num: {acc_success}")
                            else:
                                json_sample[interpreter_key] = f"The code ran successfully, but the final result:{filtered} does not match the ground truth. Adjust your solution and make some changes"
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
                json_sample[interpreter_key] = "Error: Use <code> </code> tags only, do not include markdown (e.g., python), text, or explanations."

        print(f"up to current {i}-th sample, execution_rate:{exe_success}/{exe_num} and accuracy_rate:{acc_success}/{acc_num}.\n")    
        # save as new json file for rollouts
        new_json_name = f"rollouts_trajectory_{code_idx}.json"
        new_json_path = os.path.join(sample_dir, new_json_name)
        with open(new_json_path, 'w', encoding='utf-8') as f:
            json.dump(json_samples, f, ensure_ascii=False, indent=4)

        print(f"finish: {sample_name}, generating: {new_json_path}\n")
        
    # calculate the execution result of all samples' trajectory(rollouts) for analysis
    execution_success_rate = round(exe_success / exe_num, 2) * 100
    accuracy_rate = round(acc_success/acc_num, 2) * 100
    return execution_success_rate, accuracy_rate

    
if __name__ == "__main__":
    import sys
    from datetime import datetime
    
    # --- Configuration ---
    CODE_KEY_PREFIX = "code_ex" # e.g., code_ex01, code_ex02
    MAX_CODE_EXECUTIONS_PER_ENTRY = 3 # Max number of code_exNN to check
    EXECUTION_TIMEOUT_SECONDS = 120
    INTERPRETOR_KEY = "interpreter"
    DELAY_BETWEEN_REQUESTS = 0.5
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
    config_file = "prompt_configuration_file.yaml"
    
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
    

    
    for i in range(1, MAX_CODE_EXECUTIONS_PER_ENTRY+1):
        vllm_inference(start=start,  # end-start: the numbers of qa extracted from all datasets
                       end = end, 
                       data_samples = spatial_samples_sub, 
                       output_root=output_root,
                       root_prefix= prefix, 
                       config_file=config_file,
                       )
        time.sleep(2)
        print(f"\n{i}-th turn inference finished!\n")
        execution_success_rate, accuracy_rate = Trajectory_extension(start=start, 
                                                             end=end, 
                                                             root_dir=output_root)
        print(f"\n{i}-th execution finished, and starting next turn!\n execution_success_rate:{execution_success_rate}%, accuracy_rate:{accuracy_rate}%\n")
        #
    print("All steps done.")
    sys.stdout.log.close()
