import json

input_path = "dataset_merged.jsonl"
output_path = "dataset_megerd_single.jsonl"

with open(input_path, 'r', encoding='utf-8') as infile, open(output_path, 'w', encoding='utf-8') as outfile:
    for idx, line in enumerate(infile, start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            drop = False
            for message in data.get("messages", []):
                if message.get("role") == "user":
                    contents = message.get("content", [])
                    image_count = sum(
                        1 for c in contents if isinstance(c, dict) and c.get("type") == "image_path"
                    )
                    if image_count >= 2:
                        drop = True
                        break
            if not drop:
                outfile.write(json.dumps(data, ensure_ascii=False) + "\n")
            else:
                print(f"[Line {idx}] Dropped: multiple image_path entries (>=2), conversation_id = {data.get('conversation_id')}")
        except json.JSONDecodeError as e:
            print(f"[跳过无效 JSON] 第 {idx} 行: {e}")

