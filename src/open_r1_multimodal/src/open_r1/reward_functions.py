import os
import sys
import re
import shutil
import faulthandler
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from math_verify import parse, verify
root_dir = "/home/stud/wxie/Tools_Thinker/"

def code_exec_acc_reward(completions, solution, **kwargs):
    if isinstance(completions[0], str):
        contents = [completion for completion in completions]
    else:
        contents = [completion[0]["content"] for completion in completions]

    tasks = []
    for idx, (content, sol) in enumerate(zip(contents, solution)):
        try:
            code = extract_code(content)
        except Exception as e:
            code = ""
        tasks.append(dict(
            task_id=f"task_{idx}",
            code=code,
            solution=sol
        ))
    def extract_code(completion):
        match = re.search(r"<command>(.*?)</command>", completion , re.DOTALL)
        if match:
            return match.group(1).strip()
        else:
            raise ValueError("No command tag found!!")

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
    def unsafe_execute(code: str, solution: str, timeout: float, result):
        
        import signal
        from io import StringIO
        import contextlib
        
        def timeout_handler(signum, frame):
            raise TimeoutError("Execution timed out")
        
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(int(timeout))

        try:
            reliability_guard()
            full_code = f"""
import sys
import os
import torch
from transformers import pipeline
sys.path.insert(0, "{root_dir}")
from tools.base import BaseTool
from PIL import Image, ImageOps
from tools.object_detector.tool import Object_Detector_Tool

{code}

print('<final_result>', final_result)
"""

            buffer = StringIO()
            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                exec_globals = {}
                exec(full_code, exec_globals)

            output_raw = buffer.getvalue()  # seems all output/print in code execution
            output = None
            
            log_dir = os.path.join(f"{root_dir}/src/open_r1_multimodal/src/open_r1", "logs")
            os.makedirs(log_dir, exist_ok=True)
            debug_log_path = os.path.join(log_dir, "debug_exec.log")
            with open(debug_log_path, "a") as df:
                df.write("\n" + "="*30 + " NEW EXECUTION " + "="*30 + "\n")
                df.write("[EXEC CODE]\n")
                df.write(full_code + "\n")
                df.write("[RAW OUTPUT]\n")
                df.write(output_raw + "\n")
                
            for line in output_raw.splitlines():
                if line.startswith("<final_result>"):
                    output = line[len("<final_result>"):].strip()
                    break
                
            with open(debug_log_path, "a") as df:
                df.write("[PARSED FINAL_RESULT]\n")
                df.write(str(output) + "\n")
            ##################
            #extract final result after code execution#
            ##################
            reward = 0.0
            try:
                answer = parse(output)
                sol_parsed = parse(solution)
                if float(verify(answer, sol_parsed)) > 0:
                    reward = 1.0
            except Exception:
                with open(debug_log_path, "a") as df:
                    df.write("[PARSE/VERIFY EXCEPTION]\n")
                    df.write(str(e) + "\n")
                    
                if output == solution:
                    reward = 1.0
            result.append((reward, output))
        except Exception as e:
            log_dir = os.path.join(f"{root_dir}/src/open_r1_multimodal/src/open_r1", "logs")
            os.makedirs(log_dir, exist_ok=True)
            debug_log_path = os.path.join(log_dir, "debug_exec.log")
            with open(debug_log_path, "a") as df:
                df.write("[EXECUTION EXCEPTION]\n")
                df.write(str(e) + "\n")
            result.append((0.0, str(e)))
        finally:
            signal.alarm(0)    

    def check_correctness(task: dict) -> float:
        manager = multiprocessing.Manager()
        result = manager.list()
        p = multiprocessing.Process(target=unsafe_execute, args=(task["code"], task["solution"], 20, result))
        p.start()
        p.join(21)
        if p.is_alive():
            p.kill()

        reward, output = result[0] if result else (0.0, "timeout")

        current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
        log_path = os.path.join(f"{root_dir}/src/open_r1_multimodal/src/open_r1", "logs", f"evaluation.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write(f"------------- {current_time} Accuracy reward: {reward} -------------\n")
            f.write(f"Final Result: {output}\n\n")
            f.write(f"Solution: {task['solution']}\n")
            f.write(f"Code: {task['code']}\n\n")
        return reward
    
    
    rewards = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(check_correctness, task) for task in tasks]
        for f in as_completed(futures):
            rewards.append(f.result())
    return rewards

completions = [
    "<command>final_result = 'cat'</command>",
    "<command>final_result = 'fish'</command>"
]
solutions = ["cat", "fish"]
rewards = code_exec_acc_reward(completions, solutions)
print(rewards)  