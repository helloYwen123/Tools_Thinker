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
from math_verify import parse, verify
from datetime import datetime
import asyncio
import subprocess
import traceback
from PIL import Image, ImageOps

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.join(os.path.dirname(os.path.dirname(current_dir)))

from object_detector.tool import Object_Detector_Tool 

from transformers import Qwen2VLForConditionalGeneration,Qwen2_5_VLForConditionalGeneration, AutoTokenizer, AutoProcessor
from qwen_vl_utils import process_vision_info

# loading model using Qwen2VL (from_pretrained)
model = Qwen2VLForConditionalGeneration.from_pretrained(
    "Qwen/Qwen2-VL-2B-Instruct", torch_dtype=torch.bfloat16, attn_implementation="flash_attention_2",device_map="cuda:0"
)
# Processor(from_pretrained)
processor = AutoProcessor.from_pretrained("Qwen/Qwen2-VL-2B-Instruct")

# The default range for the number of visual tokens per image in the model is 4-16384. You can set min_pixels and max_pixels according to your needs, such as a token count range of 256-1280, to balance speed and memory usage.
# min_pixels = 256*28*28
# max_pixels = 1280*28*28
# processor = AutoProcessor.from_pretrained("Qwen/Qwen2-VL-2B-Instruct", min_pixels=min_pixels, max_pixels=max_pixels)


toolbox_metadata = {
    "Object_Detector_Tool":{ 
            "tool_module_name": "object_detector", # a little modify
            "tool_class_name":"Object_Detector_Tool",
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
                    "command": 'execution = Object_Detector_Tool.execute(image="path/to/image.png", labels=["baseball", "basket"])', # little modify
                    "description": "Detect baseball and basket in an image, save the detected objects with default empty padding, and return their paths."
                },
                {
                    "command": 'execution = Object_Detector_Tool.execute(image="path/to/image.png", labels=["car", "person"], threshold=0.5, model_size="base", padding=15)',
                    "description": "Detect car and person in an image using the base model, save the detected objects with 15 pixels of empty padding, and return their paths."
                }
            ],
            "user_metadata":{
                "limitation": "The model may not always detect objects accurately, and its performance can vary depending on the input image and the associated labels. It typically struggles with detecting small objects, objects that are uncommon, or objects with limited or specific attributes. For improved accuracy or better detection in certain situations, consider using supplementary tools or image processing techniques to provide additional information for verification."
            }
    }
}

available_tools= ["Object Detector Tool"]


PROMPT_TEMPLATE= """
\n Write a Python program to answer the question related to images : {question}.
Enclose the generated code and comments in <command> </command> tags,
i.e. <command> generated python code </command>.
You can include your thoughts on the code and analysis about how to solve the problem as comments between code line.
You need to use the following available tools, which are very helpful for you.
\n Available Tools: {available_tools}
\n Tools Metadata: {toolbox_metadata}
\n In each tool module folder, there is a `python` script `tool.py` containing the class that implements the tool logic.
\n ## Rules:
\n1.The command MUST be valid Python code.
\n2.If listed available tools are insufficient to obtain the answer, you can use functions from Python's standard library as needed.
\n3.Use the exact parameter names as specified in the tool's input_types.
\n4.If you need, please directly use the PATHs of images: {image_paths}, which are related to Question
\n5.Always make sure to define variables and functions before using them to keep your Python code syntactically correct
\n6.Ensure that the code execution yields a result that directly answers the question.

\n ## Note:
\nYou must put your code and your thought comments within the tag <command> </command>.
Please assign the final answer to a variable named "final_result".
If needed, please add the following in the libheader: from <tool_module_name>.tool import <tool_class_name>
please remember to replace <tool_module_name> and <tool_class_name> with their actual names.
"""

