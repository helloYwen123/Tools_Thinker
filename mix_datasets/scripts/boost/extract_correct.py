#!/usr/bin/env python3
"""
QAid: <id>
...
question:
<question text>
...
response:
<response text>

Write them to one JSONL:
{"QAid": "...", "question": "...", "response": "..."}

Usage:
    python collect_qa.py <root_dir> <output.jsonl>
"""

import re
import json
import sys
from pathlib import Path

# ---------- 正则 ----------
QAID_RE            = re.compile(r'^\s*QAid\s*:\s*(\S+)', re.I)
QUESTION_START_RE  = re.compile(r'^\s*question\s*:\s*$', re.I)
RESPONSE_START_RE  = re.compile(r'^\s*response\s*:\s*$', re.I)
GOOD_TAG_RE        = re.compile(r'^\s*(correct result|exec_result\s*:\s*true)\b', re.I)
BAD_TAG_RE         = re.compile(r'^\s*(wrong result|exec_result\s*:\s*false)\b', re.I)

def parse_blocks(text: str):
    """提取并返回仅含 'correct result' 的块."""
    lines = text.splitlines()
    i, n = 0, len(lines)
    blocks = []

    while i < n:
        m = QAID_RE.match(lines[i])
        if not m:
            i += 1
            continue

        qaid = m.group(1)
        question, response = [], []
        keep_block = True        # 先假设保留

        i += 1
        # 在读 question 之前可能出现 correct/wrong 或 exec_result
        while i < n and not QUESTION_START_RE.match(lines[i]):
            if BAD_TAG_RE.search(lines[i]):
                keep_block = False
            elif GOOD_TAG_RE.search(lines[i]):
                keep_block = True
            i += 1
        i += 1  # 跳过 question: 行

        while i < n and not RESPONSE_START_RE.match(lines[i]):
            question.append(lines[i])
            i += 1
        i += 1  # 跳过 response: 行

        while i < n and not QAID_RE.match(lines[i]):
            response.append(lines[i])
            # 若在 response 之后再出现 exec_result 也继续判断
            if BAD_TAG_RE.search(lines[i]):
                keep_block = False
            elif GOOD_TAG_RE.search(lines[i]):
                keep_block = True
            i += 1

        if keep_block:
            blocks.append({
                "QAid": qaid,
                "question": "\n".join(question).strip(),
                "response": "\n".join(response).strip(),
            })

    return blocks

def collect(root: Path, steps=range(1, 21)):
    for step in steps:
        step_dir = root / "accuracy" / f"step_{step}"
        if not step_dir.is_dir():
            continue
        for file in step_dir.iterdir():
            if not file.is_file():
                continue
            try:
                text = file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for rec in parse_blocks(text):
                rec["file"] = str(file.relative_to(root))  # 可选
                yield rec

def main(root_dir: str, out_path: str):
    root = Path(root_dir).expanduser().resolve()
    records = list(collect(root))
    with open(out_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"✅ {len(records)} correct-result records written to {out_path}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python collect_qa.py <root_dir> <output.jsonl>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])

# python collect_correct.py /workspace/models/exp_pure_code_spatial457_w_code_len_logs/grpo_tools_logs/train output.jsonl