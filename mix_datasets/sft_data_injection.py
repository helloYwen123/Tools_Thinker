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
from typing import Dict, Any
import openai
from tqdm import tqdm
import yaml
import base64
import shutil
import random
from pathlib import Path


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
You are an expert teacher tasked with creating ONE visual question-answer pair for your student's coding exam.

The core task must involve **spatial visual reasoning** (in 2D or 3D), such as object detection and localization, image segmentation, spatial relationship reasoning, layout analysis, text region detection, depth estimation, or visual similarity comparison.

The student will solve the task **by writing Python code** using a specified visual reasoning API tool. Assume the student is already familiar with how to use this tool based on its metadata.

GOAL:
- Design a realistic, exam-style visual problem that can be **fully solved using the provided image(s) and prompt(s)** with the tool.
- The question must sound natural and plausible — do NOT mention tool names, APIs, or implementation details.
- If the question refers to specific objects (like people or items), you **must include their locations in the image** (e.g., bounding box or point coordinates) in the <question> section so that students can identify them.

Output STRICTLY in the following XML-like format (no additional commentary or explanations!):
<question> ... </question>
<answer>
<think>
Reason for approach: <explain why this is a spatial reasoning task solvable by the tool>
Analysis: <explain how the tool uses the image and prompts to solve the problem>
</think>
<code>
Python code snippet that uses the tool correctly
Final output must be assigned to `final_result`
</code>
</answer>

Constraints:
* Use ONLY the available API tool described in the metadata.
* If a task type or topic is provided (e.g., "Question topic: occlusion reasoning"), you must design the question accordingly.
* The Python code MUST follow the syntax and calling conventions defined in the tool metadata.
* The final result must be stored in a variable named `final_result`.
* If the question involves tool outputs that are large arrays (e.g., segmentation masks or pixel-level data), treat them as **intermediate variables only**.
  - Do NOT assign such arrays directly to `final_result`.
  - Instead, comment out the return line and explain the restriction, for example:
    <code>
    # The mask array can only be used as an intermediate variable;
    # it is not allowed to be assigned directly to final_result, so this line is commented out:
    # final_result = masks[image_path]['mask']
    </code>
"""



USER_TPL = """
Please carefully review the following tool metadata:
{api_meta}

You are required to include the necessary visual prompts in the generated question.

Image path: {img_path}  
Question topic: {task_type}

Make sure to clearly specify in the **<question>** section:
- The image path
- One or more visual prompts (e.g., bounding boxes or point coordinates), depending on what the tool requires
- Any visual prompt (e.g., bounding boxes or points) used in the code MUST be explicitly mentioned in the <question> text.
- If the question refers to specific objects (like people or items), you must include their exact locations in the image (e.g., bounding box or point coordinates) in the question so the student can identify them.

In some tasks, multiple visual prompts may be useful — for example:
- Reasoning over multiple regions
- Comparing objects
- Analyzing spatial relationships  
You are encouraged to design such scenarios when appropriate.

