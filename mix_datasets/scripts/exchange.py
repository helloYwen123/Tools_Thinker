import json
from pathlib import Path

def load_replacements(src_path):
    """
    从源 JSONL 读取需要“抄过来”的内容。
    返回 dict:  {conversation_id: {"assistant": str, "metadata": dict}}
    """
    repl = {}
    with open(src_path, "r", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            cid = obj.get("conversation_id")
            if cid is None:
                continue
            # 取第一个 assistant
            assistant_msg = next(
                (m for m in obj["messages"] if m["role"] == "assistant"), None
            )
            if assistant_msg is None:
                continue
            repl[cid] = {
                "assistant": assistant_msg["content"],
                "metadata": obj.get("metadata", {}),
            }
    return repl


def replace_in_target(tgt_path, out_path, repl_dict):
    """
    遍历目标 JSONL，按 conversation_id 查找替换。
    - 用 repl_dict[cid]["assistant"] 覆盖第一条 assistant 的 content
    - 用 repl_dict[cid]["metadata"] 整体替换 metadata
    """
    with open(tgt_path, "r", encoding="utf-8") as fin, \
         open(out_path, "w", encoding="utf-8") as fout:
        for line in fin:
            obj = json.loads(line)
            cid = obj.get("conversation_id")
            if cid in repl_dict:
                # 1) 替换 assistant.content
                for msg in obj["messages"]:
                    if msg["role"] == "assistant":
                        msg["content"] = repl_dict[cid]["assistant"]
                        break  # 只替换第一条即可
                # 2) 替换 metadata
                obj["metadata"] = repl_dict[cid]["metadata"]
            fout.write(json.dumps(obj, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    src_jsonl  = "mix_train/mixture.explicit_and_original_think(163).jsonl"   # 拿来“抄”的那个文件
    tgt_jsonl  = "mixture_training_code_163.jsonl"   # 需要被替换的文件
    out_jsonl  = "mixture_training_code_163_replaced.jsonl"

    replacements = load_replacements(src_jsonl)
    replace_in_target(tgt_jsonl, out_jsonl, replacements)

    print("✅ 替换完成，结果保存到:", out_jsonl)
