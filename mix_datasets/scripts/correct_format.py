import json
import re
import yaml
# 
def extract_question_and_image(text_block):
    question_match = re.search(r"^(.*?)\nPlease use the following path\(s\)", text_block, re.DOTALL)
    image_match = re.search(r"corresponding to this question:\s*\n(\/[^\s]+)", text_block)
    
    question = question_match.group(1).strip() if question_match else None
    image_path = image_match.group(1).strip() if image_match else None
    return question, image_path

# 
def process_entry(entry, SYSTEM_TEMPLATE, USER_TEMPLATE, tools_list, filtered_meta):
    if "messages" in entry:
        for m in entry["messages"]:
            if m["role"] == "system":
                m["content"] = SYSTEM_TEMPLATE
            elif m["role"] == "user":
                for block in m.get("content", []):
                    if block.get("type") == "text":
                        question, image_path = extract_question_and_image(block["content"])
                        if question and image_path:
                            block["content"] = USER_TEMPLATE.format(
                                question=question,
                                input_images=image_path,
                                available_tools=tools_list,
                                toolbox_metadata=filtered_meta
                            )
                            break
    return entry

def load_tool_data(conf):
    active_tool_names = conf.get("available_tools", [])  # 来自 YAML 的启用工具列表
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

#

def process_jsonl(input_path, output_path, configuration_file):
    with open(configuration_file, "r", encoding="utf-8") as stream:
        conf = yaml.safe_load(stream)

    system_prompt_template = conf.get("system_prompt_template")
    user_prompt_template = conf.get("user_prompt_template1")

    active_tools, filtered_meta = load_tool_data(conf)
    tools_list = ", ".join(active_tools)

    with open(input_path, "r", encoding="utf-8") as fin, open(output_path, "w", encoding="utf-8") as fout:
        for idx, line in enumerate(fin, start=1):
            line = line.strip()
            if not line:
                continue  # 跳过空行
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"❌ JSON decode error at line {idx}: {e}")
                print(f"🔍 内容: {repr(line)}")
                continue  # 跳过无法解析的行

            new_entry = process_entry(
                entry,
                SYSTEM_TEMPLATE=system_prompt_template,
                USER_TEMPLATE=user_prompt_template,
                tools_list=tools_list,
                filtered_meta=filtered_meta
            )
            fout.write(json.dumps(new_entry, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    input_jsonl = "jsonl/mixture_training_promptwrong_single.jsonl"     # 
    output_jsonl = "mixture_training_code_163.jsonl"   #
    configuration_file = "prompt.yaml"
    process_jsonl(input_jsonl, output_jsonl,configuration_file)
    print("转换完成 ✔")