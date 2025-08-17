#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
gen_tools_based_qapairs.py
------------------------
运行示例：
  python gen_segmenter_qapairs.py \
      --data dataset.json \
      --out segmenter_qa.jsonl \
"""
import json, os, argparse, re
from pathlib import Path
from typing import Any, Dict, List
import openai
from tqdm import tqdm
import yaml
import base64
import shutil
import random,time
from pathlib import Path
from PIL import Image
from google import genai
from google.genai import types

def encode_image_base64(image_path):
    with open(image_path, "rb") as img_file:
        encoded = base64.b64encode(img_file.read()).decode("utf-8")
    suffix = Path(image_path).suffix.lower()
    mime_type = "image/jpeg" if suffix in [".jpg", ".jpeg"] else "image/png"
    return encoded, mime_type
# 
def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def compress_image(input_path, output_path, max_size=512, quality=85):
    """
    compress
    """
    img = Image.open(input_path)
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    img.save(output_path, quality=quality)

def load_tool_data(conf):
    active_tool_names = conf.get("available_tools", [])  #
    full_toolbox_metadata = conf.get("toolbox_metadata", {})

    filtered_metadata_dict = {
        tool_name: full_toolbox_metadata[tool_name]
        for tool_name in active_tool_names
        if tool_name in full_toolbox_metadata
    }

    for tool_name in active_tool_names:
        if tool_name not in full_toolbox_metadata:
            print(f"Warning: Tool '{tool_name}' listed in available_tools but not found in toolbox_metadata.")

    return active_tool_names, filtered_metadata_dict

# # object detection and localization, image segmentation, spatial relationship reasoning, layout analysis, text region detection, depth estimation, or visual similarity comparison.
SYSTEM_TPL = """
You are an expert tutor tasked with answering spatial-reasoning questions using a toolbox of vision APIs.
For each question you receive:
  • the textual question
  • the path to the related image
Your job:
  1. Explain why the question regards a spatial question and why solving the task requires code reasoning, and then think step by step how to solve it:.
  2. Write Python code that calls **at least TWO distinct tools** from the toolbox in a logical sequence.
     Use only the calling conventions given in the metadata.
     Assign the final answer to the variable `final_result`.

Return your work strictly in the following format:
<answer>
<think>
Reason for approach: <explain why the question regards a spatial question and  why solving the task requires more than one tool>
Analysis: <explain how the tools are used and combined to solve the task, step by step>
</think>
<code>
`Python` code that correctly calls the tools in the required sequence,
using only the calling conventions in the toolbox metadata,
with all necessary imports.
Assign the final answer to `final_result`.
</code>
</answer>

Constraints:
- You may ONLY use tools from the provided toolbox (see metadata).
- Each question **MUST** require at least two different tools in combination.
- The code must be self-contained, following the metadata's syntax.
"""



USER_TPL = """
Please carefully review the following tool metadata(JSON):
{api_meta}

<question_text>
{question_text}
</question_text>

Image path: {img_path}  

Guidelines in Code:
- Carefully review the tool metadata to invoke each tool correctly.
- The answer code should be a complete script, including all necessary `tool_module` imports.
- Solve the question using the toolbox. Combine multiple tools; do not rely on a single tool.
- Output only the <answer> block.

