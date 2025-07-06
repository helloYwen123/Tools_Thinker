import torch
import json
import requests
from oumi.core.configs import InferenceConfig, EvaluationConfig
from oumi.core.types import Conversation, Message, Role
from oumi.inference import VLLMInferenceEngine
from oumi.builders import build_processor, build_tokenizer
from oumi.core.configs import ModelParams
from oumi.datasets import VLJsonlinesDataset
from oumi.core.registry import register_evaluation_function
from oumi.core.evaluation import Evaluator
from oumi.core.evaluation import Evaluator
import re
from tqdm import tqdm 
#--- set random seed for reproduction ---
import transformers,random
import numpy as np
seed = 42
transformers.set_seed(seed)
random.seed(seed)
np.random.seed(seed)
torch.manual_seed(seed)
torch.cuda.manual_seed(seed)
print(f"Random Seed setting finished.")
#---------------------------------
from datetime import datetime

model_name = "Qwen/Qwen2.5-VL-7B-Instruct"
tokenizer = build_tokenizer(ModelParams(model_name=model_name))
processor = build_processor(model_name, tokenizer, trust_remote_code=True)

# Load the dataset
evaluation_dataset = VLJsonlinesDataset(dataset_path="/workspace/ywen_ws/mix_datasets/train.jsonl",
                             tokenizer=tokenizer,
                             processor=processor)

# Iterate through the dataset and print conversations
for i in range(1):
   print(evaluation_dataset.conversation(i))

# For Debug
EXECUTION_TIMEOUT_SECONDS = 120
MARAJO_SANDBOX_URL = "http://10.153.51.195:8080/api/sandbox/execute"
def server_api(payload):
    try:
        resp = requests.post(MARAJO_SANDBOX_URL, json=payload, timeout=EXECUTION_TIMEOUT_SECONDS)
        resp.raise_for_status()
        result_data = resp.json()
        status = result_data.get("status")
        if status == "success":
            if result_data.get("result") is not None:
                    exec_result = result_data.get("result") # here
                    return exec_result,0
            stdout = result_data.get("stdout", "").strip()
            m = re.search(r"final_result:?[ \t]*(.+)", stdout)
            if m:
                exec_result = m.group(1).strip()
                
                return exec_result,1
            else:
                exec_result = "Error: 'final_result' variable not found in output."
                return exec_result,2
        else:
            exec_result = result_data.get("error_message") or result_data.get("stderr") or result_data.get("stdout", "")
            return exec_result,3
    except Exception as ex:
        print(f"Error during request or processing: {ex}")
        exec_result = "Error during request or processing"
        return exec_result,4
    

@register_evaluation_function("Counting_tools_evaluation")
def Counting_tools_evaluation(inference_engine, dataset):
    """Custom evaluation function registered as `Counting_tools_evaluation`."""
    # Run inference to generate the model responses.
    conversations = inference_engine.infer(dataset.conversations())

    success_exe = 0
    acc_exe = 0
    logs = []
    
    pattern = r"\s*<think>.*?</think>\s*<code>.*?</code>\s*"
    for conversation in tqdm(conversations, desc="Evaluating", unit="conv"):
        correctness = False
        success = False
        # Extract the assistant's (LLM's) response from the conversation.
        response: str = conversation.last_message().content
        
        if re.fullmatch(pattern, response.strip(), re.DOTALL):
            match = re.search(r"<code>(.*?)</code>", response, flags=re.DOTALL)
            if match:
                code = match.group(1).strip()
                payload = {
                    "code": code,
                    "timeout": EXECUTION_TIMEOUT_SECONDS,
                    "q_aid": None
                    }
                exec_result, case = server_api(payload)
            else:
                exec_result = "Code Extraction Error"
                case = 5
        else:
            exec_result = "Format Error"
            case = 5
        
        if not isinstance(exec_result, str):
            exec_result= str(exec_result)
        
        if (
            (case not in [3, 4, 5])       
            # or (case == 3 and "KeyError:" in exec_result)
            ):
            success_exe += 1
            success = True
        if exec_result.lower() == conversation.metadata["ground_truth"].lower():
            acc_exe += 1
            correctness = True
        message = conversation.messages[1]  # role: "user"

        text_items = message.text_content_items
        if text_items:
            question = text_items[0].content
        else:
            question = None 
        logs.append({
            "conversation_id": conversation.conversation_id,
            "question": question,
            "response": response,
            "exec_result": exec_result,
            "label": conversation.metadata["ground_truth"],
            "case": case,
            "correctness": correctness,
            "success": success
        })
    exe_rate = success_exe / len(conversations)
    acc_rate = acc_exe / len(conversations)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    with open(f"./output/eval_log-{timestamp}.json", "w", encoding="utf-8") as f_log:
        json.dump(logs, f_log, ensure_ascii=False, indent=2)
        
        
    return {"exe_rate": exe_rate, "acc_rate": acc_rate }

yaml_path = "evaltools.yaml"
config = EvaluationConfig.from_yaml(yaml_path)

evaluator = Evaluator()
results = evaluator.evaluate(config, dataset=evaluation_dataset)

custom_task_results: dict = results[0].get_results()

print("exe_rate:", custom_task_results["exe_rate"])
print("acc_rate:", custom_task_results["acc_rate"])
print("Execution duration in sec:", results[0].elapsed_time_sec)
