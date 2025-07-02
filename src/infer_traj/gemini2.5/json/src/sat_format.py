import os
from datasets import load_dataset
import json
from tqdm import tqdm

with open("../mm_visual7w.json", "r", encoding="utf-8") as f:
    data = json.load(f)
 
def clean_answer_tag(answer_str):
    if "<answer>" in answer_str and "</answer>" in answer_str:
        start = answer_str.find("<answer>") + len("<answer>")
        end = answer_str.find("</answer>")
        return answer_str[start:end].strip()
    else:
        return answer_str
    
dataset_info = []
questions_id = 0
for idx, example in enumerate(tqdm(data["data"], desc="Processing dataset")):
    full_path = example["image_paths"][0]
    image_idx = full_path.find("images/")
    path = full_path[image_idx:] if image_idx != -1 else full_path 

    # entry = {
    #     "idx": idx,
    #     "messages": [
    #         {"role": "user", "content": example["question"]},
    #         {"role": "assistant", "content": example["answer"]}
    #     ],
    #     "images": [f"{path}"],
    #     "source": example["source"],
    #     "response": example.get("response", None),
    # }
    # dataset_info.append(entry)
    ##################################################
    response_lines = example["response"].split("\n")
    cleaned_responses = []
    for line in response_lines:
        line = line.strip()
        # Remove leading number
        if line and line[0].isdigit() and "." in line:
            line = line.split(".", 1)[1].strip()
        cleaned_responses.append(line)
    questions = example["question"]
    answers = example["answer"]
    for idx, (q, a) in enumerate(zip(questions, answers)):
        questions_id += 1
        if q.lower().startswith("question:"):
            q = q.split(":", 1)[1].strip()
        if a.lower().startswith("answer:"):
            a = a.split(":", 1)[1].strip()
        # Use response if available, else empty string
        response = cleaned_responses[idx] if idx < len(cleaned_responses) else ""
        entry = {
            "idx": questions_id,
            "messages": [
                {"role": "user", "content": q},
                {"role": "assistant", "content": a}
            ],
            "images": [f"{path}"],
            "source": example["source"],
            "response": response,
        }
        dataset_info.append(entry)



# 保存其他信息到 JSON 文件
with open("./SAT.json", "w", encoding="utf-8") as f:
    json.dump(dataset_info, f, indent=4, ensure_ascii=False)

print("✅ Other Information saved in: SAT.json")
