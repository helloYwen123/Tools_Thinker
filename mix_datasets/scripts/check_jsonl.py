import json
with open("sft_training_fine(875)_w_multitools.jsonl", "r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        try:
            json.loads(line)
        except Exception as e:
            print(f"❌ Line {i} is invalid JSON: {e}")