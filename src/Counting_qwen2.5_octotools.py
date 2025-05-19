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

# for SAT Dataset
def make_conversation_sat(example, prefix, conf):
    # get answer
    # here `prefix` is the prefix of the image path
    # `image_path` is from the dataset json file
    answer = example["messages"][1]["content"].strip()
    image_paths = [os.path.join(prefix, img_path) for img_path in example["images"]]
    images = [Image.open(path) for path in image_paths]
    idx = os.path.splitext(os.path.basename(example["images"][0]))[0]  # image name as index
    question=example["messages"][0]["content"].strip()
    question = question.replace("<image> Answer in natural language. ", "")
    
    # get tools
    active_tools, filtered_meta = load_tool_data(conf)
    tools_list = ", ".join(active_tools)
    # get clear json file
    # meta_json = json.dumps(filtered_meta, ensure_ascii=False, indent=2)
    # toolbox_block = f"```json\n{meta_json}\n```"
    # Format the final prompt text using the provided strings
    
    code01 = """
<code>

</code>"""
    sandbox_feedback01 = """<sandbox_feedback>

</sandbox_feedback>"""
    code02 = """
<code>

</code>
"""
    sandbox_feedback02 = """<sandbox_feedback>

</sandbox_feedback>"""
    # Format the final prompt text using the provided strings
    formatted_question_part = PROMPT_TEMPLATE.format(
    question=question,
    image_paths=", ".join(image_paths),
    available_tools=tools_list,        # Use the pre-formatted string
    toolbox_metadata=filtered_meta, # Use the filtered metadata string
    code_examples1 = "<code> </code>", # "<code> </code>",
    interpreter01 = "<interpreter> </interpreter>", # "<sandbox_feedback> </sandbox_feedback>",
    code_examples2 = "<code> </code>", # "<code> </code>",
    interpreter02 = "<interpreter> </interpreter>", # "<sandbox_feedback> </sandbox_feedback>",
    code_examples3 = "<code> </code>", # "<code> </code>",
    interpreter3 = "<interpreter> </interpreter>", # "<sandbox_feedback> </sandbox_feedback>",
    )
    message_content = [*({'type': 'image'} for _ in range(len(example["images"])))]
    message_content.append({
                    "type": "text",
                    "text": formatted_question_part
                })
    
    return {"image": images, # images 
        "image_path": image_paths,
        "prompt": [
            {
                "role": "user",
                "content": message_content,
            },
        ],
        "solution": answer, 
        "QAid": idx
    }
# Blink Dataset
# def make_conversation_sat(example, prefix, conf):
#         # get answer
#         answer = example["answer"].strip("()")
#         image_paths = [os.path.join(prefix, img_path) for img_path in example["image_paths"]]
#         images = [Image.open(path) for path in image_paths ]
#         idx = example["idx"]
        
#         # get tools
#         active_tools, filtered_meta = load_tool_data(conf)
#         tools_list = ", ".join(active_tools)
#         # get clear json file
#         meta_json = json.dumps(filtered_meta, ensure_ascii=False, indent=2)
#         toolbox_block = f"```json\n{meta_json}\n```"
        
#         code01 = """
# <code>

# </code>"""
#         sandbox_feedback01 = """<sandbox_feedback>

# </sandbox_feedback>"""
#         code02 = """
# <code>

# </code>
# """
#         sandbox_feedback02 = """<sandbox_feedback>

# </sandbox_feedback>"""
#         # Format the final prompt text using the provided strings
#         formatted_question_part = PROMPT_TEMPLATE.format(
#         question=example["prompt"],
#         image_paths=", ".join(image_paths),
#         available_tools=tools_list,        # Use the pre-formatted string
#         toolbox_metadata=toolbox_block, # Use the filtered metadata string
#         code_examples01 = "<code> </code>", # "<code> </code>",
#         sandbox_feedback01 = "<sandbox_feedback> </sandbox_feedback>", # "<sandbox_feedback> </sandbox_feedback>",
#         code_examples02 = "<code> </code>", # "<code> </code>",
#         sandbox_feedback02 = "<sandbox_feedback> </sandbox_feedback>", # "<sandbox_feedback> </sandbox_feedback>",
#         code_examples03 = "<code> </code>", # "<code> </code>",
#         sandbox_feedback03 = "<sandbox_feedback> </sandbox_feedback>", # "<sandbox_feedback> </sandbox_feedback>",
#         )
        
