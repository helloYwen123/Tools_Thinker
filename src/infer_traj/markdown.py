import json
import glob
import os
# 假设你的 json 数据放在 .json 文件里
json_files = glob.glob("*.json")
all_data = []
json_files = ["GQA_SAT.json"]
for file in json_files:
    with open(file, "r") as f:
        data = json.load(f)
        all_data.extend(data) 

# 创建 markdown 文本
md_lines = []

for idx, item in enumerate(all_data):
    md_lines.append(f"### Example {idx+1}\n")
    md_lines.append(f"**Question:** {item['question']}\n")
    # code_ex1
    if 'code_ex1' in item:
        code1 = item['code_ex1'].replace('<code>', '').replace('</code>', '').replace("\\n", "\n").strip()
        md_lines.append("**code_ex1:**\n")
        md_lines.append(f"```python\n{code1}\n```\n")
    # code_ex2
    if 'code_ex2' in item:
        code2 = item['code_ex2'].replace('<code>', '').replace('</code>', '').replace("\\n", "\n").strip()
        md_lines.append("**code_ex2:**\n")
        md_lines.append(f"```python\n{code2}\n```\n")
    if 'code_ex3' in item:
        code2 = item['code_ex3'].replace('<code>', '').replace('</code>', '').replace("\\n", "\n").strip()
        md_lines.append("**code_ex3:**\n")
        md_lines.append(f"```python\n{code2}\n```\n")
    # final_solution
    if 'final_solution' in item:
        md_lines.append(f"**Final Solution:** {item['final_solution']}\n")
    md_lines.append("\n---\n")

# 输出 markdown 文件
filename_without_ext = os.path.splitext(json_files[0])[0]
with open(f"{filename_without_ext}.md", "w") as f:
    f.write('\n'.join(md_lines))

print("转换完成，已生成 examples.md，可以直接用Typora、VSCode等打开。")