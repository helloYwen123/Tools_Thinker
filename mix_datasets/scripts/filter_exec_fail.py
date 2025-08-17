import json

def extract_conversation_ids(json_path):
    """从 JSON 文件中提取所有 conversation_id"""
    with open(json_path, 'r', encoding='utf-8') as f:
        entries = json.load(f)
    return {entry["conversation_id"] for entry in entries if "conversation_id" in entry}

def filter_jsonl_by_conversation_ids(jsonl_path, output_path, ids_to_remove):
    """从 JSONL 文件中过滤掉指定的 conversation_id 条目"""
    with open(jsonl_path, 'r', encoding='utf-8') as infile, \
         open(output_path, 'w', encoding='utf-8') as outfile:
        
        for line in infile:
            try:
                item = json.loads(line)
                if item.get("conversation_id") not in ids_to_remove:
                    outfile.write(json.dumps(item, ensure_ascii=False) + '\n')
            except json.JSONDecodeError:
                print("跳过无法解析的行")
                continue
    print(f"✅ 已保存过滤后的文件到：{output_path}")

if __name__ == "__main__":
    # === 路径配置 ===
    json_with_ids_path = "../failed_cases01.json"       # 包含 conversation_id 的 json 文件
    input_jsonl_path = "../mix_train/multi_orientation_qa_dirty_correct(68).jsonl"     # 原始 jsonl 文件
    output_jsonl_path = "filtered_dataset.jsonl"  # 输出文件

    # === 执行 ===
    conversation_ids_to_remove = extract_conversation_ids(json_with_ids_path)
    filter_jsonl_by_conversation_ids(input_jsonl_path, output_jsonl_path, conversation_ids_to_remove)
