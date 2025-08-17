# remove the samples with multi-images for oumi
import json

input_path = "mixture_training.jsonl"
filtered_output = "mixture_training_.jsonl"
skipped_output = "skipped.jsonl"

with open(input_path, "r") as fin, \
     open(filtered_output, "w") as fout_filtered, \
     open(skipped_output, "w") as fout_skipped:

    for i, line in enumerate(fin, 1):
        try:
            sample = json.loads(line)
            # 统计 image_path 的数量
            image_count = 0
            for msg in sample.get("messages", []):
                content = msg.get("content", [])
                if isinstance(content, list):
                    image_count += sum(1 for item in content if item.get("type") == "image_path")

            if image_count <= 1:
                fout_filtered.write(json.dumps(sample, ensure_ascii=False) + "\n")
            else:
                fout_skipped.write(json.dumps(sample, ensure_ascii=False) + "\n")
                print(f"[跳过] 第 {i} 行: 包含 {image_count} 个 image_path")

        except Exception as e:
            print(f"[错误] 第 {i} 行 JSON 无效: {e}")
