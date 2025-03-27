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
sys.path.insert(0, root_dir)

from tools.object_detector.tool import Object_Detector_Tool
def code_exec_acc_reward(completions, solution, **kwargs):
    if isinstance(completions[0], str):
        contents = [completion for completion in completions]
    else:
        contents = [completion[0]["content"] for completion in completions]
        
    def extract_code(completion):
        match = re.search(r"<command>(.*?)</command>", completion , re.DOTALL)
        if match:
            return match.group(1).strip()
        else:
            raise ValueError("No command tag found!!")
    tasks = []
    for idx, (content, sol) in enumerate(zip(contents, solution)):
        try:
            code = extract_code(content)
        except Exception as e:
            code = ""
        tasks.append(dict(
            code=code,
            solution=sol
        ))
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_root_dir  = os.path.join(f"{root_dir}/src/open_r1_multimodal/src/open_r1", f"{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
 ##########################################################   
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
        import signal
        from io import StringIO
        import contextlib
        
        def timeout_handler(signum, frame):
            raise TimeoutError("Execution timed out")
        
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(int(timeout))

        try:
            reliability_guard()

            buffer = StringIO()
            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                
                # here add external tool module
                exec_globals = { 
                    "Object_Detector_Tool": Object_Detector_Tool,  
                    "final_result": None
                }
                
                exec(code, exec_globals)  # python dynamic execution environment
            output_raw = buffer.getvalue()  # seems all output/print in code execution
            output = exec_globals.get("final_result", None)
            #####################################
            #record immediate variables and outputs
            #####################################
            
            debug_log_path = os.path.join(log_path, "debug_exec.log")
            with open(debug_log_path, "a") as df:
                df.write("\n" + "="*30 + " NEW EXECUTION " + "="*30 + "\n")
                df.write("[EXEC CODE]\n")
                df.write(code + "\n")
                df.write("[THE PRINT OUTPUT]\n")
                df.write(output_raw + "\n")
                df.write("[GENERATE FINAL_RESULT]\n")
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
                    df.write("[PARSE/VERIFY FAILED]\n")
                    pass        
            if output == solution:
                with open(debug_log_path, "a") as df:
                    df.write("[CORRECT RESULT]\n\n")          
                reward = 1.0
            else:
                with open(debug_log_path, "a") as df:
                    df.write("[WRONG RESULT]\n\n")
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

    def check_correctness(task: dict, log_path) -> float:
        manager = multiprocessing.Manager()
        result = manager.list()
        p = multiprocessing.Process(target=unsafe_execute, args=(task["code"], task["solution"], 60, result, log_path))
        p.start()
        p.join(61)
        if p.is_alive():
            p.kill()

        reward, output = result[0] if result else (0.0, "timeout")

        evaluation_log_path = os.path.join(log_path, f"evaluation.log")
        with open(evaluation_log_path, "a") as f:
            f.write(f"------------- {current_time} Accuracy reward: {reward} -------------\n")
            f.write(f"Final Result: {output}\n\n")
            f.write(f"Solution: {task['solution']}\n")
            f.write(f"Code: {task['code']}\n\n")
        return reward
    
    rewards = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(check_correctness, task, log_root_dir) for task in tasks]
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


