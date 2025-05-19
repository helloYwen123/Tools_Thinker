from transformers import Qwen2_5_VLForConditionalGeneration, AutoTokenizer, AutoProcessor
from qwen_vl_utils import process_vision_info
import torch
import transformers
import json
print(torch.cuda.is_available())
print(torch.cuda.device_count())
print(torch.cuda.get_device_name(0))
seed = 42
transformers.set_seed(seed)
import os
from PIL import Image
import random
# vLLM 相关
from vllm import LLM, EngineArgs, SamplingParams
from vllm.distributed import cleanup_dist_env_and_memory
from dataclasses import asdict
def main():
    # for ViRL Dataset
    def make_conversation_sat(example, prefix, conf):
        # get answer
        # here `prefix` is the prefix of the image path
        # `image_path` is from the dataset json file
        answer = example["answer"]
        answer = answer.replace("\\boxed{", "").replace("}", "")
        image_paths = [os.path.join(prefix, img_path) for img_path in example["images"]]
        images = [Image.open(path) for path in image_paths]
        idx = example["qid"]
        question=example["question"]
        question = question.replace("<image>\n", "")
        
        # get tools
        active_tools, filtered_meta = load_tool_data(conf)
        tools_list = ", ".join(active_tools)
        # get clear json file
        # meta_json = json.dumps(filtered_meta, ensure_ascii=False, indent=2)
        # toolbox_block = f"```json\n{meta_json}\n```"
        # Format the final prompt text using the provided strings

        final_solution = "\\box{}"
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
        import re
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

    # Load the dataset
    import yaml
    confiuration_file = "prompt_configuration_file.yaml"
    with open(confiuration_file, "r") as stream:
            conf = yaml.safe_load(stream)
    PROMPT_TEMPLATE = conf.get("prompt_template")

    dataset_prefix = "/nfs/data8/liao/wxie/ViRL_spatial/"  # "/nfs/data8/liao/wxie/ViRL_spatial/"
    dataset_path = "QA.json" # "SAT_subtasks/SAT_Counting.json" BLINK_Dataset/Counting/val/Counting_val.json

    all_samples = []

    full_path = os.path.join(dataset_prefix, dataset_path)
    with open(full_path, 'r') as f:
        raw_dataset = json.load(f)
        for sample in raw_dataset[0:50]:
            wrapped_data = make_conversation_sat(sample, dataset_prefix, conf) ##### contorlling the number of QA pairs
            all_samples.append(wrapped_data)
            
    # print(f"\nThe first sample:\n {all_samples[0]}\n")
    # # Print the first sample for debugging
    # print(f"\nThe first sample image path:\n {all_samples[0]['image_path']}\n")

    prompt = all_samples[0]['prompt'][0]["content"][-1]["text"]
    print(f"\nDebug for message prompt:\n{prompt}")

    # engine_args = EngineArgs(
    #     model="Qwen/Qwen2.5-VL-7B-Instruct",
    #     dtype="bfloat16",
    #     limit_mm_per_prompt={"image": 3},
    #     enforce_eager=False,
    #     enable_prefix_caching=True,
    #     max_model_len = 8192
    # )
    # llm = LLM(**asdict(engine_args))

    # sampling_params = SamplingParams(
    #     temperature=1.0, # highly diverse
    #     max_tokens=1024,
    # )

    # processor = AutoProcessor.from_pretrained(
    #     "Qwen/Qwen2.5-VL-7B-Instruct", use_fast=True
    # )
    
    # # 开始历遍所有samples data
    # output_root = "Rollout/Counting"
    # os.makedirs(output_root, exist_ok=True)
    # PROMPT_SHOW = True
    # for sample_idx, sample in enumerate(all_samples):
    #     sample_dir = os.path.join(output_root, f"sample_{sample_idx}")
    #     os.makedirs(sample_dir, exist_ok=True)
        
    #     #Preparation for inference
    #     text = processor.apply_chat_template(
    #         sample["prompt"], tokenize=False, add_generation_prompt=True
    #     )
    #     images = sample["image"]
        
    #     request = {
    #         "prompt": text,
    #         "multi_modal_data": {"image": [images]},
    #     }
    #     _ = llm.generate(request, sampling_params)

    #     # multi-turn outputs
    #     all_outputs = [] # 当前这个sample的rollout outputs(create n trajectory ; extent n trajectory)
    #     # 确定最新的rollout json trajectory文件
    #     rollout_files = []
    #     import re
    #     for fname in os.listdir(sample_dir): # 列出当前sample文件夹中所有的rollout trajectory json文件
    #         m = re.match(r"rollouts_trajectory_(\d+)\.json$", fname)
    #         if m:
    #             idx = int(m.group(1))
    #             rollout_files.append((idx, fname))
    #     # 如果上述确定rollout json文件失败则确定是第一轮rollout 否则进入读取rollout json读取阶段
    #     # 用json中的code text 更新 prompt template
    #     if rollout_files:
    #         phase = 2 # trajectory extent phase
    #         max_idx, latest_fname = max(rollout_files, key=lambda x: x[0]) # 找到最新的轨迹json文件 并加载
    #         # json_samples = {"image", "question", "QAid", "GT", "code_ex_i"}
    #         load_path = os.path.join(sample_dir, latest_fname)
    #         print(f"[Sample {sample_idx}] Phase 2: load {latest_fname}")
    #         with open(load_path, 'r', encoding='utf-8') as f:
    #             json_samples = json.load(f)
    #     else:
    #         phase = 1 # rollout seeds phase
    #         json_samples = []
    #         print(f"[Sample {sample_idx}] Phase 1: start initial rollouts")
            
    #     if phase == 1:
    #         for _ in range(20):
    #             # 开始创建轨迹trajectory n
    #             # every sample(1 qa) rollout 20 times; 大循环下对单个QA进行读取； 小循环对这个qa用模型(vLLM)推理20轮
    #             ###### here to control the number of rollouts, e.g. 20
    #             # Rollout starting
    #             outputs = llm.generate(request, sampling_params)
    #             out_text = outputs[0].outputs[0].text

    #             json_sample = {
    #                 "image": sample["image_path"],
    #                 "question": sample["question"],
    #                 "QAid": sample["QAid"],
    #                 "rolloutID": str(id+1),
    #                 "GT": sample["solution"],
    #                 "code_ex1": out_text
    #             }
    #             # 初始化轨迹 json 文件
    #             json_samples.append(json_sample)
    #             # all_outputs.txt 文件填充
    #             all_outputs.append(out_text)
    #             # Rollout ending
                
    #     elif phase == 2:
    #         # 开始延展轨迹trajectory in rollout json
    #         prompt_kwargs = sample["kwargs"]
    #         for json_sample in json_samples:
    #             codes = [k for k in json_sample.keys() if k.startswith("code_ex")] # here is from json files
    #             for k in codes:
    #                 # 从已有的json trajectory中更新prompt; 用新生成的code 更新prompt template
    #                 idx = int(k.replace("code_ex", ""))
    #                 #code_text = json_sample[k].replace("\n", "\\n") # TODO check whether is better
    #                 code_text = json_sample[k]
    #                 prompt_kwargs[f"code_example{idx}"] = code_text

    #             # Note：
    #             # interpreter 的添加在code执行端也就是medeira端
                
    #             interpreters = [k for k in json_sample.keys() if k.startswith("interpretor")] # here is from json files
    #             for k in interpreters:
    #                  # 从已有的json trajectory中更新prompt; 用新生成的interpreter 更新prompt template
    #                 idx = int(k.replace("interpretor", ""))
    #                 # code_text = json_sample[k].replace("\n", "\\n") # TODO check whether is better
    #                 interpreter_text = json_sample[k]
    #                 prompt_kwargs[f"interpreter{idx}"] = interpreter_text
                
    #             new_formatted = PROMPT_TEMPLATE.format(**prompt_kwargs)
    #             if PROMPT_SHOW:
    #                 print(f"new_formatted: {new_formatted}\n")
    #                 PROMPT_SHOW = False
    #             # break
    #             message_content = [*({'type': 'image'} for _ in range(len(json_sample["image"])))]
    #             message_content.append({
    #                     "type": "text",
    #                     "text": new_formatted})
                
    #             llm_prompt = [{"role":"user", "content": message_content}]
    #             text_phase_2 = processor.apply_chat_template(
    #                 llm_prompt, tokenize=False, add_generation_prompt=True
    #             )

    #             request = {
    #                 "prompt": text_phase_2,
    #                 "multi_modal_data": {"image": [images]},
    #             }
    #             outputs = llm.generate(request, sampling_params)
    #             out_text = outputs[0].outputs[0].text
    #             last_idx = len(codes) + 1
    #             key = f"code_ex{last_idx}"
    #             json_sample[key] = out_text # 添加新的code text到json_sample json文件
    #             all_outputs.append(out_text)
    #     else:
    #         raise ValueError
        
    #     max_idx = 0
    #     idxs = [int(k.replace("code_ex","")) for k in json_samples[0].keys() if k.startswith("code_ex")]
    #     if idxs:
    #         max_idx = max(max_idx, max(idxs))
    #     # saving response as `txt` file，`python` file，以及供dowmstream处理的 `json` file
    #     # all_outputs: 这个qa下进行推理n轮的结果；
    #     # json_samples: 这个qa下进行推理n轮的结果(json格式)
    #     txt_path = os.path.join(sample_dir, f"all_rollouts_{max_idx}.txt")
    #     with open(txt_path, "w", encoding="utf-8") as f_txt:
    #         for i, out in enumerate(all_outputs, start=1):
    #             f_txt.write(f"=== Rollout {i} ===\n")
    #             f_txt.write(f"{out}\n\n")
                
    #     script_dir = os.path.join(sample_dir, f"scipts_turn_{max_idx}")
    #     os.makedirs(script_dir, exist_ok=True) # create script dir
    #     for i, out in enumerate(all_outputs, start=1):
    #         script_path = os.path.join(script_dir, f"rollout_{i}.py")
    #         with open(script_path, "w", encoding="utf-8") as f_py:
    #             f_py.write(f'# Sample {sample_idx} — Rollout {i}\n')
    #             f_py.write(f'{out}\n\n')
                
    #     json_path = os.path.join(sample_dir, f"rollouts_{max_idx}.json")
    #     with open(json_path, "w", encoding="utf-8") as f_json:
    #         json.dump(json_samples, f_json, ensure_ascii=False, indent=4)
            

    
if __name__ == "__main__":
    main()
    import atexit
    import torch.distributed as dist

    def cleanup():
        if dist.is_initialized():
            dist.destroy_process_group()

    atexit.register(cleanup)
