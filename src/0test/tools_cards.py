import sys
import os
import re
import time
import torch
import transformers
from transformers import pipeline
import torch.utils.data
from datasets import Dataset, IterableDataset
import shutil
import faulthandler
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor , as_completed
import signal
import runpy
from math_verify import parse, verify
from io import StringIO
import contextlib
import signal
from datetime import datetime
import asyncio
import subprocess
import traceback
from PIL import Image, ImageOps

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.join(os.path.dirname(os.path.dirname(current_dir)))

from object_detector import Object_Detector_Tool 

from transformers import Qwen2VLForConditionalGeneration,Qwen2_5_VLForConditionalGeneration, AutoTokenizer, AutoProcessor
from qwen_vl_utils import process_vision_info

# # loading model using Qwen2VL (from_pretrained)
# model = Qwen2VLForConditionalGeneration.from_pretrained(
#     "Qwen/Qwen2-VL-2B-Instruct", torch_dtype=torch.bfloat16, attn_implementation="flash_attention_2",device_map="cuda:0"
# )
# # Processor(from_pretrained)
# processor = AutoProcessor.from_pretrained("Qwen/Qwen2-VL-2B-Instruct")

# # The default range for the number of visual tokens per image in the model is 4-16384. You can set min_pixels and max_pixels according to your needs, such as a token count range of 256-1280, to balance speed and memory usage.
# # min_pixels = 256*28*28
# # max_pixels = 1280*28*28
# # processor = AutoProcessor.from_pretrained("Qwen/Qwen2-VL-2B-Instruct", min_pixels=min_pixels, max_pixels=max_pixels)


# toolbox_metadata = {
#     "Object_Detector_Tool":{ 
#             "tool_module_name": "object_detector", # a little modify
#             "tool_class_name":"Object_Detector_Tool",
#             "tool_description":"A tool that detects objects in an image using the Grounding DINO model and saves individual object images with empty padding.",
#             "tool_version":"1.0.0",
#             "input_types":{
#                 "image": "str - The path to the image file.",
#                 "labels": "list - A list of object labels to detect.",
#                 "threshold": "float - The confidence threshold for detection (default: 0.35).",
#                 "model_size": "str - The size of the model to use ('tiny' or 'base', default: 'tiny').",
#                 "padding": "int - The number of pixels to add as empty padding around detected objects (default: 20)."
#             },
#             "output_type":"list - A list of detected objects dictionaries with ('label';'confidence score';'box';'saved_image_path')keys and their corresponding values",
#             "demo_commands":[
#                 {
#                     "command": 'execution = Object_Detector_Tool.execute(image="path/to/image.png", labels=["baseball", "basket"])', # little modify
#                     "description": "Detect baseball and basket in an image, save the detected objects with default empty padding, and return their paths."
#                 },
#                 {
#                     "command": 'execution = Object_Detector_Tool.execute(image="path/to/image.png", labels=["car", "person"], threshold=0.5, model_size="base", padding=15)',
#                     "description": "Detect car and person in an image using the base model, save the detected objects with 15 pixels of empty padding, and return their paths."
#                 }
#             ],
#             "user_metadata":{
#                 "limitation": "The model may not always detect objects accurately, and its performance can vary depending on the input image and the associated labels. It typically struggles with detecting small objects, objects that are uncommon, or objects with limited or specific attributes. For improved accuracy or better detection in certain situations, consider using supplementary tools or image processing techniques to provide additional information for verification."
#             }
#     }
# }

# available_tools= ["Object Detector Tool"]


# PROMPT_TEMPLATE= """
# \n Write a Python program to answer the question related to images : {question}.
# Enclose the generated code and comments in <command> </command> tags,
# i.e. <command> generated python code </command>.
# You can include your thoughts on the code and analysis about how to solve the problem as comments between code line.
# You need to use the following available tools, which are very helpful for you.
# \n Available Tools: {available_tools}
# \n Tools Metadata: {toolbox_metadata}
# \n In each tool module folder, there is a `python` script `tool.py` containing the class that implements the tool logic.
# \n ## Rules:
# \n1.The command MUST be valid Python code.
# \n2.If listed available tools are insufficient to obtain the answer, you can use functions from Python's standard library as needed.
# \n3.Use the exact parameter names as specified in the tool's input_types.
# \n4.If you need, please directly use the PATHs of images: {image_paths}, which are related to Question
# \n5.Always make sure to define variables and functions before using them to keep your Python code syntactically correct
# \n6.Ensure that the code execution yields a result that directly answers the question.

