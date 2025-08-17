import argparse
import json
import re
import sys
from pathlib import Path

# ---------- 正则 ----------
THINK_RE = re.compile(r"<think>(.*?)</think>", re.S | re.I)
# 仅匹配出现在 "Analysis:" 紧随其后的首个 "The tool"
ANALYSIS_RE = re.compile(r"(Analysis:\s*)The\s+tool\b", re.I)

def replace_in_think(block: str) -> (str, bool):
    """替换单个 <think> 块"""
    new_block, n = ANALYSIS_RE.subn(r"\1Depth Estimator", block, count=1)
    return new_block, bool(n)

def process_assistant(text: str) -> (str, bool):
    """处理 assistant.content"""
    changed = False

    def _repl(m):
        nonlocal changed
        inner = m.group(1)
        new_inner, ok = replace_in_think(inner)
        changed = changed or ok
        return f"<think>{new_inner}</think>"

    new_text = THINK_RE.sub(_repl, text)
    return new_text, changed


def run(input_file: Path, output_file: Path):
    total, success, fail_ids = 0, 0, []

    with input_file.open("r", encoding="utf-8") as fin, \
         output_file.open("w", encoding="utf-8") as fout:

        for lineno, raw in enumerate(fin, 1):
            line = raw.strip()
            if not line:         # 空行，跳过
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"⚠️  JSON 解析失败: 行 {lineno}: {e}", file=sys.stderr)
                continue          # 跳过此行，继续后面的行

            total += 1
            cid = data.get("conversation_id", f"line-{lineno}")

            replaced = False
            for msg in data.get("messages", []):
                if msg.get("role") == "assistant" and isinstance(msg.get("content"), str):
                    msg["content"], ok = process_assistant(msg["content"])
                    replaced = replaced or ok

            if replaced:
                success += 1
            else:
                fail_ids.append(cid)

            fout.write(json.dumps(data, ensure_ascii=False) + "\n")

    print(f"✅ 完成: 共解析 {total} 条记录，成功替换 {success} 条。")
    if fail_ids:
        print("⚠️ 以下 conversation_id 未替换成功：", *fail_ids, sep="\n  - ", file=sys.stderr)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", default = 'depth_tool_sft_correct.jsonl' , help="输入 jsonl 文件")
    p.add_argument("--output", default = 'depth_tool_sft_correct_.jsonl', help="输出 jsonl 文件")
    args = p.parse_args()
    run(Path(args.input), Path(args.output))