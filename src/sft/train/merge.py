import os
import json
import random

input_folder = "json_files"
train_output_file = "merged_train.jsonl"
test_output_file = "merged_test.jsonl"

start_id = 100
current_id = start_id

jsonl_files = sorted([f for f in os.listdir(input_folder) if f.endswith('.jsonl')])

def is_valid_sample(data):
    for message in data.get("messages", []):
        if message.get("role") == "user":
            contents = message.get("content", [])
            image_count = sum(
                1 for c in contents if isinstance(c, dict) and c.get("type") == "image_path"
            )
            if image_count >= 2:
                return False
    return True

with open(train_output_file, 'w', encoding='utf-8') as train_outfile, \
     open(test_output_file, 'w', encoding='utf-8') as test_outfile:

    for filename in jsonl_files:
        file_path = os.path.join(input_folder, filename)

        # 
        samples = []
        with open(file_path, 'r', encoding='utf-8') as infile:
            for idx, line in enumerate(infile, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if is_valid_sample(data):
                        samples.append(data)
                except json.JSONDecodeError as e:
                    print(f"[跳过无效 JSON] {filename}, 第 {idx} 行: {e}")

        
        random.shuffle(samples)

        #
        test_samples = samples[:8]
        train_samples = samples[8:]

        # 写入 test 样本
        for sample in test_samples:
            sample["conversation_id"] = str(current_id)
            json.dump(sample, test_outfile, ensure_ascii=False)
            test_outfile.write("\n")
            current_id += 1

        # 写入 train 样本
        for sample in train_samples:
            sample["conversation_id"] = str(current_id)
            json.dump(sample, train_outfile, ensure_ascii=False)
            train_outfile.write("\n")
            current_id += 1
