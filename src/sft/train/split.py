import json
import random

def split_jsonl(input_path, train_path, test_path, train_ratio=0.8, seed=42):
    with open(input_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    random.seed(seed)
    random.shuffle(lines)
    
    total = len(lines)
    train_num = int(total * train_ratio)
    train_lines = lines[:train_num]
    test_lines = lines[train_num:]
    
    with open(train_path, 'w', encoding='utf-8') as f_train:
        f_train.writelines(train_lines)
    with open(test_path, 'w', encoding='utf-8') as f_test:
        f_test.writelines(test_lines)
    
    print(f"Total: {total}, Train: {len(train_lines)}, Test: {len(test_lines)}")


split_jsonl(
    input_path='./oumi_success_traj.jsonl',
    train_path='./train.jsonl',
    test_path='./test.jsonl',
    train_ratio=0.8 # Trainning set's rate number
)
