# import argparse
# import json
# import re
# import sys
# from pathlib import Path

# # ---------- 正则 ----------
# THINK_RE = re.compile(r"<think>(.*?)</think>", re.S | re.I)
# # 仅匹配出现在 "Analysis:" 紧随其后的首个 "The tool"
# ANALYSIS_RE = re.compile(r"(Analysis:\s*)The\s+tool\b", re.I)

# def replace_in_think(block: str) -> (str, bool):
#     """替换单个 <think> 块"""
#     new_block, n = ANALYSIS_RE.subn(r"\1Segmenter", block, count=1)
#     return new_block, bool(n)

# def process_assistant(text: str) -> (str, bool):
#     """处理 assistant.content"""
#     changed = False

#     def _repl(m):
#         nonlocal changed
#         inner = m.group(1)
#         new_inner, ok = replace_in_think(inner)
#         changed = changed or ok
#         return f"<think>{new_inner}</think>"

#     new_text = THINK_RE.sub(_repl, text)
#     return new_text, changed


# def run(input_file: Path, output_file: Path):
#     total, success, fail_ids = 0, 0, []

#     with input_file.open("r", encoding="utf-8") as fin, \
#          output_file.open("w", encoding="utf-8") as fout:

#         for lineno, raw in enumerate(fin, 1):
#             line = raw.strip()
#             if not line:         # 空行，跳过
#                 continue

#             try:
#                 data = json.loads(line)
#             except json.JSONDecodeError as e:
#                 print(f"⚠️  JSON 解析失败: 行 {lineno}: {e}", file=sys.stderr)
#                 continue          # 跳过此行，继续后面的行

#             total += 1
#             cid = data.get("conversation_id", f"line-{lineno}")

#             replaced = False
#             for msg in data.get("messages", []):
#                 if msg.get("role") == "assistant" and isinstance(msg.get("content"), str):
#                     msg["content"], ok = process_assistant(msg["content"])
#                     replaced = replaced or ok

#             if replaced:
#                 success += 1
#             else:
#                 fail_ids.append(cid)

#             fout.write(json.dumps(data, ensure_ascii=False) + "\n")

#     print(f"✅ 完成: 共解析 {total} 条记录，成功替换 {success} 条。")
#     if fail_ids:
#         print("⚠️ 以下 conversation_id 未替换成功：", *fail_ids, sep="\n  - ", file=sys.stderr)

# if __name__ == "__main__":
#     p = argparse.ArgumentParser()
#     p.add_argument("--input", default = 'segment_tools_sft_correct.jsonl' , help="输入 jsonl 文件")
#     p.add_argument("--output", default = 'segment_tools_sft_correct_.jsonl', help="输出 jsonl 文件")
#     args = p.parse_args()
#     run(Path(args.input), Path(args.output))

# markdown
# import json
# from pathlib import Path
# import argparse

# def extract_assistant_contents(jsonl_path, md_out_path):
#     count = 0
#     with open(jsonl_path, "r", encoding="utf-8") as fin, \
#          open(md_out_path, "w", encoding="utf-8") as fout:
#         for line in fin:
#             data = json.loads(line)
#             conv_id = data.get("conversation_id", None)
#             for msg in data.get("messages", []):
#                 if msg.get("role") == "assistant" and isinstance(msg.get("content"), str):
#                     count += 1
#                     fout.write(f"## Conversation ID: {conv_id}\n\n")
#                     fout.write("```text\n")
#                     fout.write(msg["content"].strip() + "\n")
#                     fout.write("```\n\n")
#                     fout.write("---\n\n")
#     print(f"✅ 已提取 {count} 条 assistant 内容到 {md_out_path}")

# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(description="Extract assistant content to markdown")
#     parser.add_argument("--input",  required=True, help="输入 jsonl 文件路径")
#     parser.add_argument("--output", required=True, help="输出 markdown 文件路径")
#     args = parser.parse_args()
#     extract_assistant_contents(args.input, args.output)

# shuffle
# import random
# import argparse

# def shuffle_jsonl(path):
#     # 读取全部行
#     with open(path, 'r', encoding='utf-8') as f:
#         lines = f.readlines()
#     # 打乱顺序
#     random.shuffle(lines)
#     # 覆盖写回原文件
#     with open(path, 'w', encoding='utf-8') as f:
#         f.writelines(lines)
#     print(f"✅ 已打乱并覆盖保存到 {path} (共 {len(lines)} 行)")

# if __name__ == '__main__':
#     parser = argparse.ArgumentParser(description="Shuffle a jsonl file in place.")
#     parser.add_argument('--input', required=True, help='要打乱的 jsonl 文件路径')
#     args = parser.parse_args()
#     shuffle_jsonl(args.input)

# normalization
import json, re, textwrap, pathlib

IN_FILE  = "verified_tools_sft/text_tool_sft_correct.jsonl"
OUT_FILE = "verified_tools_sft/text_tool_sft_correct__.jsonl"

# 1️⃣ 需要自动补的 tool → import 行
TOOL_IMPORTS = {
    "Depth_Estimator_Tool": "from depth_estimator import Depth_Estimator_Tool",
    "Segmenter_Tool":       "from segmenter import Segmenter_Tool",
    "Object_Detector_Tool": "from object_detector import Object_Detector_Tool",
    "Text_Detector_Tool":   "from text_detector import Text_Detector_Tool",
    "Matcher_Tool":         "from matcher import Matcher_Tool",
}

# --------- 基础工具函数 ---------
def normalize_code(code: str) -> str:
    """去公共缩进 + 去掉首尾空行"""
    norm = textwrap.dedent(code)
    lines = norm.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)

def ensure_tool_imports(code: str) -> str:
    """若用到了某个 Tool 且缺少对应 import，则自动补一行"""
    imports_needed = []
    for tool, import_stmt in TOOL_IMPORTS.items():
        if tool in code and import_stmt not in code:
            imports_needed.append(import_stmt)

    if not imports_needed:
        return code

    lines = code.splitlines()
    insert_idx = 0
    for i, ln in enumerate(lines):
        if ln.strip().startswith(("import ", "from ")):
            insert_idx = i + 1
    patched_lines = lines[:insert_idx] + imports_needed + lines[insert_idx:]
    return "\n".join(patched_lines)

# --------- 处理整个 jsonl ---------
def process_jsonl(in_path: str, out_path: str):
    out_lines = []
    with open(in_path, "r", encoding="utf-8") as fr:
        for line in fr:
            obj = json.loads(line)
            # 找到 assistant 的 message，通常最后一个就是
            assistant_msg = next((m for m in reversed(obj["messages"]) if m["role"] == "assistant"), None)
            if assistant_msg is None:
                out_lines.append(line)  # 没有 assistant，原样写回
                continue

            content = assistant_msg["content"]
            m = re.search(r"<code>(.*?)</code>", content, flags=re.S)
            if not m:
                out_lines.append(line)
                continue

            raw_code = m.group(1)
            # 跑 normalize & import patch
            fixed_code = ensure_tool_imports(normalize_code(raw_code))

            # 把新的 code 替换回去
            new_content = content.replace(raw_code, fixed_code)
            assistant_msg["content"] = new_content
            out_lines.append(json.dumps(obj, ensure_ascii=False) + "\n")

    pathlib.Path(out_path).write_text("".join(out_lines), encoding="utf-8")
    print(f"✅ 处理完成，已保存到 {out_path}")

if __name__ == "__main__":
    process_jsonl(IN_FILE, OUT_FILE)
