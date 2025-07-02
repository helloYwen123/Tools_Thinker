import yaml
import json

# 读取 YAML 文件内容
configuration_file = "prompt_configuration_file.yaml"

with open(configuration_file, "r", encoding="utf-8") as f:
    yaml_content = yaml.safe_load(f)

# 提取 toolbox_metadata 字典
TOOL_METADATA = yaml_content.get("toolbox_metadata")

# 使用 json.dumps 将 dict 序列化为字符串，并将实际换行符变为 \n 字符
one_line_string = json.dumps(TOOL_METADATA).replace("\n", "\\n")

# 将其写入 txt 文件
with open("toolbox_metadata_one_line.txt", "w", encoding="utf-8") as f:
    f.write(one_line_string)

# 可选：打印出来看看
print(one_line_string)
