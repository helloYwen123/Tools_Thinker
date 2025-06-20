import json
from pathlib import Path

def drop_assistant_turns(src_path: str, dst_path: str):
    """
    读取 src_path(*.jsonl)删除每个 entry 内 messages 数组里
    role == 'assistant' 的元素，并写入 dst_path。
    """
    src = Path(src_path)
    dst = Path(dst_path)

    with src.open("r", encoding="utf-8") as fin, dst.open("w", encoding="utf-8") as fout:
        for line in fin:
            entry = json.loads(line)

            if isinstance(entry, dict) and "messages" in entry:
                entry["messages"] = [
                    m for m in entry["messages"] if m.get("role") != "assistant"
                ]

            fout.write(json.dumps(entry, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    drop_assistant_turns("../train/merged_test.jsonl", "merged_test.jsonl")
    # drop_assistant_turns("train.jsonl", "train_eval.jsonl")