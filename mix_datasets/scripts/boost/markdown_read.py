import json
import re

input_path = 'boost/checked.jsonl'
output_path = 'boost/checked_correct.md'

def extract_code(text):
    # 匹配 <code>...</code> 之间的内容
    m = re.search(r"<code>\s*(.*?)\s*</code>", text, re.DOTALL)
    return m.group(1).strip() if m else ''

with open(input_path, 'r', encoding='utf-8') as fin, open(output_path, 'w', encoding='utf-8') as fout:
    for line in fin:
        data = json.loads(line)
        if data.get('llm_review', {}).get('result', '').strip().lower() == 'wrong': # 'correct‘
            qaid = data.get('QAid', 'N/A')
            question = data.get('question', '').strip()
            response = data.get('response', '')
            code = extract_code(response)
            review = data.get('llm_review', {})
            result = review.get('result', '')
            reason = review.get('reason', '')

            fout.write(f'### QAid: {qaid}\n\n')
            fout.write(f'**Question:**\n')
            fout.write(f'```\n{question}\n```\n\n')
            fout.write(f'**Code:**\n')
            fout.write(f'```python\n{code}\n```\n\n')
            fout.write(f'**LLM Review:**\n')
            fout.write(f'> result: {result}\n')
            fout.write(f'> reason: {reason}\n\n')
            fout.write('---\n\n')
