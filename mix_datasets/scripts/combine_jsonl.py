import json
import random

def sample_jsonl(input_path, num_samples):
    with open(input_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    if num_samples >= len(lines):
        samples = lines
    else:
        samples = random.sample(lines, num_samples)
    samples = [json.loads(line) for line in samples]
    return samples

file1 = 'mix_train/mixture_training_code_163.jsonl'
file2 = 'mix_train/r1_vision_train.jsonl'
n1 = 163
n2 = 183

samples1 = sample_jsonl(file1, n1)
samples2 = sample_jsonl(file2, n2)

merged_samples = samples1 + samples2

# 打乱顺序
random.shuffle(merged_samples)

with open('merged.jsonl', 'w', encoding='utf-8') as out_f:
    for item in merged_samples:
        out_f.write(json.dumps(item, ensure_ascii=False) + '\n')

print(f"合并并打乱完成，共{len(merged_samples)}条数据，已保存为 merged.jsonl")