Remember, your answer should be based on code reasoning that invokes the provided tool APIs, not just natural language explanations:
"""

def build_messages(question_text: str, img_path: str, api_meta: str, backend: str = "gemini") -> List[Dict[str, Any]]:
    """Create the input according to the backend (openai chat vs gemini)."""

    user_prompt = USER_TPL.format(
        api_meta=api_meta,
        question_text=question_text,
        img_path=img_path,
    )
    # print(f"user prompt: \n{user_prompt}")
    if backend == "openai":
        encoded_image, mime_type = encode_image_base64(img_path)
        return [
            {"role": "system", "content": SYSTEM_TPL},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"}},
                ],
            },
        ]
    elif backend == "gemini":
        # Gemini "contents" is a flat list of text and PIL images
        return [user_prompt, Image.open(img_path)]  # system prompt passed separately via config
    else:
        raise ValueError(f"Unsupported backend: {backend}")


def main(args):
    
    conf = "prompt.yaml"
    with open(conf, "r") as stream:
        conf = yaml.safe_load(stream)

    data = load_json(args.data)
    random.seed(42)
    random.shuffle(data)
    data = data[0:1]

    active_tools, filtered_meta = load_tool_data(conf)
    active_tools = ",".join(active_tools)
    api_meta_str = json.dumps(filtered_meta, indent=2)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    md_path = out_path.with_suffix(".md")
    Path(args.image_out_dir).mkdir(parents=True, exist_ok=True)
    backend = args.backend.lower()
    if backend == "openai":
        import openai
        client = openai.OpenAI(api_key="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")
        # client = openai.OpenAI(api_key="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")
    elif backend == "gemini":
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
        client = genai.Client(api_key="AIzaSyBhhjYp_VcfIfu2Fi7rqEcy8I0CbuNVONc")
        safety_settings = [
        types.SafetySetting(
            category="HARM_CATEGORY_DANGEROUS_CONTENT",
            threshold="BLOCK_ONLY_HIGH",
                )
            ]
    else:
        raise ValueError("--backend must be openai or gemini")

       # 5. Iterate over sampled questions
    with out_path.open("a+", encoding="utf-8") as jout, md_path.open("a+", encoding="utf-8") as jmd:
        for item in tqdm(data, desc="Generating answers"):
            # Parse fields
            question_text = item["messages"][0]["content"]
            img_path_orig = "/workspace/ywen_ws/datasets/Spatial457/" + item["images"][0]
            if not os.path.isfile(img_path_orig):
                print(f"❌ image not found: {img_path_orig}")
                continue

            # Copy (and optionally compress) image to working dir for traceability
            new_img_name = os.path.basename(img_path_orig)
            new_img_path = os.path.join(args.image_out_dir, new_img_name)
            try:
                shutil.copy(img_path_orig, new_img_path)
                # compress_image(new_img_path, new_img_path)  # uncomment if needed
            except Exception as e:
                print(f"❌ Failed to copy {img_path_orig}: {e}")
                continue

            # Build messages
            if backend == "openai":
                messages = build_messages(question_text, new_img_path, api_meta_str, backend="openai")
            else:  # gemini
                contents = build_messages(question_text, new_img_path, api_meta_str, backend="gemini")

            # Call the model
            try:
                if backend == "openai":
                    response = client.chat.completions.create(
                        model="gpt-4o",  # or args.model
                        messages=messages,
                        temperature=0.3,
                        max_tokens=800,
                    )
                    content = response.choices[0].message.content.strip()
                else:  # gemini
                    response = client.models.generate_content(
                        model="gemini-2.5-pro", 
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_TPL,
                            temperature=0.3,
                            safety_settings=safety_settings,
                        ),
                    )
                    content = response.text
            except Exception as e:
                print(f"⚠️ API error on {new_img_path}: {e}")
                continue

            print(content)
            # <answer>
            if not re.search(r"<answer>.*?</answer>", content, re.S):
                print(f"Missing <answer> tag, skip {img_path_orig}")
                continue

            # Validate answer block
            answer_match = re.search(r"<answer>.*?</answer>", content, re.S)
            answer_xml = answer_match.group(0).strip()

            # Save to jsonl
            jout.write(
                json.dumps({"question": question_text, "image_path": new_img_path, "answer": answer_xml}, ensure_ascii=False)
                + "\n"
            )

            # Render to markdown (optional)
            think_match = re.search(r"<think>(.*?)</think>", answer_xml, re.S)
            code_match = re.search(r"<code>(.*?)</code>", answer_xml, re.S)
            jmd.write(f"### Q: {question_text}\n\n")
            if think_match:
                jmd.write("**Think:**\n\n" + think_match.group(1).strip() + "\n\n")
            if code_match:
                jmd.write("**Code:**\n\n```python\n" + code_match.group(1).strip() + "\n```\n\n")
            jmd.write("---\n\n")
            time.sleep(random.uniform(5,8))  # polite delay

    print(f"✅ Done! Saved answers to {out_path}")


# ---------------------------- CLI ----------------------------------
if __name__ == "__main__":
    # /workspace/ywen_ws/datasets/Spatial457/questions_sat/L5_6d_spatial_mcq.json
    # /workspace/ywen_ws/datasets/Spatial457/questions_sat/L5_collision_mcq.json

    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="JSON file containing existing questions + images")
    parser.add_argument("--out", default="/workspace/ywen_ws/datasets/single_tool_sft/multi_tools/multi_tools_given_spatial_qa.jsonl", help="Output jsonl file path")
    parser.add_argument("--image_out_dir", default="/workspace/ywen_ws/datasets/single_tool_sft/multi_tools/multi_tools_imgs/", help="Directory to copy images for record")
    parser.add_argument("--backend", choices=["openai", "gemini"], default="gemini", help="LLM provider")

    args = parser.parse_args()
    main(args)