# \n ## Note:
# \nYou must put your code and your thought comments within the tag <command> </command>.
# Please assign the final answer to a variable named "final_result".
# If needed, please add the following in the libheader: from <tool_module_name>.tool import <tool_class_name>
# please remember to replace <tool_module_name> and <tool_class_name> with their actual names.
# """

# ##############################################################################################################################
# # image_paths = [
# #             "BLINK_Dataset/Jigsaw/val/images/val_Jigsaw_1_image_1.jpg",
# #             "BLINK_Dataset/Jigsaw/val/images/val_Jigsaw_1_image_2.jpg",
# #             "BLINK_Dataset/Jigsaw/val/images/val_Jigsaw_1_image_3.jpg"
# #         ]
# # dataset_prefix = "/home/stud/wxie/"
# # image_paths = [os.path.join(dataset_prefix, image_path) for image_path in image_paths]
# # images = [Image.open(path) for path in image_paths]
# # # print(images)
# # Question = "Which image is the missing part in the first image?"
# ######################################
# relative_image_path = "examples/baseball.png"
# image_path = os.path.join(root_dir,'tools','object_detector',relative_image_path)
# image_path = [image_path]
# print(image_path)
# Question = "How many baseballs are there in the image"
# images = [Image.open(path) for path in image_path]
# ######################################
# message_content = [ {"type": "image"} for _ in image_path ] ###
# message_content.append({
#     "type": "text",
#     "text": PROMPT_TEMPLATE.format(
#         question=Question,
#         image_paths=", ".join(image_path),   ###
#         available_tools=available_tools,
#         toolbox_metadata=toolbox_metadata
#     )
# })
# messages = [
#     {
#         "role": "user",
#         "content": message_content
#     }
# ]
# # print(message_content)
# # Preparation for inference
# text = processor.apply_chat_template(
#     messages, tokenize=False, add_generation_prompt=True
# )


# inputs = processor(
#     text=text,
#     images=images, # images
#     padding=True,
#     return_tensors="pt",
#     add_special_tokens=False,
#     padding_side="left"
# )

# inputs = inputs.to("cuda")


# # Inference: Generation of the output
# generated_ids = model.generate(**inputs, max_new_tokens=1024)

# generated_ids_trimmed = [
#     out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
# ]
# completions = processor.batch_decode(
#     generated_ids_trimmed, skip_special_tokens=True
# )
# print(completions)

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

# # print(full_code)
# solutions = ["20"]

# #Asyncio#
# def code_exec_acc_reward(completions, solution, **kwargs):
#     """
#     running code snippets in completions and if result is correct return the rewards.
#     If an error occurs during execution, return "0".
#     Use asyncio to automatically create and manage event loops.
#     """
#     if isinstance(completions[0],str):
#         contents = [completion for completion in completions]
#     else:
#         contents = [completion[0]["content"] for completion in completions]
#     current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
#     log_dir_path = os.path.join(root_dir, "src/open_r1_multimodal/DEBUGlogs")
#     #log_dir_path = os.path.join(root_dir, "src/open_r1_multimodal/Trainlogs")
#     os.makedirs(log_dir_path, exist_ok=True)
#     ### debug subprocess 
#     def run_async_from_sync(coro):
#         try:
#             loop = asyncio.get_event_loop()
#         except RuntimeError:
#             # No loop exists
#             loop = asyncio.new_event_loop()
#             asyncio.set_event_loop(loop)
        
#         if loop.is_closed():
#             # Previously closed loop
#             loop = asyncio.new_event_loop()
#             asyncio.set_event_loop(loop)
            
#         return loop.run_until_complete(coro)
    