Reminder:
- The answer code should be a complete script, including all necessary `tool_module` imports.
- DO NOT generate questions that expect large outputs such as segmentation masks, `.npy` arrays, or raw pixel-level matrices.
- Avoid printing or visualizing raw array data in the final result.
Remember: If the question refers to specific objects (e.g., people or items), their exact image locations **must be provided** in the question section (e.g., bounding box or point coordinates).
Please generate exactly one question–answer pair for the task type {task_type}, using `points` as visual prompts, and present it in the required format.
"""

# Seg
# However, you ARE allowed to use such outputs (e.g., masks) as **intermediate steps** to support spatial reasoning — such as:
# - "Shape comparison"
# - "Pixel counting"
# - "Overlap analysis"
# - "Object containment"
# ...and similar tasks.
# To encourage variety, you are encouraged to **occasionally** design tasks involving **multiple visual prompts** (e.g., two or more boxes or points), especially when solving problems related to:
# - multi-object reasoning or comparison,
# - spatial aggregation (e.g., total area or containment),
# - or higher-order spatial analysis.
# Depth
# However, you ARE allowed to use the estimated depth map (pixel-level) from the tool as an intermediate result to support more advanced reasoning tasks. 
# To ensure diversity, you are encouraged to design different types of depth-based reasoning tasks across generations. Do not always default to comparing depth between objects.
# Try to vary your task types by using one or more of the following strategies when appropriate:
# - Occlusion reasoning,
# - Depth-based object comparison (closer or farther),
# - Region extraction based on depth thresholds,
# - Analyzing spatial layout or ordering,
# - Estimating rough object size or distance-based clustering,
# - ...and similar tasks.
# Be creative in designing real-world spatial problems grounded in 3D geometry or perception, especially using indoor or outdoor images where depth matters.
    # "depth-based occlusion reasoning",
    # "depth-based region extraction",
    # "spatial layout analysis",
    # "depth-based object comparison (closer or farther)",
    # "depth-based object clustering"
# text
# "text_presence_check",
# "keyword_detection",
# "text_matching",
# "spatial_region_text_extraction",
# "line_or_column_detection",
# "id_or_code_extraction",
# "date_detection",

# You may use the estimated (yaw, pitch, roll, confidence) of one or more objects in the image to reason about their orientation in 3D space. Typical tasks include:
#     "Determining which object faces the camera",
#     "Identifying which object is tilted or rotated the most",
#     "Comparing the orientation of multiple objects",
#     "Detecting pose outliers",
#     "Filtering objects by confidence",
#     "Assessing mutual alignment or directional intent",
# Feel free to design tasks that involve bounding boxes and require spatial understanding through pose estimation.

def build_msgs(img_path, api_meta):
    # Prepare image content
    encoded_image, mime_type = encode_image_base64(img_path)
    task_types = [
    "Determining which object faces the camera",
    "Identifying which object is tilted or rotated the most",
    "Comparing the orientation of multiple objects",
    "Detecting pose outliers",
    "Filtering objects by confidence",
    "Assessing mutual alignment or directional intent",
    ]
    selected_task = random.choice(task_types)
    print(f"question type:{selected_task}")
    # Construct user message
    user_prompt = USER_TPL.format(
        api_meta=api_meta,
        img_path=img_path,
        task_type=selected_task
    )

    return [
        {"role": "system", "content": SYSTEM_TPL},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"}}
            ]
        }
    ]

def main(args):

    # client = openai.OpenAI(api_key="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")
    client = openai.OpenAI(api_key="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")
    conf = "prompt.yaml"
    with open(conf, "r") as stream:
        conf = yaml.safe_load(stream)

    data = load_json(args.data)
    random.seed(42)
    random.shuffle(data)
    data = data[350:400]

    active_tools, filtered_meta = load_tool_data(conf)
    active_tools = ",".join(active_tools)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    Path(args.image_out_dir).mkdir(parents=True, exist_ok=True)
    with out_path.open("a+", encoding="utf-8") as fout:
        md_path = out_path.with_suffix(".md")
        for item in tqdm(data, desc="Generating QA"):
            img_path = "/workspace/ywen_ws/datasets/refcoco/images/" + item["file_name"] #  "/workspace/ywen_ws/datasets/refcoco/"
            prompts     = item["bbox"]

            # img_path = f"/workspace/ywen_ws/datasets/pointprompt/images/{os.path.splitext(os.path.basename(args.data))[0]}/image_00{item['image_index']}.png"
            # prompts = item["green_points"][0]

            # # text
            # img_path = item

            img_basename = os.path.basename(img_path)
            new_img_path = os.path.join(args.image_out_dir, img_basename)
            try:
                shutil.copy(img_path, new_img_path)
            except Exception as e:
                print(f"❌ Failed to copy image {img_path} to {new_img_path}: {e}")
                continue
            
            messages = build_msgs(new_img_path, filtered_meta)
            try:
                response = client.chat.completions.create(
                                model="gpt-4o",
                                messages=messages,
                                temperature=0.5,
                                max_tokens=640
                                )
            except Exception as e:
                print(f"⚠️ OpenAI API error on {img_path}: {e}")
                continue

            content = response.choices[0].message.content.strip()
            print(content)
            # <question> 与 <answer>
            if not re.search(r"<question>.*?</question>", content, re.S):
                print(f"Missing <question> tag, skip {img_path}")
                continue
            if not re.search(r"<answer>.*?</answer>", content, re.S):
                print(f"Missing <answer> tag, skip {img_path}")
                continue

            #
            qa_entry = {
                "image_path": new_img_path,
                "qa_pair": content
            }
            fout.write(json.dumps(qa_entry, ensure_ascii=False) + "\n")
            with md_path.open("a+", encoding="utf-8") as md_out:
                # extract <question> and <answer> 
                question_match = re.search(r"<question>(.*?)</question>", content, re.S)
                answer_match = re.search(r"<answer>(.*?)</answer>", content, re.S)
                if not question_match or not answer_match:
                    continue  # Skip if either part is missing

                question_text = question_match.group(1).strip()
                answer_text = answer_match.group(1).strip()

                # code snippets
                code_match = re.search(r"<code>(.*?)</code>", answer_text, re.S)
                code_text = code_match.group(1).strip() if code_match else ""

                # think
                think_match = re.search(r"<think>(.*?)</think>", answer_text, re.S)
                think_text = think_match.group(1).strip() if think_match else ""

                # markdown
                md_out.write(f"### Example for `{img_basename}`\n")
                md_out.write(f"**Question:**\n\n{question_text}\n\n")
                if think_text:
                    md_out.write(f"**Thinking:**\n\n{think_text}\n\n")
                if code_text:
                    md_out.write("**Code:**\n\n```python\n")
                    md_out.write(code_text)
                    md_out.write("\n```\n\n")
                md_out.write("\n---\n\n")
    print(f"Done! Saved to {out_path}")

# ---------------------------- CLI ----------------------------------
if __name__ == "__main__":
    # /workspace/ywen_ws/datasets/pointprompt/points_json/baseball_bat.json
    # /workspace/ywen_ws/datasets/refcoco/refcoco.json 
    # /workspace/ywen_ws/datasets/textOCR/image_list.json
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="JSON")
    # segmentor
    parser.add_argument("--out", default="/workspace/ywen_ws/datasets/single_tool_sft/segment_tool/segmenter_qa.jsonl", help="output JSON") 
    parser.add_argument("--image_out_dir", default="/workspace/ywen_ws/datasets/single_tool_sft/segment_tool/segment_imgs/", help="Directory to save copied QA images")
    # # depth estimator
    # parser.add_argument("--out", default="/workspace/ywen_ws/datasets/single_tool_sft/depth_tool/depth_estimator_qa2.jsonl", help="output JSON") # /workspace/ywen_ws/datasets/refcoco/refcoco.json 
    # parser.add_argument("--image_out_dir", default="/workspace/ywen_ws/datasets/single_tool_sft/depth_tool/depth_tool_imgs/", help="Directory to save copied QA images")
    # text detector
    # parser.add_argument("--out", default="/workspace/ywen_ws/datasets/single_tool_sft/text_tool/text_detector_qa.jsonl", help="output JSON") # /workspace/ywen_ws/datasets/refcoco/refcoco.json 
    # parser.add_argument("--image_out_dir", default="/workspace/ywen_ws/datasets/single_tool_sft/text_tool/text_detector_imgs/", help="Directory to save copied QA images")
    args = parser.parse_args()
    main(args)
