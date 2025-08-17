import json
import re
import yaml
import os

def insert_code_reasoning(answer_text):
    pattern = r"(Reason for approach:.*?)(\n\s*Analysis:)"
    replacement = r"\1\nSo I take the code reasoning approach.\2"
    return re.sub(pattern, replacement, answer_text, flags=re.DOTALL)

def extract_from_qa_pair(qa_text):
    question_match = re.search(r"<question>\s*(.*?)\s*</question>", qa_text, re.DOTALL)
    answer_match = re.search(r"<answer>\s*(.*?)\s*</answer>", qa_text, re.DOTALL)

    question = question_match.group(1).strip() if question_match else ""
    answer_text = answer_match.group(1).strip() if answer_match else ""

    return question, answer_text

def load_tool_data(conf):
    active_tool_names = conf.get("available_tools", [])
    full_toolbox_metadata = conf.get("toolbox_metadata", {})
    filtered_metadata_dict = {
        tool_name: full_toolbox_metadata[tool_name]
        for tool_name in active_tool_names
        if tool_name in full_toolbox_metadata
    }
    return active_tool_names, filtered_metadata_dict

def build_dialog(entry, system_prompt, user_template, tools_list, toolbox_metadata):
    image_path = entry["image_path"]
    qa_pair = entry["qa_pair"]

    image_id = os.path.basename(image_path)
    question, answer_text = extract_from_qa_pair(qa_pair)
    assert question and answer_text, "Extraction error!"
    answer_text = insert_code_reasoning(answer_text)

    user_message_text = user_template.format(
        question=question,
        input_images=image_path,
        available_tools=tools_list,
        toolbox_metadata=toolbox_metadata
    )
    
    conversation = {
        "conversation_id": f"{image_id}",
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "image_path", "content": image_path},
                    {"type": "text", "content": user_message_text}
                ]
            },
            {"role": "assistant", "content": answer_text}
        ],
        "metadata": {
            "ground_truth": None
        }
    }

    return conversation

def convert_qa_jsonl(input_path, output_path, config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        conf = yaml.safe_load(f)

    system_prompt = conf["system_prompt_template"]
    user_prompt_template = conf["user_prompt_template1"]

    tools, toolbox_metadata = load_tool_data(conf)
    tools_str = ", ".join(tools)

    with open(input_path, "r", encoding="utf-8") as fin, open(output_path, "w", encoding="utf-8") as fout:
        for idx, line in enumerate(fin, start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                new_entry = build_dialog(
                    entry, system_prompt, user_prompt_template,
                    tools_str, toolbox_metadata
                )
                fout.write(json.dumps(new_entry, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"❌ Error on line {idx}: {e}")
                print(f"🧪 Content: {line}")

if __name__ == "__main__":
    convert_qa_jsonl(
        # input_path= "/workspace/ywen_ws/datasets/single_tool_sft/text_tool/text_detector_qa.jsonl",
        input_path = "/workspace/ywen_ws/datasets/single_tool_sft/multi_tools/multi_tools_qa.jsonl",
        # "/workspace/ywen_ws/datasets/single_tool_sft/depth_tool/depth_estimator_qa.jsonl",

        # output_path= "../mix_train/text_tool_sft.jsonl",
        output_path= "../mix_train/multi_tools_qa_dirty.jsonl",
        # "../mix_train/depth_tool_sft.jsonl",
        config_path="../prompt.yaml"
    )
    print("✅ 转换完成！")
