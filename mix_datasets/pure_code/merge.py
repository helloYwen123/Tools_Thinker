import os
import json
import random

def merge_and_shuffle_jsonl(output_path='merged_shuffled.jsonl'):
    # 1. 获取当前目录下所有 .jsonl 文件
    jsonl_files = [f for f in os.listdir('.') if f.endswith('.jsonl')]

    all_data = []

    # 2. 读取所有 jsonl 文件的内容
    for file in jsonl_files:
        with open(file, 'r', encoding='utf-8') as f:
            lines = [json.loads(line.strip()) for line in f if line.strip()]
            all_data.extend(lines)

    # 3. 打乱顺序
    random.shuffle(all_data)

    # 4. 保存到新的 jsonl 文件
    with open(output_path, 'w', encoding='utf-8') as out_f:
        for item in all_data:
            out_f.write(json.dumps(item, ensure_ascii=False) + '\n')

    print(f'Merged and shuffled {len(jsonl_files)} files with {len(all_data)} entries.')
    print(f'Saved to: {output_path}')

if __name__ == "__main__":
    merge_and_shuffle_jsonl()