##############################################################################################################################
# image_paths = [
#             "BLINK_Dataset/Jigsaw/val/images/val_Jigsaw_1_image_1.jpg",
#             "BLINK_Dataset/Jigsaw/val/images/val_Jigsaw_1_image_2.jpg",
#             "BLINK_Dataset/Jigsaw/val/images/val_Jigsaw_1_image_3.jpg"
#         ]
# dataset_prefix = "/home/stud/wxie/"
# image_paths = [os.path.join(dataset_prefix, image_path) for image_path in image_paths]
# images = [Image.open(path) for path in image_paths]
# # print(images)
# Question = "Which image is the missing part in the first image?"
######################################
relative_image_path = "examples/baseball.png"
image_path = os.path.join(root_dir,'tools','object_detector',relative_image_path)
image_path = [image_path]
print(image_path)
Question = "How many baseballs are there in the image"
images = [Image.open(path) for path in image_path]
######################################
message_content = [ {"type": "image"} for _ in image_path ] ###
message_content.append({
    "type": "text",
    "text": PROMPT_TEMPLATE.format(
        question=Question,
        image_paths=", ".join(image_path),   ###
        available_tools=available_tools,
        toolbox_metadata=toolbox_metadata
    )
})
messages = [
    {
        "role": "user",
        "content": message_content
    }
]
# print(message_content)
# Preparation for inference
text = processor.apply_chat_template(
    messages, tokenize=False, add_generation_prompt=True
)


