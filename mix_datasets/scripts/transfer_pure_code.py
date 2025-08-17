import yaml
import json
import re

def load_tool_data(conf):
    active_tool_names = conf.get("available_tools", [])
    full_toolbox_metadata = conf.get("toolbox_metadata", {})
    filtered_metadata_dict = {
        tool_name: full_toolbox_metadata[tool_name]
        for tool_name in active_tool_names
        if tool_name in full_toolbox_metadata
    }
    for tool_name in active_tool_names:
        if tool_name not in full_toolbox_metadata:
            print(f"Warning: Tool '{tool_name}' listed in available_tools but not found in toolbox_metadata.")
    return active_tool_names, filtered_metadata_dict

with open('prompt.yaml', "r", encoding="utf-8") as stream:
    conf = yaml.safe_load(stream)

system_prompt_template = conf.get("system_prompt_template2")
user_prompt_template = conf.get("user_prompt_template2")
active_tools, filtered_meta = load_tool_data(conf)
tools_list = ", ".join(active_tools)

def extract_question_and_images(text):
    question_match = re.search(r"\*\*Question:\*\*\s*(.*?)\s*\*\*Image", text, re.DOTALL)
    if question_match:
        question = question_match.group(1).strip()
    else:
        question = ""

    image_match = re.search(r"\*\*Image\(s\):\*\*\s*(.*)", text)
    if image_match:
        input_images = image_match.group(1).strip()
    else:
        input_images = ""
    return question, input_images

with open('mix_train/single_tool.explicit_and_original_think(290)_clean.jsonl', 'r', encoding='utf-8') as fin, \
     open('single_tool.explicit_and_original_think(290)_clean_code.jsonl', 'w', encoding='utf-8') as fout:
    for line in fin:
        data = json.loads(line)

        # 替换 system prompt
        for msg in data['messages']:
            if msg['role'] == 'system':
                msg['content'] = system_prompt_template

        # 替换 user prompt（仅替换 text类型，图片不变）
        for msg in data['messages']:
            if msg['role'] == 'user':
                for part in msg['content']:
                    if part['type'] == 'text':
                        old_text = part['content']
                        # 提取 question 和 input_images
                        question, input_images = extract_question_and_images(old_text)
                        # 拼接新 user prompt
                        user_prompt = user_prompt_template.format(
                            available_tools=tools_list,
                            toolbox_metadata=json.dumps(filtered_meta, ensure_ascii=False, indent=2),
                            question=question,
                            input_images=input_images
                        )
                        part['content'] = user_prompt

        fout.write(json.dumps(data, ensure_ascii=False) + '\n')
