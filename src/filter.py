import json

# 1. 读取原始数据
with open('/nfs/data8/liao/wxie/SAT/SAT_subtasks/SAT_Proximity.json', 'r') as f:
    data = json.load(f)

filtered_data = []
for entry in data:
    question = entry["messages"][0]["content"]
    if "marked" not in question:
        filtered_data.append(entry)

# 3. 保存为新的json文件
with open('/nfs/data8/liao/wxie/SAT/SAT_nomark/Proximity.json', 'w') as f:
    json.dump(filtered_data, f, indent=2, ensure_ascii=False)

print(f"过滤完成！原始 {len(data)} 条，保留 {len(filtered_data)} 条，已写入 filtered_data.json")
