import sys
import os
import re
import time
import torch
import transformers
from transformers import pipeline
import torch.utils.data
from datasets import Dataset, IterableDataset

from PIL import Image, ImageOps

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))))
sys.path.insert(0, root_dir)

from tools.object_detector.tool import Object_Detector_Tool 

from transformers import Qwen2VLForConditionalGeneration,Qwen2_5_VLForConditionalGeneration, AutoTokenizer, AutoProcessor
from qwen_vl_utils import process_vision_info

# loading model using Qwen2VL (from_pretrained)
model = Qwen2VLForConditionalGeneration.from_pretrained(
    "Qwen/Qwen2-VL-2B-Instruct", torch_dtype=torch.bfloat16, device_map="auto"
)
# Processor(from_pretrained)
processor = AutoProcessor.from_pretrained("Qwen/Qwen2-VL-2B-Instruct")

# The default range for the number of visual tokens per image in the model is 4-16384. You can set min_pixels and max_pixels according to your needs, such as a token count range of 256-1280, to balance speed and memory usage.
# min_pixels = 256*28*28
# max_pixels = 1280*28*28
# processor = AutoProcessor.from_pretrained("Qwen/Qwen2-VL-2B-Instruct", min_pixels=min_pixels, max_pixels=max_pixels)


toolbox_metadata = {
    "Object_Detector_Tool":{ "tool_name":"Object_Detector_Tool",
            "tool_description":"A tool that detects objects in an image using the Grounding DINO model and saves individual object images with empty padding.",
            "tool_version":"1.0.0",
            "input_types":{
                "image": "str - The path to the image file.",
                "labels": "list - A list of object labels to detect.",
                "threshold": "float - The confidence threshold for detection (default: 0.35).",
                "model_size": "str - The size of the model to use ('tiny' or 'base', default: 'tiny').",
                "padding": "int - The number of pixels to add as empty padding around detected objects (default: 20)."
            },
            "output_type":"list - A list of detected objects dictionaries with ('label';'confidence score';'box';'saved_image_path')keys and their corresponding values",
            "demo_commands":[
                {
                    "command": 'execution = tool.execute(image="path/to/image.png", labels=["baseball", "basket"])',
                    "description": "Detect baseball and basket in an image, save the detected objects with default empty padding, and return their paths."
                },
                {
                    "command": 'execution = tool.execute(image="path/to/image.png", labels=["car", "person"], threshold=0.5, model_size="base", padding=15)',
                    "description": "Detect car and person in an image using the base model, save the detected objects with 15 pixels of empty padding, and return their paths."
                }
            ],
            "user_metadata":{
                "limitation": "The model may not always detect objects accurately, and its performance can vary depending on the input image and the associated labels. It typically struggles with detecting small objects, objects that are uncommon, or objects with limited or specific attributes. For improved accuracy or better detection in certain situations, consider using supplementary tools or image processing techniques to provide additional information for verification."
            }
    }
}

available_tools= ["Object_Detector_Tool"]


PROMPT_TEMPLATE= """
\n Question: {question}. Answer question through writing valid python command
Output the thinking process in <think> </think>, code in <command> </command> and result variable's name in <result> </result>, 
i.e., <think> tools selection reasoning and coding reasoning here </think>, <command> python code here </command> and <result> the name of result variable in code </result>.

\n Available Tools: {available_tools}

\n Tools Metadata: {toolbox_metadata}

\n Rules:
1. The command MUST be valid Python code and include at least one call to `tool.execute()`(here tool can be instance of any available Tools' Class).
2. If listed available tools are insufficient to obtain the answer, you can use functions from Python's standard library as needed.
3. Use the exact parameter names as specified in the tool's input_types.
4. If you need, please directly use the PATHs of images: {image_paths}, which are related to Question
5. Do not import modules for tool classes in the header, use these modules and their functions directly by default.
6. Always make sure to define variables and functions before using them to keep your Python code syntactically correct
7. Code's result must be exactly the final answer to the question.

\n Remember:In <think> </think> filed is your entire reasoning and thinking process. 
In <command> </command> field MUST be valid Python code including all necessary data preparation steps.
The <result> </result> field is where you should place the name of final result variable from your code.
You must Output three types of tags <think> </think>, <command> </command> and <result> </result>.
The Code's result variable must be exactly the final answer to the question.
Again!!! The Code's result variable must be exactly the final answer to the question.
"""

##############################################################################################################################
relative_image_path = "examples/baseball.png"
image_path = os.path.join(root_dir,'tools','object_detector',relative_image_path)

Question = "How many baseballs are there in the image"

messages = [
    {
        "role": "user",
        "content": [
            {"type": "image",},
            {"type": "text", "text": PROMPT_TEMPLATE.format(question = Question,
                                                            image_paths = image_path, 
                                                            available_tools=available_tools,
                                                            toolbox_metadata = toolbox_metadata)},
        ],
    }
]

# Preparation for inference
text = processor.apply_chat_template(
    messages, tokenize=False, add_generation_prompt=True
)
image = Image.open(image_path)
# image_inputs, video_inputs = process_vision_info(messages)
inputs = processor(
    text=[text],
    images=image,
    padding=True,
    return_tensors="pt",
    add_special_tokens=False,
    padding_side="left"
)

inputs = inputs.to("cuda")


# Inference: Generation of the output
generated_ids = model.generate(**inputs, max_new_tokens=1024)

generated_ids_trimmed = [
    out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
]
output_text = processor.batch_decode(
    generated_ids_trimmed, skip_special_tokens=True
)

output_file = "result.txt"
with open(output_file, "w", encoding="utf-8") as f:
    f.write("\n".join(output_text))

def format_reward(completions, **kwargs):
    """Reward function that checks if the completion has a specific format."""
    pattern = r"<think>.*?</think>\s*<answer>.*?</answer>"
    if isinstance(completions[0],str):
        completion_contents = ["<think>" + completion for completion in completions]
    else:
        completion_contents = [completion[0]["content"] for completion in completions]
    matches = [re.fullmatch(pattern, content, re.DOTALL) for content in completion_contents]
    return [1.0 if match else 0.0 for match in matches]