import os
import json
from tqdm import tqdm

root_dir = '../Rollout/ViRL'
output_file = 'success_traj.json'

success_entries = []

# 先统计一共多少个sample文件夹用于进度条
sample_folders = [d for d in os.listdir(root_dir) if os.path.isdir(os.path.join(root_dir, d))]

print(f"Total sample folders to check: {len(sample_folders)}")

for sample_folder in tqdm(sample_folders, desc="Processing samples"):
    sample_path = os.path.join(root_dir, sample_folder)
    json_file = os.path.join(sample_path, 'rollouts_trajectory_3.json')
    if not os.path.exists(json_file):
        tqdm.write(f"File not found: {json_file}")
        continue

    with open(json_file, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except Exception as e:
            tqdm.write(f"Failed to read {json_file}: {e}")
            continue

    found = 0
    for entry in data:
        if "final_solution" in entry:
            success_entries.append(entry)
            found += 1

    tqdm.write(f"{json_file}: Found {found} entries with 'solution' (Total so far: {len(success_entries)})")

# 保存到 success_traj.json
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(success_entries, f, ensure_ascii=False, indent=2)

print(f"\nTotal entries with 'solution': {len(success_entries)}")
print(f"Saved to: {output_file}")
