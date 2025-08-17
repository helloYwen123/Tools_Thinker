import json

input_path = 'boost/checked.jsonl'
output_path = 'output_correct.jsonl'

with open(input_path, 'r', encoding='utf-8') as fin, open(output_path, 'w', encoding='utf-8') as fout:
    for line in fin:
        data = json.loads(line)
        # 检查 llm_review 里 result 是否为 correct
        if data.get('llm_review', {}).get('result', '').strip().lower() == 'correct':
            # 满足条件，写出整条
            fout.write(json.dumps(data, ensure_ascii=False) + '\n')