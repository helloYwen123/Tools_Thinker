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

# Import libraries
import os
from PIL import Image
import random
# vLLM related
from vllm import LLM, EngineArgs, SamplingParams
from vllm.distributed import cleanup_dist_env_and_memory
from dataclasses import asdict

def vllm_inference(start=-1, end=-1 , 
                   data_samples = None, 
                   output_root="Rollout", 
                   root_prefix = "/datasets", 
                   config_file="configuration_file.yaml", 
                   dataset=""):
    # default: all samples
    if start == -1:
        start = 0
    if end == -1:
        end = len(data_samples)
    # for SAT Dataset
    def make_conversation_sat(example, prefix):
        # transform the example into a SAT-conversation format
        image_paths = [os.path.join(prefix, img_path) for img_path in example["images"]]
        images = [Image.open(path) for path in image_paths]
        idx = example["idx"]  # image name as index
        # question=example["messages"][0]["content"].strip()
        question = example["original_question"]
        question = question.lower()
        # answer = example["messages"][1]["content"].strip()
        answer = example["original_answer"].strip()
        formatted = PROMPT_TEMPLATE.format(question=question)
        
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
        }
###################################################################################################################
    # vLLM inference function for SAT-Format dataset
    
    # Load the configuration file
    confiuration_file = config_file
    with open(confiuration_file, "r") as stream:
            conf = yaml.safe_load(stream)
    PROMPT_TEMPLATE = conf.get("prompt_template")
    print(f"Loaded PROMPT_TEMPLATE:\n{PROMPT_TEMPLATE}")

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
        wrapped_data = make_conversation_sat(sample, dataset_prefix)
        all_samples.append(wrapped_data)

    # print(f"\nThe first sample:\n {all_samples[0]}\n")
    # # Print the first sample for debugging
    # print(f"\nThe first sample image path:\n {all_samples[0]['image_path']}\n")

    engine_args = EngineArgs(
        model="Qwen/Qwen2-VL-7B-Instruct",
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
        temperature=0.5, # appoximate greedy sampling
        max_tokens=1024,
    )

    processor = AutoProcessor.from_pretrained(
        "Qwen/Qwen2-VL-7B-Instruct", use_fast=True
    )
    
    correct_count = 0
    total_count = 0
    
    all_outputs = []
    # genreate idx from `start` to `end`
    for sample_idx, sample in zip(range(start+1, end+1), all_samples):
        print(f"\nProcessing sample {sample_idx}.\n")
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
        
        # For debug
        prompt = all_samples[sample_idx-1]['prompt'][0]["content"][-1]["text"]
        print(f"\nDebug for message prompt:\n{prompt}")

        # Rollout starting
        outputs = llm.generate(request, sampling_params)
        out_text = outputs[0].outputs[0].text
        time.sleep(1)# wait for the output to be ready
        json_sample = {
            "question": sample["question"],
            "sampleID": sample_idx,
            "QAid": sample["QAid"],
            "GT": sample["solution"],
            "response": out_text,
        }
        print(f"Sample {sample_idx} response:\n{out_text}\n")
        
        all_outputs.append(json_sample)
        
        # Calculate the accracy
        import re
        def extract_boxed(text):
            BOXED_PATTERN = re.compile(r'\\boxed\s*\{(.*?)\}', re.DOTALL)
            matches = BOXED_PATTERN.findall(text)
            if matches:
                return [m.strip() for m in matches]
            return None
        
        gt_answer = sample["solution"].strip()
        
        extracted_answer = extract_boxed(out_text)[0] if extract_boxed(out_text) else out_text.strip()
        total_count += 1
        if extracted_answer is not None and extracted_answer.lower() == gt_answer.lower():
            print(f"Question {sample['question']} is correct. GT: {gt_answer}, Response: {extracted_answer}")
            correct_count += 1
        current_accuracy = correct_count / total_count * 100
        print(f"SampleID {sample_idx} => GT: {gt_answer}, Model Answer: {extracted_answer}")
        print(f"Current accuracy: {current_accuracy:.2f}% ({correct_count}/{total_count})\n")
        
    # Rollout ending
    vllmoutput_json_path = os.path.join(output_root, f"{dataset}_vllm_output.json")
    result = {
        "accuracy": current_accuracy,
        "inference": all_outputs,
    }
    with open(vllmoutput_json_path, "w", encoding="utf-8") as f_out:
        json.dump(result, f_out, ensure_ascii=False, indent=4)
            

    del llm
    cleanup_dist_env_and_memory()   # vLLM
    torch.cuda.empty_cache() # PyTorch cache clear
    if dist.is_initialized():
        print("Destroying distributed process group...")
        dist.destroy_process_group()

if __name__ == "__main__":
    import sys
    from datetime import datetime
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--json_path", type=str, required=True, help="Path to dataset JSON file")
    parser.add_argument("--output_root", type=str, required=True, help="Path to output root directory")
    parser.add_argument("--dataset", type=str, default="dataset", help="name prefix of dataset")
    parser.add_argument("--start", type=int, default=-1, help="Start index")
    parser.add_argument("--end", type=int, default=-1, help="End index")
    parser.add_argument('--spatial', action='store_true', help="spatial reasoning samples or not")
    args = parser.parse_args()
    
    json_path = args.json_path
    dataset = args.dataset
    start = args.start
    end = args.end
    output_root = args.output_root
    spatial = args.spatial
    
    
    
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
    config_file = "prompt_configuration_file_nocode.yaml"
    
    # Load the dataset
    with open(json_path, 'r') as f:
        raw_dataset = json.load(f)
        
    output_indices_file = os.path.join(output_root, f"spatial_selected_indices.json")
    # create output directory
    if not os.path.exists(output_root):
        os.makedirs(output_root)
    
    # LOGGING
    print(f"Final output_root: {output_root}")
    log_file = os.path.join(output_root, f"{dataset}_log-{timestamp}.txt")
    sys.stdout = Logger(log_file)
    sys.stderr = sys.stdout
    print(f"Log file created at: {log_file}\n")
    
    if spatial:
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

            if start == -1:
                start = 0
            if end == -1:
                end = len(spatial_samples)
            
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
    else:
        if start == -1:
            start = 0
        if end == -1:
            end = len(raw_dataset)
        # For non-spatial reasoning samples, use the whole dataset
        output_indices_file = os.path.join(output_root, f"nonspatial_selected_indices.json")
        random.shuffle(raw_dataset)
        spatial_samples_sub = raw_dataset[start:end]
        selected_indices = [sample["idx"] for sample in spatial_samples_sub]
        with open(output_indices_file, "w", encoding="utf-8") as f_out:
            json.dump(selected_indices, f_out, ensure_ascii=False, indent=4)
        print("Non-spatial reasoning samples selected.\n")
        
   
    vllm_inference( start=start,  # end-start: the numbers of qa extracted from all datasets
                    end=end,
                    data_samples = spatial_samples_sub,
                    output_root=output_root,
                    root_prefix= prefix,
                    config_file=config_file,
                    dataset = dataset
                    )
    time.sleep(0.5)
    print("All steps done.")
    sys.stdout.log.close()