#     def extract_code(completion):
#         match = re.search(r"<command>(.*?)</command>", completion , re.DOTALL)
#         if match:
#             extracted_code = match.group(1).strip()
#             return extracted_code
#         else:
#             return None
# #     api_methods = { # python environment in subprocess is isolated from mainprocess
# #     "object_detector":  ""# must import one by one to keep more robust
# # # """
# # # import sys
# # # import os
# # # import time
# # # import torch
# # # from transformers import pipeline

# # # from tools.base import BaseTool
# # # from PIL import Image, ImageOps
# # # import os
# # # import sys
# # # import warnings
# # # """
# # }
#     async def run_all_codes(contents, solutions, log_dir_path, current_time):
#         """
#         Asynchronously run multiple code snippets.
#         """
#         sema = asyncio.Semaphore(8)  # max n ubprocess
        
#         tasks = []
#         for content, sol in zip(contents, solutions):
#             async def limited_task(content=content, sol=sol):
#                 extracted_code = extract_code(content)  
#                 if extracted_code is None:
#                     log_path = os.path.join(log_dir_path ,f"{current_time}-evaluation.log")
#                     with open(log_path, "w") as f:
#                         f.write(f"------------- {current_time} Extract Code Error -------------\n")
#                         f.write(f"\nSolution: {solution}\n")
#                     return 0.0

#                 async with sema:
#                     code_to_run = (
#                         #f"{api_methods['object_detector']}\n" # no need maybe
#                         f"{extracted_code}\n"
#                         "print('<final_result>', final_result)"
#                         )
#                     return await run_code_async(code_to_run, sol, log_dir_path, current_time, 120)
#             tasks.append(limited_task())
#         return await asyncio.gather(*tasks)
    
#     async def run_code_async(code, solution, log_dir_path, current_time, exec_timeout: int=10) -> float:
#         """
#         Run a code snippet asynchronously and evaluate the result.
#         """
#         try:
#             # proc = await asyncio.create_subprocess_exec(
#             #     'python3', '-c', code,
#             #     stdout=asyncio.subprocess.PIPE,
#             #     stderr=asyncio.subprocess.PIPE,
#             # )
#             python_exec = sys.executable
#             # print("Python Exec Path:", python_exec)
#             proc = await asyncio.create_subprocess_exec(
#                 python_exec, '-c', code,
#                 stdout=asyncio.subprocess.PIPE,
#                 stderr=asyncio.subprocess.PIPE,
#             )
#             stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=exec_timeout)
#             if proc.returncode != 0:
#                 log_path = os.path.join(log_dir_path ,f"{current_time}-evaluation.log")
#                 with open(log_path, "w") as f:
#                     f.write(f"------------- {current_time} Execution Error: {proc.returncode} -------------\n")
#                     f.write(f"Error in code execution: \n{stderr.decode().strip()}\n")
#                     f.write(f"\nCode: {code}\n\n")
#                     f.write(f"\nSolution: {solution}\n")
#                 return 0.0
#             output_raw = stdout.decode().strip()
#         except Exception as e:
#             log_path = os.path.join(log_dir_path ,f"{current_time}-evaluation.log")
#             with open(log_path, "w") as f:
#                 f.write(f"------------- {current_time} Exception in creating subproess -------------\n")
#                 f.write(f"Exception: in creating subproess \n{str(e)}\n")
#                 f.write("Traceback:\n")
#                 f.write(traceback.format_exc())
#                 f.write(f"Timeout after {exec_timeout} seconds.\n")
#                 f.write(f"Code: {code}\n\n")
#                 f.write(f"Solution: {solution}\n")
#             return 0.0
        
#         output = None
        
#         try:
#             for line in output_raw.splitlines():
#                 if line.startswith("<final_result>"):
#                     output = line[len("<final_result>"):].strip()
#                     break
#         except Exception as e:
#             log_path = os.path.join(log_dir_path, f"{current_time}-evaluation.log")
#             os.makedirs(os.path.dirname(log_path), exist_ok=True)
#             with open(log_path, "w") as f:
#                 f.write(f"------------- {current_time} Exception in extract final result-------------\n")
#                 f.write(f"Exception in extract final result: \n{str(e)}\n")
#                 f.write(f"Code: {code}\n\n")
#                 f.write(f"Solution: {solution}\n")
#             return 0.0
            
