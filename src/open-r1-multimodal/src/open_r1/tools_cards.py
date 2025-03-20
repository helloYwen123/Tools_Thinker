import sys
import os
import re
import time
import torch
import transformers
from transformers import pipeline
import torch.utils.data
from datasets import Dataset, IterableDataset
import signal
import runpy
import asyncio
import subprocess
from PIL import Image, ImageOps
from math_verify import parse, verify
from datetime import datetime
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
\n Write a Python program to answer the question related to images : {question}.
Enclose the generated code and comments in <command> </command> tags, 
i.e. <command> generated python code </command>.
You need to use the following available tools, which are very helpful for you.
\n Available Tools: {available_tools}
\n Tools Metadata: {toolbox_metadata}
\n Rules:
1. The command MUST be valid Python code.
2. If listed available tools are insufficient to obtain the answer, you can use functions from Python's standard library as needed.
3. Use the exact parameter names as specified in the tool's input_types.
4. If you need, please directly use the PATHs of images: {image_paths}, which are related to Question
5. Always make sure to define variables and functions before using them to keep your Python code syntactically correct
6. Ensure that the code execution yields a result that directly answers the question.

\n Remember:
You must output the tag <command> </command>. You can include your thoughts on the code and your step-by-step understanding and analysis of the problem as comments between code blocks.
In <command> </command> field MUST be valid Python code including all necessary data preparation steps.
Do not import any the available tool from module in the code, Again! Do not import any the available tool from module!!. 
Your code must return a final result that serves as the answer to the question. 
Please assign the final answer to a variable named "final_result".
Again! The code must return a final result that directly serves as the answer to the question. 
Please assign the final answer to a variable named "final_result".
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
completions = processor.batch_decode(
    generated_ids_trimmed, skip_special_tokens=True
)

############################################################################
#################################DEBUG######################################
completions_path = os.path.join(root_dir,"debug","completions_debug.txt")
os.makedirs(os.path.dirname(completions_path), exist_ok=True)
with open(completions_path, "w") as f:
    for completion in completions:
        f.write(f"{completion} \n")
############################################################################        
    
############################################################################
def extract_code(completion):
    match = re.search(r"<command>(.*?)</command>", completion , re.DOTALL)
    if match:
        extracted_code = match.group(1).strip()  
        return extracted_code
    else:
        raise ValueError("no command tag found!!")

# waiting to be extended
api_methods = {
    "object_detector": 
"""
import sys
import os
import time
import torch
from transformers import pipeline
sys.path.insert(0, "{root_dir}")
from tools.base import BaseTool
from PIL import Image, ImageOps
import os
import sys
import warnings
from tools.object_detector.tool import Object_Detector_Tool 
"""
}
#####################
generated_code = extract_code(completions[0])

generated_code = """
tool = Object_Detector_Tool()
metadata = tool.get_metadata()
# tool.set_custom_output_dir("detected_objects")


# print(metadata)

relative_image_path = "examples/baseball.png"
image_path = os.path.join("/home/stud/wxie/Tools_Thinker","tools","object_detector", relative_image_path)

# Execute the tool
try:
    execution = tool.execute(image=image_path, labels=["baseball"], padding=20)
    print("Detected Objects:")
    for obj in execution:
        print(f"Detected {obj['label']} with confidence {obj['confidence score']}")
        print(f"Bounding box: {obj['box']}")
        print(f"Saved image (with padding): {obj['saved_image_path']}")
        print()
except ValueError as e: 
    print(f"Execution failed: {e}")
    
final_result = len(execution)

print("Done!")
"""

full_code = [api_methods["object_detector"].format(root_dir = root_dir) + "\n" + generated_code + "\n"+"print('<final_result>', final_result)"]

# print(full_code)
solutions = ["20"]

def code_exec_acc_reward(completions, solutions):
    """
    running code snippets in completions and return the results.
    If an error occurs during execution, return "0".
    Use asyncio.run to automatically create and manage event loops.
    """
    async def run_all_codes(codes: list[str], solutions: list[str]) -> list[float]:
        """
        Asynchronously run multiple code snippets.
        """
        tasks = [run_code_async(code, sol, 60) for code, sol in zip(codes, solutions)]
        rewards = await asyncio.gather(*tasks)
        return rewards
    
    async def run_code_async(code: str, solution: str, exec_timeout: int = 10) -> float:
        """
        Run a code snippet asynchronously and evaluate the result.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                'python3', '-c', code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=exec_timeout)
            if proc.returncode != 0:
                log_path = os.path.join(root_dir, "logs", "evaluation.log")
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
                with open(log_path, "w") as f:
                    f.write(f"------------- {current_time} Process Error: {proc.returncode} -------------\n")
                    f.write(f"Error in code execution: \n{stderr.decode().strip()}\n")
                    f.write(f"Code: {code}\n\n")
                    f.write(f"Solution: {solution}\n")
                return 0.0
            output_raw = stdout.decode().strip()
        except Exception as e:
            log_path = os.path.join(root_dir, "logs", "evaluation.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
            with open(log_path, "w") as f:
                f.write(f"------------- {current_time} Exception in run_code_async -------------\n")
                f.write(f"Exception: in create subproess \n{str(e)}\n")
                f.write(f"Code: {code}\n\n")
                f.write(f"Solution: {solution}\n")
            return 0.0
        
        output = None
        
        try:
            for line in output_raw.splitlines():
                if line.startswith("<final_result>"):
                    output = line[len("<final_result>"):].strip()
                    break
        except Exception as e:
            log_path = os.path.join(root_dir, "logs", "evaluation.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
            with open(log_path, "w") as f:
                f.write(f"------------- {current_time} Exception in run_code_async -------------\n")
                f.write(f"Exception in extract final result: \n{str(e)}\n")
                f.write(f"Code: {code}\n\n")
                f.write(f"Solution: {solution}\n")
            return 0.0
            
        reward = 0.0
        # try to parse the output and solution to do symbolic verification
        try:
            answer = parse(output)
            sol_parsed = parse(solution)
            if float(verify(answer, sol_parsed)) > 0:
                reward = 1.0
        except Exception:
            pass

        # 
        if reward == 0.0:
            try:
                # get Ground Truth from solution
                ground_truth = solution
                student_answer = output
                if student_answer == ground_truth:
                    reward = 1.0
            except Exception:
                raise Exception("Error in comparison for ground truth!")

        log_path = os.path.join(root_dir, "logs", "evaluation.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
        with open(log_path, "w") as f:
            f.write(f"------------- {current_time} Accuracy reward: {reward} -------------\n")
            f.write(f"Code: {code}\n\n")
            f.write(f"Final Result: {output}\n\n")
            f.write(f"Solution: {solution}\n")
        return reward
        
    return asyncio.run(run_all_codes(completions,solutions=solutions))

    
results = code_exec_acc_reward(full_code,solutions=solutions)

for idx, result in enumerate(results):
    print(f"code snippet {idx} result: {result}")