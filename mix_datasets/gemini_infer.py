from google import genai
from google.genai import types
import json, yaml, re, time, random, os
from pathlib import Path
from tqdm import tqdm

# ---------------- Gemini client ----------------
client = genai.Client(api_key="AIzaSyBhhjYp_VcfIfu2Fi7rqEcy8I0CbuNVONc")
model_name = "gemini-2.5-flash"

# ---------------- 提取工具 ----------------------
QUESTION_RE = re.compile(r"\*\*Question:\*\*(.*?)\*\*Image\(s\):\*\*", re.DOTALL)
CODE_RE     = re.compile(r"<code>(.*?)</code>", re.DOTALL)
FENCE_RE    = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.DOTALL)   # ← for verify 解析

def extract_question(text: str):
    m = QUESTION_RE.search(text)
    return m.group(1).strip() if m else None

def extract_code(content: str):
    if not isinstance(content, str):
        return None
    match = re.search(r"<code>\s*(.*?)\s*</code>", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None

# ---------------- 解析 verify ------------------
def parse_verify(raw):
    """
    raw 可能是 dict / str / None
    return (dict | None, error_msg | None)
    """
    if isinstance(raw, dict):
        return raw, None
    if raw is None:
        return None, "verify is None"

    if isinstance(raw, str):
        stripped = FENCE_RE.sub(r"\1", raw).strip()
        try:
            return json.loads(stripped), None
        except Exception as e:
            return None, f"json.loads error: {e}"

    return None, f"unsupported type {type(raw)}"

def standardize_verdict(v):
    v = (v or "").strip().lower()
    if v in {"correct", "right", "true"}:
        return "correct"
    if v in {"wrong", "incorrect", "false"}:
        return "wrong"
    return "unknown"

# ---------------- prompt 构造 -------------------
def load_tool_data(conf):
    active = conf.get("available_tools", [])
    meta_all = conf.get("toolbox_metadata", {})
    return {k: meta_all[k] for k in active if k in meta_all}

def build_system_prompt(conf):
    tools = load_tool_data(conf)
    active_names = list(tools.keys())
    return f"""You are a professional verifier for multimodal tool-based question‑answering systems.

You must determine whether a Python code snippet correctly solves a visual reasoning question and is free of bugs.

Available Tools: {active_names}

Tool Metadata (JSON):
{json.dumps(tools, indent=2)}

Return only:
{{
  "verdict": "Correct" or "Wrong",
  "reason": "Concise explanation"
}}"""

def build_user_prompt(q, code):
    return f"""Question:
{q}

Code:
{code}

Does this code correctly and logically answer the question without any bugs? Please respond using only the specified JSON schema."""
# ------------------------------------------------

def gemini_call(system_prompt, user_prompt):
    safety_settings = [
        types.SafetySetting(
            category="HARM_CATEGORY_DANGEROUS_CONTENT",
            threshold="BLOCK_ONLY_HIGH",
        )
    ]
    time.sleep(random.uniform(0.4, 0.8))
    resp = client.models.generate_content(
        model=model_name,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.3,
            safety_settings=safety_settings,
        ),
    )
    return resp.text

# ---------------- 主流程 ------------------------
def process_jsonl(input_path, prompt_yaml_path, start_idx=0, end_idx=None):
    with open(prompt_yaml_path, "r") as f:
        conf = yaml.safe_load(f)
    system_prompt = build_system_prompt(conf)

    all_samples, correct, wrong, unparsed = [], [], [], []

    with open(input_path, "r", encoding="utf-8") as f:
        lines = enumerate(f)
        if start_idx or end_idx is not None:
            from itertools import islice
            lines = islice(lines, start_idx, end_idx)

        for i, line in tqdm(lines, desc="Verifying"):
            sample = json.loads(line)
            q_text, code_block = None, None

            # ---------- 提取 question / code ----------
            for m in sample.get("messages", []):
                if m["role"] == "user":
                    for item in m.get("content", []):
                        if item.get("type") == "text":
                            q = extract_question(item["content"])
                            if q: q_text = q
                elif m["role"] == "assistant":
                    code = extract_code(m.get("content", "").strip())
                    if code: code_block = code

            if not q_text or not code_block:
                sample.setdefault("metadata", {})["verify"] = {
                    "verdict": "Wrong",
                    "reason": "Question or code block missing"
                }
                wrong.append(sample)
                all_samples.append(sample)
                continue

            # ---------- Gemini 验证 ----------
            try:
                user_prompt = build_user_prompt(q_text, code_block)
                verify_str = gemini_call(system_prompt, user_prompt)
                verify_dict = json.loads(FENCE_RE.sub(r"\1", verify_str))
            except Exception as e:
                verify_dict = {"verdict": "Wrong", "reason": f"Gemini error: {e}"}

            sample.setdefault("metadata", {})["verify"] = verify_dict

            verdict_std = standardize_verdict(verify_dict.get("verdict"))
            if verdict_std == "correct":
                correct.append(sample)
            elif verdict_std == "wrong":
                wrong.append(sample)
            else:
                unparsed.append(sample)   # unknown verdict
                wrong.append(sample)      # 统计到 wrong
            all_samples.append(sample)

    # ---------- 保存 ----------
    base = Path(input_path).with_suffix("")
    out_all   = f"{base}_verified.jsonl"
    out_corr  = f"{base}_correct.jsonl"
    out_wrong = f"{base}_wrong.jsonl"
    out_unp   = f"{base}_unparsed.jsonl"

    def dump(path, data):
        if not data: return
        with open(path, "w", encoding="utf-8") as g:
            for s in data: g.write(json.dumps(s, ensure_ascii=False) + "\n")

    dump(out_all, all_samples)
    dump(out_corr, correct)
    dump(out_wrong, wrong)
    dump(out_unp, unparsed)

    print(f"\n✅ Done!  Correct={len(correct)}  Wrong={len(wrong)}  Unparsed={len(unparsed)}")
    print(f"• {out_all}\n• {out_corr}\n• {out_wrong}")
    if unparsed: print(f"• {out_unp}   <-- verify verdict 未识别 / 解析失败")

# ---------------- CLI --------------------------
if __name__ == "__main__":
    process_jsonl(
        input_path="mix_train/multi_tools_qa_dirty.jsonl",
        prompt_yaml_path="prompt.yaml",
        start_idx=0,   # ← 如需抽样可调这里
        end_idx=None,
    )