#         image_paths = [os.path.join(prefix, img_path) for img_path in example["image_paths"]]

#         message_content = [*({'type': 'image'} for _ in range(len(image_paths)))]
#         message_content.append({
#                         "type": "text",
#                         "text": formatted_question_part
#                     })
        
#         return {"image": images, # images 
#             "image_path": image_paths,
#             "prompt": [
#                 {
#                     "role": "user",
#                     "content": message_content,
#                 },
#             ],
#             "solution": answer, ###
#             "QAid": idx
#         }

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

# Load the model and processor
# default: Load the model on the available device(s)
model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
    "Qwen/Qwen2.5-VL-3B-Instruct", torch_dtype=torch.bfloat16, device_map="auto", attn_implementation="flash_attention_2", 
)
# default processer
processor = AutoProcessor.from_pretrained("Qwen/Qwen2.5-VL-3B-Instruct", use_fast=True)

# Load the dataset
import yaml
confiuration_file = "prompt_configuration_file.yaml"
with open(confiuration_file, "r") as stream:
        conf = yaml.safe_load(stream)
PROMPT_TEMPLATE = conf.get("prompt_template")

dataset_prefix = "/home/stud/wxie/SAT/"  # "/nfs/data8/liao/wxie/SAT/"  # "/home/stud/wxie/"
dataset_path = "SAT_subtasks/SAT_Counting.json" # "SAT_subtasks/SAT_Counting.json" BLINK_Dataset/Counting/val/Counting_val.json

all_samples = []
full_path = os.path.join(dataset_prefix, dataset_path)
with open(full_path, 'r') as f:
    raw_dataset = json.load(f)
    for sample in raw_dataset[0:2]: ##### contorlling the number of QA pairs
        all_samples.append(make_conversation_sat(sample, dataset_prefix, conf))

print(f"\nThe first sample:\n {all_samples[0]}\n")
# Print the first sample for debugging
print(f"\nThe first sample image path:\n {all_samples[0]['image_path']}\n")

prompt = all_samples[0]['prompt'][0]["content"][-1]["text"]
print(f"\nDebug for message prompt:\n{prompt}")

for sample_idx, sample in enumerate(all_samples):
    
    #Preparation for inference
    text = processor.apply_chat_template(
        sample["prompt"], tokenize=False, add_generation_prompt=True
    )
    images = sample["image"]
    inputs = processor(
        text=[text],
        images=images,
        padding=True,
        padding_side="left",
        add_special_tokens=False,
        return_tensors="pt",
    )
    inputs = inputs.to("cuda")

    # multi-turn outputs
    all_outputs = []
    ###### here to control the number of rollouts, e.g. 5
    for _ in range(20):
        # Inference: Generation of the output
        generated_ids = model.generate(**inputs, max_new_tokens=1024, do_sample= True, temperature= 1.0)
        generated_ids_trimmed = [
            out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        output_text = processor.batch_decode(
            generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )
        all_outputs.append(f"output rollout response: \n{output_text[0]}\n")

    output_dir = "Rollout/Counting"
    os.makedirs(output_dir, exist_ok=True)

    # === Write to txt file ===
    output_file = os.path.join(output_dir, f"sample_{sample_idx}.txt")
    with open(output_file, "w", encoding="utf-8") as f:
        for i, output in enumerate(all_outputs):
            f.write(f"=== Sample {i+1} ===\n")
            f.write(output + "\n\n")

    print(f"Saved {sample_idx} to {output_file}")

# # Save the generated code to a file
# file_path = "generated_code.py"

# with open(file_path, "a", encoding="utf-8") as file:  # Use "a" mode to append
#     file.write("\n\n#### Sample Index: {} ####\n\n".format(sample_idx))
#     file.write("#### Query ####\n\n")
#     file.write(query_text)
#     file.write("\n\n#### Generated Code ####\n\n")
#     file.write(output_text)
#     file.write("\n")

# print(output_text)
# print(f"Python code has been saved in {file_path}")