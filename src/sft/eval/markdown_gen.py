import json

def extract_incorrect_to_md(input_path, output_md_path):
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    with open(output_md_path, "w", encoding="utf-8") as f_md:
        f_md.write("# ❌ Incorrect Execution Cases\n\n")
        i = 0
        for entry in data:
            if not entry.get("correctness", True):
                i += 1
                question = entry.get("question", "").strip()
                exec_result = entry.get("exec_result", "").strip()
                code = entry.get("response", "").strip()
                label = entry.get("label", "")

                f_md.write(f"## Example {i}\n")
                f_md.write(f"**Question:**\n```\n{question}\n```\n\n")
                f_md.write(f"**Code:**\n```\n{code}\n```\n\n")
                f_md.write(f"**Exec Result:**\n```\n{exec_result}\n```\n\n")
                f_md.write(f"**Ground Truth Label:** `{label}`\n\n")
                f_md.write("---\n\n")

    print(f"✅ Done! Incorrect cases written to: {output_md_path}")


if __name__ == "__main__":
    # 替换为你的路径
    input_json_path = "./output/eval_log-2025-06-16_22-21.json"
    output_md_path = "case_showing_all.md"
    extract_incorrect_to_md(input_json_path, output_md_path)