#         reward = 0.0
#         # try to parse the output and solution to do symbolic verification
#         try:
#             answer = parse(output) # follow Visual Thinker accuracy
#             sol_parsed = parse(solution)
#             if float(verify(answer, sol_parsed)) > 0:
#                 reward = 1.0
#         except Exception:
#             pass

#         # 
#         if reward == 0.0:
#             # get Ground Truth from solution
#             ground_truth = solution
#             student_answer = output
#             if student_answer == ground_truth:
#                 reward = 1.0

#         log_path = os.path.join(log_dir_path, f"{current_time}-evaluation.log")
#         os.makedirs(os.path.dirname(log_path), exist_ok=True)
#         with open(log_path, "a") as f:
#             f.write(f"------------- {current_time} Sucessful Execution; Reward: {reward} -------------\n")
#             f.write(f"Code: {code}\n\n")
#             f.write(f"Final Result: {output}\n\n")
#             f.write(f"Solution: {solution}\n")
#         return reward
    
#     return run_async_from_sync(run_all_codes(contents=contents,solutions=solution, log_dir_path=log_dir_path, current_time=current_time))
#################Preparation For Execution#######################
#Prepare Function for Code reward
def reliability_guard():
    faulthandler.disable()
    import builtins
    builtins.exit = None
    builtins.quit = None
    import os
    os.kill = None
    os.system = None
    os.remove = None
    os.rmdir = None
    import shutil
    shutil.rmtree = None
    import subprocess
    subprocess.Popen = None
    import sys
    sys.modules["ipdb"] = None

def unsafe_execute(code, timeout, result, log_path):
    def timeout_handler(signum, frame):
        raise TimeoutError("Execution timed out")
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(int(timeout))
    try: # if the code is bugfree
        reliability_guard() # follow human-eval evaluation script
        buffer = StringIO() # save all output when execution
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            # TODO # here add external tool module and can be better
            exec_globals = {
                "Object_Detector_Tool": Object_Detector_Tool,
                "final_result": None
            }
            exec(code, exec_globals)  # # python dynamic execution environment
        output_raw = buffer.getvalue() # seems to get all output/print in code execution
        output = exec_globals.get("final_result", None)
        
        debug_log_path = os.path.join(log_path, "debug_exec.log")
        with open(debug_log_path, "a") as df:
            df.write("\n" + "=" * 30 + " NEW SCCESSFUL EXECUTION " + "=" * 30 + "\n")
            df.write("[EXEC CODE]\n")
            df.write(code + "\n")
            df.write("[THE PRINT OUTPUT]\n")
            df.write(output_raw + "\n")
            df.write("[GENERATE FINAL_RESULT]\n")
            df.write(str(output) + "\n")
        
        reward = 0.0
        if output != None: # OUTPUT exist, then reward is 1.0
            reward = 1.0
        else:
            with open(debug_log_path, "a") as df:
                df.write("\n[None RESULT]\n\n")
        result.append((reward, output))
    except Exception as e: # if the code problematic
        debug_log_path = os.path.join(log_path, "debug_exec.log")
        with open(debug_log_path, "a") as df:
            df.write("\n[EXECUTION EXCEPTION]\n")
            df.write(str(e) + "\n")
            df.write(f"code:{code}\n")
        result.append((0.0, None))
    finally:
        signal.alarm(0)
        
