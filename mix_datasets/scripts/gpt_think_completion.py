import json
import re
import openai
from tqdm import tqdm
import yaml
import openai
import base64
client = openai.OpenAI(api_key="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")
conf = "../prompt.yaml"
with open(conf, "r") as stream:
    conf = yaml.safe_load(stream)

def extract_think(text):
    match = re.search(r'<think>\s*(.*?)\s*</think>', text, re.DOTALL)
    return match.group(1).strip() if match else None

def replace_think(text, new_think):
    return re.sub(r'<think>.*?</think>', f'<think>{new_think}</think>', text, flags=re.DOTALL)


def extract_question_block(text: str) -> str:
    match = re.search(r'\*\*Question:\*\*(.*?)\*\*Image', text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""

def detect_reasoning_type(assistant_content):
    # 只要出现<code>，就认为是code reasoning
    return "spatial question" if "<code>" in assistant_content else "general question"

def get_task_reason(question_type, question_block, image_path):
    # 图片base64
    with open(image_path, "rb") as f:
        base64_str = base64.b64encode(f.read()).decode()
    prompt = (
        f"Given the following visual question and image, explain in 1-3 sentences why this question should be classified as a **{question_type}**. "
        "Justify your answer based only on the question content and the image. "
        "Do not restate the question or describe how to solve it. "
        "Only provide the justification.\n\n"
        f"Question:\n{question_block}"
    )
    messages = [
        {"role": "system", "content": "You are an expert in classifying visual reasoning tasks."},
        {"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64_str}}
        ]}
    ]
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.3,
        max_tokens=200
    )
    return response.choices[0].message.content.strip()

def extract_image_path(user_message):
    for item in user_message:
        if isinstance(item, dict) and item.get("type") == "image_path":
            return item.get("content")
    return None

def extract_question_block_from_content(user_message):
    for item in user_message:
        if isinstance(item, dict) and item.get("type") == "text":
            return extract_question_block(item.get("content", ""))
    return ""

def process_file(input_path, output_path):
    with open(input_path, "r", encoding="utf-8") as fin, open(output_path, "w", encoding="utf-8") as fout:
        lines = [fin.readline() for _ in range(3)]
        for line in tqdm(fin, desc="Processing"):
            data = json.loads(line)
            image_path = None
            question_block = ""
            assistant_content = ""
            for msg in data.get("messages", []):
                if msg["role"] == "user":
                    content = msg["content"]
                    if isinstance(content, list):
                        image_path = extract_image_path(content)
                        question_block = extract_question_block_from_content(content)
                if msg["role"] == "assistant":
                    assistant_content = msg["content"]
            question_type = detect_reasoning_type(assistant_content) # "spatial question" or "general question"

            if question_type == "spatial question":
                reasoning_sentence = "So I take the code reasoning approach."
            else:
                reasoning_sentence = "So I take the natural language reasoning approach."

            if question_block and image_path:
                reason = get_task_reason(question_type, question_block, image_path)
                #
                for msg in data.get("messages", []):
                    if msg["role"] == "assistant":
                        think_text = extract_think(msg["content"])
                        print(f"\nExtracted think: {think_text[:60]}")
                        if think_text:
                            merged_think = f"Reason for approach:\n{reason}\n{reasoning_sentence}\nAnalysis:\n{think_text}"
                            msg["content"] = replace_think(msg["content"], merged_think)
            fout.write(json.dumps(data, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    process_file("../mix_train/r1_vision_train.jsonl", "r1_vision_train.explicit_and_original_think.jsonl")
