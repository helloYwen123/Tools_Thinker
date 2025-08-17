import json
import re

input_path = '../mix_train/multi_orientation_qa_dirty(99).jsonl'  # 替换为你的jsonl路径
output_path = 'output.md'

def extract_question_and_image(text):
    # 提取 **Question:** ... 以及 **Image(s):** ... 的块，直到遇到空行或下一个 **
    q_match = re.search(r"(\*\*Question:\*\*.*?)(?=\n\s*\*\*|$)", text, re.DOTALL)
    if q_match:
        return q_match.group(1).strip()
    return ""

def extract_code_block(text):
    match = re.search(r"<code>(.*?)</code>", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""

with open(input_path, "r", encoding="utf-8") as fin, open(output_path, "w", encoding="utf-8") as fout:
    for line in fin:
        entry = json.loads(line)
        # extracct user question block
        question_block = ""
        for msg in entry.get('messages', []):
            if msg['role'] == 'user':
                for c in msg.get('content', []):
                    if isinstance(c, dict) and c.get('type') == 'text':
                        question_block = extract_question_and_image(c['content'])
                        if question_block:
                            break
            if question_block:
                break
        if not question_block:
            continue

        # 提取assistant's code 
        code_block = ""
        for msg in entry.get('messages', []):
            if msg['role'] == 'assistant':
                content = msg.get('content', '')
                code_block = extract_code_block(content)
                if code_block:
                    break

        verify = entry.get('metadata', {}).get('verify', {})
        verdict = verify.get('verdict', '')
        reason = verify.get('reason', '')

        fout.write('---\n')
        fout.write(f'**Question & Image Block:**\n\n{question_block}\n\n')
        fout.write(f'**Assistant `<code>` Block:**\n\n```python\n{code_block}\n```\n\n')
        fout.write('**Verify Result:**\n\n')
        fout.write(f'- Verdict: **{verdict}**\n')
        fout.write(f'- Reason: {reason}\n\n')

print(f"Done! Extracted entries are saved in {output_path}")
