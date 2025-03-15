import sys
import os

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
print(root_dir)
from tools.object_detector.tool import Object_Detector_Tool 

tool = Object_Detector_Tool()
metadata = tool.get_metadata()

from transformers import Qwen2VLForConditionalGeneration, AutoTokenizer, AutoProcessor
from qwen_vl_utils import process_vision_info

# print(metadata)
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
            "output_type":"list - A list of detected objects with their scores, bounding boxes, and saved image paths.",
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
Your task: Firstly, Analyze the given question and determine the needed skills and tools from listed available tools.
Secondly, Generate a precise command to execute the selected tool based on the given information.

\nQuestion: {question} 

\nAvailable Tools: {available_tools}

\nTools Metadata: {toolbox_metadata}

\nInstructions:
1. Carefully review all provided information: the Question, images, listed available tools, and tool metadata.
2. Identify the main objectives or tasks within the Question, and determine sub-tasks that you think as necessary.
3. Analyze the tool's input_types from the metadata to understand required and optional parameters. 
4. Make sure to consider the user metadata for each tool, including limitations and potential applications (if available)
5. Record and Generate your entire reasoning and thinking process, and include it in your output.
6. Construct a command or series of commands that aligns with the tool's usage pattern and addresses the sub-tasks.
7. Ensure all required parameters are included and properly formatted.
8. If multiple steps are needed to prepare data for the tool, include them in the command construction.

\nOutput Format:

<Think> YOUR ENTIRE THINKING PROCESS HERE </Think>
<Command> YOUR PYTHON CODE HERE </Command>

\nRules:
1. The command MUST be valid Python code and include at least one call to `tool.execute()`(here tool can be instance of any available Tools' Class).
2. If lists available tools are insufficient to obtain the answer, you can use functions from Python's standard library as needed.
3. Use the exact parameter names as specified in the tool's input_types.
4. IF you need, Please directly use the PATHs of images: {image_paths}, which are related to Question
5. Do not include any code or text that is not part of the actual command.
6. In <Think> field, do not repeat and list the information about tools and metadata.
7. Always make sure to define variables and functions before using them to keep your Python code syntactically correct
8. Your code MUST produce a final result stored in a variable named RESULT, which can be used to directly answer the question.

\n REMENBER: Your <Command> </Command> field MUST be valid Python code including all necessary data preparation steps.
In <Think> </Think> filed is your entire reasoning and thinking process. But please do not repeat the information about tools.
Your MUST Output the thinking process in <Think> </Think> and Code in <Command> </Command> tags.
Again! Your MUST Output the thinking process in <Think> </Think> and Code in <Command> </Command> tags.
"""

##############################################################################################################################
relative_image_path = "examples/baseball.png"
image_path = os.path.join(root_dir,'tools','object_detector',relative_image_path)

Question = "Please tag all baseballs in image"

messages = [
    {
        "role": "system",
        "content" : [
            {"type": "text", "text": "You are a helpful, creative, and smart assistant."}
        ]
    }
    ,
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
    messages, tokenize=False, add_generation_prompt=False
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
generated_ids = model.generate(**inputs, max_new_tokens=1024, do_sample=False)
generated_ids_trimmed = [
    out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
]
output_text = processor.batch_decode(
    generated_ids_trimmed, skip_special_tokens=True
)


output_file = "result.txt"
with open(output_file, "w", encoding="utf-8") as f:
    f.write("\n".join(output_text))
