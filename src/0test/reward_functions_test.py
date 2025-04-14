import os
import sys
import re
import asyncio
import faulthandler
import multiprocessing
from io import StringIO
import contextlib
from concurrent.futures import ThreadPoolExecutor,ProcessPoolExecutor, as_completed
from datetime import datetime
import signal
from math_verify import parse, verify

from object_detector.tool import Object_Detector_Tool

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

def unsafe_execute(code: str, solution: str, timeout: float, result, log_path):
    def timeout_handler(signum, frame):
        raise TimeoutError("Execution timed out")
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(int(timeout))
    try:
        reliability_guard()
        buffer = StringIO()
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
            df.write("\n" + "=" * 30 + " NEW EXECUTION " + "=" * 30 + "\n")
            df.write("[EXEC CODE]\n")
            df.write(code + "\n")
            df.write("[THE PRINT OUTPUT]\n")
            df.write(output_raw + "\n")
            df.write("[GENERATE FINAL_RESULT]\n")
            df.write(str(output) + "\n")
        
        reward = 0.0
        try:
            answer = parse(output)
            sol_parsed = parse(solution)
            if float(verify(answer, sol_parsed)) > 0:
                reward = 1.0
        except Exception:
            with open(debug_log_path, "a") as df:
                df.write("[\nPARSE/VERIFY FAILED]\n\n")
        if output == solution:
            with open(debug_log_path, "a") as df:
                df.write("[\nCORRECT RESULT]\n\n")
            reward = 1.0
        else:
            with open(debug_log_path, "a") as df:
                df.write("[\nWRONG RESULT]\n\n")
            reward = 0.0
        
        result.append((reward, output))
    except Exception as e:
        debug_log_path = os.path.join(log_path, "debug_exec.log")
        with open(debug_log_path, "a") as df:
            df.write("[EXECUTION EXCEPTION]\n")
            df.write(str(e) + "\n")
            df.write(f"code:{code}")
        result.append((0.0, str(e)))
    finally:
        signal.alarm(0)

def check_correctness(task: dict, log_path, current_time) -> float:
    manager = multiprocessing.Manager()
    result = manager.list()
    p = multiprocessing.Process(target=unsafe_execute, args=(task["code"], task["solution"], 60, result, log_path))
    p.start()
    p.join(61)
    if p.is_alive():
        p.kill()
    reward, output = result[0] if result else (0.0, "timeout")
    evaluation_log_path = os.path.join(log_path, "evaluation.log")
    with open(evaluation_log_path, "a") as f:
        f.write(f"------------- {current_time} Accuracy reward: {reward} -------------\n")
        f.write(f"Final Result: {output}\n\n")
        f.write(f"Solution: {task['solution']}\n")
        f.write(f"Code: {task['code']}\n\n")
    return reward

async def run_all_checks_async(tasks, log_root_dir, current_time):
    loop = asyncio.get_event_loop()
    rewards = []
    with ProcessPoolExecutor(max_workers=4) as pool: # TODO Make workers' number more elegant
        futures = [
            loop.run_in_executor(pool, check_correctness, task, log_root_dir, current_time)
            for task in tasks
        ]
        for future in asyncio.as_completed(futures):
            result = await future
            rewards.append(result)
    return rewards

def code_exec_acc_reward(completions, solution, **kwargs):
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
            raise ValueError("No command tag found!!")
    
    tasks = []
    for content, sol in zip(contents, solution):
        try:
            code = extract_code(content)
        except Exception as e:
            code = ""
        tasks.append({
            "code": code,
            "solution": sol
        })
    
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_root_dir = os.path.join(f"{root_dir}/src/open_r1_multimodal/src/open_r1", f"{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
    
    rewards = asyncio.run(run_all_checks_async(tasks, log_root_dir, current_time))
    return rewards

completions = [
"""<command>
import object_detector
import image
import letter_detector

# Convert image to grayscale for text detection
pixel_depth = object_detector.pixel_level_depth_estimator(input_type='image', mode='image')
image_result = image.execute(image_path=filename, save_image=True)

# Load the detected text from the image
detected_text = image_result['depth_image_result']['text_output']

# Detect letters in the detected text
letter_results = letter_detector.execute(image='depth_image')

# Find the first letter in the detected text
first_char = letter_results[0][0][3]

# Extract the bounding box coordinates and check if it matches any letters
bbox, letter, score = letter_results[0][1]

# Print the final result
if bbox == first_char:
  final_result = "1"
else:
  final_result = "0"

print(final_result)  # Output: 1 </command>"""
]
solutions = ["cat", "fish"]

def format_reward(completions, **kwargs):
    """Reward function that checks if the completion has a specific format."""
    pattern = r"(?s)<command>(?!\s*\bfinal_result\b).*?\bfinal_result\b\s*=.*?</command>"  # TODO - Done
    if isinstance(completions[0],str):
        completion_contents = [completion for completion in completions]
    else:
        completion_contents = [completion[0]["content"] for completion in completions]
    matches = [re.fullmatch(pattern, content, re.DOTALL) for content in completion_contents]
    return [1.0 if match else 0.0 for match in matches]

rewards = format_reward(completions)
print(rewards)  








#################################################################