##################################################################
##################################################################
##################################################################
##################################################################
##################################################################
#Asyncio#
def code_exec_acc_reward(completions, solution, **kwargs):
    """
    running code snippets in completions and if result is correct return the rewards.
    If an error occurs during execution, return "0".
    Use asyncio to automatically create and manage event loops.
    """
    start_time = time.perf_counter()
    if isinstance(completions[0],str):
        contents = [completion for completion in completions]
    else:
        contents = [completion[0]["content"] for completion in completions]
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_dir_path = os.path.join(root_dir, "src/open_r1_multimodal/A+DEBUGlogs")
    #log_dir_path = os.path.join(root_dir, "src/open_r1_multimodal/Trainlogs")
    os.makedirs(log_dir_path, exist_ok=True)
    ### debug subprocess 
    def run_async_from_sync(coro):
        
        global global_loop
        if global_loop.is_closed():
            global_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(global_loop)
        return global_loop.run_until_complete(coro)
    
    def extract_code(completion):
        match = re.search(r"<command>(.*?)</command>", completion , re.DOTALL)
        if match:
            extracted_code = match.group(1).strip()
            return extracted_code
        else:
            return None
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
                    end_time = time.perf_counter()  # Timer Stop
                    elapsed = end_time - start_time
                    log_path = os.path.join(log_dir_path ,f"{current_time}-evaluation.log")
                    with open(log_path, "a") as f:
                        f.write(f"------------- {current_time} Extract Code Error -------------\n")
                        f.write(f"[Reward computation time(for one completion): {elapsed:.4f} seconds]\n\n")
                        f.write(f"\nSolution: {solution}\n")
                    return 0.0

                async with sema:
                    code_to_run = (
                        f"{extracted_code}\n"
                        "print('<final_result>', final_result)"
                        )
                    return await run_code_async(code_to_run, sol, log_dir_path, current_time, 30) ## would be better
            tasks.append(limited_task())
        return await asyncio.gather(*tasks)
    
    async def run_code_async(code, solution, log_dir_path, current_time, exec_timeout: int=10) -> float:
        """
        Run a code snippet asynchronously and evaluate the result.
        """
        try:
            python_exec = sys.executable
            # print("Python Exec Path:", python_exec)
            proc = await asyncio.create_subprocess_exec(
                python_exec, '-c', code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=exec_timeout)
            if proc.returncode != 0:
                end_time = time.perf_counter()  # Timer Stop
                elapsed = end_time - start_time
                log_path = os.path.join(log_dir_path ,f"{current_time}-evaluation.log")
                with open(log_path, "a") as f:
                    f.write(f"------------- {current_time} Execution Error: {proc.returncode} -------------\n")
                    f.write(f"Error in code execution: \n{stderr.decode().strip()}\n")
                    f.write(f"\nCode: {code}\n\n")
                    f.write(f"[Reward computation time(for one completion): {elapsed:.4f} seconds]\n\n")
                    f.write(f"\nSolution: {solution}\n")
                return 0.0
            output_raw = stdout.decode().strip()
        except Exception as e:
            end_time = time.perf_counter()  # Timer Stop
            elapsed = end_time - start_time
            log_path = os.path.join(log_dir_path ,f"{current_time}-evaluation.log")
            with open(log_path, "a") as f:
                f.write(f"------------- {current_time} Exception in creating subproess -------------\n")
                f.write(f"Exception: in creating subproess \n{str(e)}\n")
                f.write("Traceback:\n")
                f.write(traceback.format_exc())
                f.write(f"Timeout after {exec_timeout} seconds.\n")
                f.write(f"Code: {code}\n\n")
                f.write(f"[Reward computation time(for one completion): {elapsed:.4f} seconds]\n\n")
                f.write(f"Solution: {solution}\n")
            return 0.0
        
        output = None
        
        try:
            for line in output_raw.splitlines():
                if line.startswith("<final_result>"):
                    output = line[len("<final_result>"):].strip()
                    break
        except Exception as e:
            end_time = time.perf_counter()  # Timer Stop
            elapsed = end_time - start_time
            log_path = os.path.join(log_dir_path, f"{current_time}-evaluation.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a") as f:
                f.write(f"------------- {current_time} Exception in extract final result-------------\n")
                f.write(f"Exception in extract final result: \n{str(e)}\n")
                f.write(f"Code: {code}\n\n")
                f.write(f"[Reward computation time(for one completion): {elapsed:.4f} seconds]\n\n")
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
                
        end_time = time.perf_counter()  # Timer Stop
        elapsed = end_time - start_time
        log_path = os.path.join(log_dir_path, f"{current_time}-evaluation.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write(f"------------- {current_time} Sucessful Execution; Reward: {reward} -------------\n")
            f.write("Traceback:\n")
            f.write(traceback.format_exc())
            f.write(f"Code: {code}\n\n")
            f.write(f"Final Result: {output}\n\n")
            f.write(f"[Reward computation time(for one completion): {elapsed:.4f} seconds]\n\n")
            f.write(f"Solution: {solution}\n")
        return reward

    return run_async_from_sync(run_all_codes(contents=contents,solutions=solution, log_dir_path=log_dir_path, current_time=current_time))



#################################################################
####MultiProcessing + Asyncio##########
###########################################################
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

def unsafe_execute(code, solution, timeout, result, log_path):
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
            df.write("\n" + "=" * 30 + " NEW EXECUTION " + "=" * 30 + "\n")
            df.write("[EXEC CODE]\n")
            df.write(code + "\n")
            df.write("[THE PRINT OUTPUT]\n")
            df.write(output_raw + "\n")
            df.write("[GENERATE FINAL_RESULT]\n")
            df.write(str(output) + "\n")
        
        reward = 0.0
        if output != None: # otherwise `parse error` occur
            try:
                answer = parse(output)
                sol_parsed = parse(solution)
                if float(verify(answer, sol_parsed)) > 0:
                    reward = 1.0
            except Exception:
                with open(debug_log_path, "a") as df:
                    df.write("\n[PARSE/VERIFY FAILED]\n\n")
            if output == solution:
                with open(debug_log_path, "a") as df:
                    df.write("\n[CORRECT RESULT]\n\n")
                reward = 1.0
            else:
                with open(debug_log_path, "a") as df:
                    df.write("\n[WRONG RESULT]\n\n")
                reward = 0.0
        else:
                with open(debug_log_path, "a") as df:
                    df.write("\n[None RESULT]\n\n")
                    reward = 0.0
        result.append((reward, output))
    except Exception as e: # if the code problematic
        debug_log_path = os.path.join(log_path, "debug_exec.log")
        with open(debug_log_path, "a") as df:
            df.write("\n[EXECUTION EXCEPTION]\n")
            df.write(str(e) + "\n")
            df.write(f"code:{code}\n")
        result.append((0.0, str(e)))
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
            f.write(f"Solution: {task['solution']}\n")
            f.write(f"Code: [EMPTY]\n\n")
        result = (0.0,"Extraction Failed")  # code reward is 0.0 
        reward, output = result
    else:
        manager = multiprocessing.Manager()
        result = manager.list()
        p = multiprocessing.Process(target=unsafe_execute, args=(task["code"], task["solution"], 60, result, log_path))
        p.start()
        p.join(61)
        if p.is_alive():
            p.kill()
        reward, output = result[0] if result else (0.0, "timeout")
        end_time = time.perf_counter()  # timer stop
        elapsed = end_time - start_time
        with open(evaluation_log_path, "a") as f:
            f.write(f"------------- {current_time} Accuracy reward: {reward} -------------\n")
            f.write(f"Final Result: {output}\n\n")
            f.write(f"[Reward computation time: {elapsed:.4f} seconds]\n\n")
            f.write(f"Solution: {task['solution']}\n")
            f.write(f"Code: {task['code']}\n\n")
    return reward

async def run_all_checks_async(tasks, log_root_dir, current_time):
    loop = asyncio.get_event_loop()
    rewards = []
    with ProcessPoolExecutor(max_workers=4) as pool:  # max num Processes 
        futures = [
            loop.run_in_executor(pool, check_correctness, task, log_root_dir, current_time)
            for task in tasks
        ]
        for future in asyncio.as_completed(futures):
            result = await future
            rewards.append(result)
    return rewards
####################################################################
##################CODE ACCURACY and EXECUTION REWARD################
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
            raise ValueError("No Command Tag Found!!")
    
    tasks = []
    for content, sol in zip(contents, solution):
        try:
            code = extract_code(content)
        except Exception as e:
            code = None
        tasks.append({
            "code": code,
            "solution": sol
        })
    
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_root_dir = os.path.join(f"{root_dir}/src/open_r1_multimodal/DEBUGlogs/A+MLOGS", f"{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
    
    rewards = asyncio.run(run_all_checks_async(tasks, log_root_dir, current_time))
    return rewards

#############################################################################################3
#########################Split into 2 functions##############################################
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
            df.write("\n" + "=" * 30 + " NEW EXECUTION " + "=" * 30 + "\n")
            df.write("[EXEC CODE]\n")
            df.write(code + "\n")
            df.write("[THE PRINT OUTPUT]\n")
            df.write(output_raw + "\n")
            df.write("[GENERATE FINAL_RESULT]\n")
            df.write(str(output) + "\n")
        
        reward = 0.0
        if output != None: # otherwise `parse error` occur
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
            f.write(f"Solution: {task['solution']}\n")
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
            f.write(f"------------- {current_time} Execution reward: {reward} -------------\n")
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
    reward_list = [res for _, res in rewards]
    return (reward_list, reward_list)
##########################################################################
##########EXECUTION REWARD#############################
def execution_reward(completions,QAid,**kwargs):
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
    log_root_dir = os.path.join(f"{root_dir}/A+MLOGS/Execution", f"{current_time}-logs")
    os.makedirs(log_root_dir, exist_ok=True)
    
    reward_result = asyncio.run(run_all_checks_async(tasks, log_root_dir, current_time))
    return reward_result
execution_reward.reward_type = "execution"
##############################2. ANSWER_CORRECTNESS_REWARD######################
def accuracy_reward(exec_reward_list, exec_result_list, solution, QAid, **kwargs):
    """
    """
    current_time = datetime.now().strftime("%d-%H-%M-%S-%f")
    log_root_dir = os.path.join(f"{root_dir}/A+MLOGS/Accuracy", f"{current_time}-logs")
    acc_log_path = os.path.join(log_root_dir, "accuracy.log")
    os.makedirs(log_root_dir, exist_ok=True)
    rewards = []
    for exec_r, result, sol, id in zip(exec_reward_list, exec_result_list, solution, QAid):
        if exec_r == 0:
            with open(acc_log_path, "a") as f:
                f.write(f"\n[QAid]{id}\n\n")
                f.write("\n[EXECUTION EXCEPTION]\n\n")
            rewards.append(0.0)
        else:
            try:
                # try to verify symbolic calculation
                parsed_result = parse(result)
                parsed_solution = parse(sol)
                if float(verify(parsed_result, parsed_solution)) > 0:
                    rewards.append(1.0)
                    with open(acc_log_path, "a") as f:
                        f.write(f"\n[QAid]{id}\n\n")
                        f.write("\n[Verification Correct Result]\n\n")
                else:
                    rewards.append(0.0)
                    with open(acc_log_path, "a") as f:
                        f.write(f"\n[QAid]{id}\n\n")
                        f.write("\n[Verification Wrong Result]\n\n")
            except Exception:
                pass
            
            if result == sol:
                rewards.append(1.0)
                with open(acc_log_path, "a") as f:
                    f.write(f"\n[QAid]{id}\n\n")
                    f.write("\n[Correct Result]\n\n")
            else:
                rewards.append(0.0)
                with open(acc_log_path, "a") as f:
                    f.write(f"\n[QAid]{id}\n\n")
                    f.write("\n[Wrong Result]\n\n")
    return rewards
accuracy_reward.reward_type = "accuracy"