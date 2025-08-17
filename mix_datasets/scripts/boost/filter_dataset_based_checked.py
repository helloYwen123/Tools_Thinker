import json
import os

# 1. 读取 correct_list，建立 (image_id, question) 的 set
correct_set = set()
with open('checked_correct.jsonl', 'r', encoding='utf-8') as fin:
    for line in fin:
        data = json.loads(line)
        image_id = data['QAid']
        question = data['question'].strip()
        correct_set.add((image_id, question))

# 2. 读取 dataset.json，遍历并过滤
with open('spatial457_wo_L5(8400)_random.json', 'r', encoding='utf-8') as fin:
    dataset = json.load(fin)

filtered = []
removed_count = 0  # 新增计数器

for entry in dataset:
    if not entry.get('images') or not entry.get('messages'):
        continue  # 跳过无效条目
    image_path = entry['images'][0]
    image_id = os.path.splitext(os.path.basename(image_path))[0]
    question = entry['messages'][0]['content'].strip()
    if (image_id, question) in correct_set:
        removed_count += 1  # 被过滤，计数+1
        continue
    filtered.append(entry)

# 3. 写回过滤后的数据
with open('spatial457_filtered.json', 'w', encoding='utf-8') as fout:
    json.dump(filtered, fout, ensure_ascii=False, indent=2)

# 4. 打印过滤结果
print(f"共过滤掉 {removed_count} 条数据，保留 {len(filtered)} 条数据。")