def check_correctness(task: dict, log_path, current_time) -> float:
    start_time = time.perf_counter()  # timer start
    evaluation_log_path = os.path.join(log_path, "evaluation.log")  # in evaluation includes all cased in reward computation
                                                    # Code extraction,Code Bug and Successfual Execution: Correct(Wrong) result.
    if task["code"] == None:  # 
        with open(evaluation_log_path, "a") as f:
            
            f.write(f"------------- {current_time} Code Extraction Failed -------------\n")
            f.write(f"Reward: 0.0\n")
            f.write(f"QAid: {task['QAid']}\n")
            f.write(f"Code: [EMPTY]\n\n")
        result = (0.0, None)  # code reward is 0.0
    else:
        manager = multiprocessing.Manager()
        result = manager.list()
        ########################################################################################
        p = multiprocessing.Process(target=unsafe_execute, args=(task["code"], 60, result, log_path)) 
        # here unsafe execute part could be replaced with communication between Executor Server and Reward function(Evaluator Client)
        ###########################################################################################
        p.start()
        p.join(61)
        if p.is_alive():
            p.kill()
        result = result[0] if result else (0.0, None)
        end_time = time.perf_counter()  # timer stop
        elapsed = end_time - start_time
        with open(evaluation_log_path, "a") as f:
            f.write(f"------------- {current_time} Execution reward: {result[0]} -------------\n")
            f.write(f"[Reward computation time: {elapsed:.4f} seconds]\n\n")
            f.write(f"QAid: {task['QAid']}\n")
            f.write(f"Code: {task['code']}\n\n")
    return result

async def run_all_checks_async(tasks, log_root_dir, current_time):
    loop = asyncio.get_event_loop()
    rewards = []
    with ProcessPoolExecutor(max_workers=4) as pool:  # max num Processes 
        futures = [
            loop.run_in_executor(pool, check_correctness, task, log_root_dir, current_time)
            for task in tasks
        ]
        rewards = await asyncio.gather(*futures) # keep same sequence as tasks(completions code)
    reward_list = [r for r, _ in rewards] 
    result_list = [res for _, res in rewards]
    return (reward_list, result_list)
##########################################################################
##########EXECUTION REWARD#############################
def execution_reward(completions, QAid,**kwargs):
    # based on completions type to constuct
    if isinstance(completions[0], str):
        contents = [completion for completion in completions]
    else:
        contents = [completion[0]["content"] for completion in completions]

    def extract_code(completion):
        match = re.search(r"<command>(.*?)</command>", completion, re.DOTALL)
        if match:
            return match.group(1).strip()
        else:
            raise ValueError("No Command Tag Found!!")
    
    tasks = []
    for content, id in zip(contents, QAid):
        try:
            code = extract_code(content)
        except Exception as e:
            code = None
        tasks.append({
            "code": code,
            "QAid": id
        })
    
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_root_dir = os.path.join(f"{root_dir}/A+M_SPLIT_LOGS/Execution", f"{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
    
    reward_result = asyncio.run(run_all_checks_async(tasks, log_root_dir, current_time))
    return reward_result

completions = ["""
<command>
def count_yellow_jackets(image_path, yellow_jackets):
    # Load the image using the objectdetector tool
    detection_tool = object_detector.Object_Detector_Tool()
    
    # Execute the detection tool with the given parameters
    execution = detection_tool.execute(image_path, ["yellow_jacket"], threshold=0.35, model_size="tiny", padding=20)
    
    # Get the bounding boxes for the detected yellow jackets
    yellow_jackets_with_boxes = []
    for detection in execution[0]:
        label = detection['label']
        confidence_score = detection['confidence score']
        box = tuple(detection['box'])
        
        # Add the detected yellow jacket to the result list
        yellow_jackets_with_boxes.append({'label': label, 'confidence score': confidence_score, 'box': box, 'saved_image_path': None})
    
    # Get the total number of yellow jackets detected
    total_yellow_jackets = 0
    for jacket in yellow_jackets_with_boxes:
        if jacket['label'] == 'yellow_jacket':
            total_yellow_jackets += 1
    
    return total_yellow_jackets

# Example usage
if __name__ == "__main__":
    # Remove the path arguments and execute the function
    count_result = count_yellow_jackets(image_path="/home/stud/wxie/BLINK_Dataset/Counting/val/images/val_Counting_103_image_1.jpg", yellow_jackets=None)
    final_result = count_result['yellow_jacket']
    print("Hello from exec!")
    print(f"The number of people wearing a yellow jacket is: {final_result}")
</command>
"""]
QAid = [20]

rewards, results = execution_reward(completions=completions, QAid=QAid)
for idx, (reward, output) in enumerate(zip(rewards, results)):
    print(f"code snippet {idx} result: {reward}, {output}")
