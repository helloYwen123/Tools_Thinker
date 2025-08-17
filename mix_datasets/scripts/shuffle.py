import json
import random

def shuffle_jsonl(input_path, output_path):
    # 读取所有行
    with open(input_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # 打乱顺序
    random.shuffle(lines)

    # 写入新文件
    with open(output_path, 'w', encoding='utf-8') as f:
        for line in lines:
            f.write(line)

    print(f'Shuffled file saved to: {output_path}')

# 使用示例
input_file = '/workspace/ywen_ws/mix_datasets/sft_training_fine(875)_w_multitools.jsonl'     # 替换为你的输入文件路径
output_file = 'shuffled_output.jsonl'  # 替换为你想保存的输出文件路径
shuffle_jsonl(input_file, output_file)