inputs = processor(
    text=text,
    images=images, # images
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
print(completions)

# ############################################################################
# #################################DEBUG######################################
# completions_path = os.path.join(root_dir,"debug","completions_debug.txt")
# os.makedirs(os.path.dirname(completions_path), exist_ok=True)
# with open(completions_path, "w") as f:
#     for completion in completions:
#         f.write(f"{completion} \n")

############################################################################        
    
############################################################################
# def extract_code(completion):
#     match = re.search(r"<command>(.*?)</command>", completion , re.DOTALL)
#     if match:
#         extracted_code = match.group(1).strip()  
#         return extracted_code
#     else:
#         raise ValueError("no command tag found!!")

# # waiting to be extended
# api_methods = {
#     "object_detector": 
# """

# """
# }
# #####################
# generated_code = extract_code(completions[0])

# generated_code = """
# tool = Object_Detector_Tool()
# metadata = tool.get_metadata()
# # tool.set_custom_output_dir("detected_objects")


# # print(metadata)

# relative_image_path = "examples/baseball.png"
# image_path = os.path.join("/home/stud/wxie/Tools_Thinker","tools","object_detector", relative_image_path)

# # Execute the tool
# try:
#     execution = tool.execute(image=image_path, labels=["baseball"], padding=20)
#     print("Detected Objects:")
#     for obj in execution:
#         print(f"Detected {obj['label']} with confidence {obj['confidence score']}")
#         print(f"Bounding box: {obj['box']}")
#         print(f"Saved image (with padding): {obj['saved_image_path']}")
#         print()
# except ValueError as e: 
#     print(f"Execution failed: {e}")
    
# final_result = len(execution)

# print("Done!")
# """

#full_code = [api_methods["object_detector"] + "\n" + generated_code + "\n"+"print('<final_result>', final_result)"]

# print(full_code)
solutions = ["20"]

#Asyncio#
def code_exec_acc_reward(completions, solution, **kwargs):
    """
    running code snippets in completions and if result is correct return the rewards.
    If an error occurs during execution, return "0".
    Use asyncio to automatically create and manage event loops.
    """
    if isinstance(completions[0],str):
        contents = [completion for completion in completions]
    else:
        contents = [completion[0]["content"] for completion in completions]
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_dir_path = os.path.join(root_dir, "src/open_r1_multimodal/DEBUGlogs")
    #log_dir_path = os.path.join(root_dir, "src/open_r1_multimodal/Trainlogs")
    os.makedirs(log_dir_path, exist_ok=True)
    ### debug subprocess 
    def run_async_from_sync(coro):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # No loop exists
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        if loop.is_closed():
            # Previously closed loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        return loop.run_until_complete(coro)
    
    def extract_code(completion):
        match = re.search(r"<command>(.*?)</command>", completion , re.DOTALL)
        if match:
            extracted_code = match.group(1).strip()
            return extracted_code
        else:
            return None
#     api_methods = { # python environment in subprocess is isolated from mainprocess
#     "object_detector":  ""# must import one by one to keep more robust
# # """
# # import sys
# # import os
# # import time
# # import torch
# # from transformers import pipeline

# # from tools.base import BaseTool
# # from PIL import Image, ImageOps
# # import os
# # import sys
# # import warnings
# # """
# }
    async def run_all_codes(contents, solutions, log_dir_path, current_time):
        """
        Asynchronously run multiple code snippets.
        """
        sema = asyncio.Semaphore(8)  # max n ubprocess
        
        tasks = []
        for content, sol in zip(contents, solutions):
            async def limited_task(content=content, sol=sol):
                extracted_code = extract_code(content)  
                if extracted_code is None:
                    log_path = os.path.join(log_dir_path ,f"{current_time}-evaluation.log")
                    with open(log_path, "w") as f:
                        f.write(f"------------- {current_time} Extract Code Error -------------\n")
                        f.write(f"\nSolution: {solution}\n")
                    return 0.0

                async with sema:
                    code_to_run = (
                        #f"{api_methods['object_detector']}\n" # no need maybe
                        f"{extracted_code}\n"
                        "print('<final_result>', final_result)"
                        )
                    return await run_code_async(code_to_run, sol, log_dir_path, current_time, 120)
            tasks.append(limited_task())
        return await asyncio.gather(*tasks)
    
    async def run_code_async(code, solution, log_dir_path, current_time, exec_timeout: int=10) -> float:
        """
        Run a code snippet asynchronously and evaluate the result.
        """
        try:
            # proc = await asyncio.create_subprocess_exec(
            #     'python3', '-c', code,
            #     stdout=asyncio.subprocess.PIPE,
            #     stderr=asyncio.subprocess.PIPE,
            # )
            python_exec = sys.executable
            # print("Python Exec Path:", python_exec)
            proc = await asyncio.create_subprocess_exec(
                python_exec, '-c', code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=exec_timeout)
            if proc.returncode != 0:
                log_path = os.path.join(log_dir_path ,f"{current_time}-evaluation.log")
                with open(log_path, "w") as f:
                    f.write(f"------------- {current_time} Execution Error: {proc.returncode} -------------\n")
                    f.write(f"Error in code execution: \n{stderr.decode().strip()}\n")
                    f.write(f"\nCode: {code}\n\n")
                    f.write(f"\nSolution: {solution}\n")
                return 0.0
            output_raw = stdout.decode().strip()
        except Exception as e:
            log_path = os.path.join(log_dir_path ,f"{current_time}-evaluation.log")
            with open(log_path, "w") as f:
                f.write(f"------------- {current_time} Exception in creating subproess -------------\n")
                f.write(f"Exception: in creating subproess \n{str(e)}\n")
                f.write("Traceback:\n")
                f.write(traceback.format_exc())
                f.write(f"Timeout after {exec_timeout} seconds.\n")
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
            log_path = os.path.join(log_dir_path, f"{current_time}-evaluation.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "w") as f:
                f.write(f"------------- {current_time} Exception in extract final result-------------\n")
                f.write(f"Exception in extract final result: \n{str(e)}\n")
                f.write(f"Code: {code}\n\n")
                f.write(f"Solution: {solution}\n")
            return 0.0
            
        reward = 0.0
        # try to parse the output and solution to do symbolic verification
        try:
            answer = parse(output) # follow Visual Thinker accuracy
            sol_parsed = parse(solution)
            if float(verify(answer, sol_parsed)) > 0:
                reward = 1.0
        except Exception:
            pass

        # 
        if reward == 0.0:
            # get Ground Truth from solution
            ground_truth = solution
            student_answer = output
            if student_answer == ground_truth:
                reward = 1.0

        log_path = os.path.join(log_dir_path, f"{current_time}-evaluation.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write(f"------------- {current_time} Sucessful Execution; Reward: {reward} -------------\n")
            f.write(f"Code: {code}\n\n")
            f.write(f"Final Result: {output}\n\n")
            f.write(f"Solution: {solution}\n")
        return reward
    
    return run_async_from_sync(run_all_codes(contents=contents,solutions=solution, log_dir_path=log_dir_path, current_time=current_time))

results = code_exec_acc_reward(completions=completions,solution=solutions)
for idx, result in enumerate(results):
    print(f"code snippet {idx} result: {result}")