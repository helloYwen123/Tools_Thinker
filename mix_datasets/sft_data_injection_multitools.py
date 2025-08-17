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
import random,time
from pathlib import Path
from PIL import Image
from google import genai
from google.genai import types
import io, math

MAX_SIDE = 1024     
IMG_FMT  = "JPEG"    
IMG_QUAL = 80

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
    压缩图片到指定最大边长, 并保存到output_path。
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

def compress_image(
        img: Image.Image,
        max_side: int = 1024,
        fmt: str = "JPEG",
        quality: int = 80
    ) -> Image.Image:

    # ① 等比缩放
    w, h = img.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w*scale), int(h*scale)), Image.LANCZOS)

    # ② 如目标是 JPEG，但图片带 alpha，则转为 RGB
    if fmt.upper() == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")

    # ③ 重新编码到内存
    buf = io.BytesIO()
    save_kwargs = dict(quality=quality, optimize=True) if fmt.upper() == "JPEG" else {}
    img.save(buf, format=fmt, **save_kwargs)
    buf.seek(0)
    return Image.open(buf)


# # object detection and localization, image segmentation, spatial relationship reasoning, layout analysis, text region detection, depth estimation, or visual similarity comparison.
SYSTEM_TPL = """
You are an expert teacher tasked with creating ONE exam-style spatial reasoning question that requires the student to use **at least TWO different API tools from the toolbox in combination** to solve it.

Each question must:
- Be based on a realistic, 2D or 3D spatial visual reasoning scenario.
- Require the student to combine the outputs of at least two different tools in a sequence or chain (tool chaining).
- NOT mention tool names, APIs, or implementation details in the question text itself (it should sound natural).

**Output strictly in this XML-like format:**
<question> ... </question>
<answer>
<think>
Reason for approach: <explain why the question regards a spatial question and  why solving the task requires more than one tool>
Analysis: <explain how the tools are combined to solve the task, step by step>
</think>
<code>
Python code that correctly calls the tools in the required sequence,
using only the calling conventions in the toolbox metadata,
with all necessary imports.
Assign the final answer to `final_result`.
</code>
</answer>

Constraints:
- You may ONLY use tools from the provided toolbox (see metadata).
- Each question **MUST** require at least two different tools in combination.
- If any tool's output is a large array (e.g., segmentation mask), use it only as an intermediate variable.
- The code must be self-contained, following the metadata's syntax.
"""



USER_TPL = """
Please carefully review the following tool metadata(JSON):
{api_meta}

You are required to include the necessary visual prompts in the generated question.

Image path: {img_path}  

Make sure to clearly specify the image path in the **<question>** section:

Please follow these guidelines when generating the question:
- The question must require combining {tools_type} from the toolbox; it should not be solvable using fewer tools.
- You may use the outputs from the tools as intermediate results to support higher-level reasoning tasks.
- The question should only ask for one property or answer (do not combine independent sub-questions).
- Do not include solution steps or explicit instructions in the question.
- Whenever possible, use interpreted, scenario-based, or abstracted properties in the question (e.g., "Is the car facing left or right?") instead of raw numeric values.

Reminder in Code:
- The answer code should be a complete script, including all necessary `tool_module` imports.
- DO NOT generate questions that expect large outputs such as segmentation masks, `.npy` arrays, or raw pixel-level matrices.
- Avoid printing or visualizing raw array data in the final result.

Please generate exactly one question-answer pair that relates to the task type: {task_type} and requires using the following tools in combination: {tools_type} . 
Present your output strictly in the required XML-like format.
"""

def build_msgs(img_path, api_meta):
    # Prepare image content
    encoded_image, mime_type = encode_image_base64(img_path)
    tools_types = [
                    # "Orientation Estimator, Object Detector",
                    # "Orientation Estimator, Object Detector, Depth Estimator",
                    # "Orientation Estimator, Object Detector, Segmenter",
                    "Orientation Estimator, Object Detector, Depth Estimator, Segmenter",
                    "Object Detector, Depth Estimator",
                    "Object Detector, Segmenter",
                    "Object Detector, Depth Estimator, Segmenter"
                    ]

    tools_task_types = {
        "Orientation Estimator, Object Detector": [
            "Facing Direction Judgment",
            "Maximum/Minimum Rotation Identification",
            "Specific Orientation Classification",
            "Multi-object Orientation Comparison",
            "Orientation Outlier Detection",
            "Orientation-based Object Filtering",
            "Target Attribute Combined with Orientation"
        ],
        "Orientation Estimator, Object Detector, Depth Estimator": [
            "Object Facing Direction with Depth Comparison",
            "Which object is facing the camera and is also closest/farthest to the camera?",
            "Is the most upright object also the closest to the camera?",
            "Compare objects by both their tilt and distance",
            "Orientation Outlier among objects at similar depths"
        ],
        "Orientation Estimator, Object Detector, Segmenter": [
            "Orientation Judgment within Segmented Regions",
            "Which segmented object is most upright?",
            "Is the largest segmented object facing left or right?",
            "Compare tilt of segmented vs. detected objects",
            "Orientation-based Filtering within Segmented Objects"
        ],
        "Orientation Estimator, Object Detector, Depth Estimator, Segmenter": [
            "Which segmented object is most upright and closest to the camera?",
            "Orientation-depth combined outlier detection",
            "Among segmented objects, which is both facing left and is farthest?",
            "Segmented region tilt and distance analysis",
            "Is the object with largest roll angle also the nearest segmented object?"
        ],
        "Object Detector, Depth Estimator": [
            "Object Depth Comparison",
            "Depth-based Object Ranking",
            "Depth-based Object Filtering",
            "Object Distance Judgement",
        ],
        "Object Detector, Segmenter": [
            "Which detected object has the largest segmented area?",
        ],
        "Orientation Estimator, Object Detector": [
            "Depth-based Segmentation Comparison",
        ],
    }
    selected_tools = random.choice(tools_types)
    selected_task = random.choice(tools_task_types[selected_tools])
    print(f"question type:{selected_task}\n {selected_tools}")

    # Construct user message
    user_prompt = USER_TPL.format(
        api_meta=api_meta,
        img_path=img_path,
        task_type=selected_task,
        tools_type = selected_tools,
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
    # client = openai.OpenAI(api_key="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")
    client = genai.Client(api_key="AIzaSyBhhjYp_VcfIfu2Fi7rqEcy8I0CbuNVONc")
    model_name = "gemini-2.5-flash" # gemini-2.5-flash
    conf = "prompt.yaml"
    with open(conf, "r") as stream:
        conf = yaml.safe_load(stream)

    data = load_json(args.data)
    random.seed(42)
    random.shuffle(data)
    data = data[136:148]

    active_tools, filtered_meta = load_tool_data(conf)
    active_tools = ",".join(active_tools)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    Path(args.image_out_dir).mkdir(parents=True, exist_ok=True)
    with out_path.open("a+", encoding="utf-8") as fout:
        md_path = out_path.with_suffix(".md")
        for item in tqdm(data, desc="Generating QA"):
            # img_path = "/workspace/ywen_ws/datasets/Spatial457/" + item["images"][0]
            img_path = item
            img_basename = os.path.basename(img_path)
            new_img_path = os.path.join(args.image_out_dir, img_basename)
            
            try:
                shutil.copy(img_path, new_img_path)
                # compress_image(new_img_path, new_img_path, max_size=512, quality=85)
            except Exception as e:
                print(f"❌ Failed to copy image {img_path} to {new_img_path}: {e}")
                continue
            filtered_meta = json.dumps(filtered_meta, indent=2)
            # messages = build_msgs(new_img_path, filtered_meta)
            try:
                # Open AI
                # response = client.chat.completions.create(
                #                 model="gpt-4o",
                #                 messages=messages,
                #                 temperature=0.5,
                #                 max_tokens=512
                #                 )
                #######################################
                # Gemini 
                tools_types = [
                    # "Orientation Estimator, Object Detector",
                    # "Orientation Estimator, Object Detector, Depth Estimator",
                    # "Orientation Estimator, Object Detector, Segmenter",
                    "Orientation Estimator, Object Detector, Depth Estimator, Segmenter",
                    "Object Detector, Depth Estimator",
                    "Object Detector, Segmenter",
                    "Object Detector, Depth Estimator, Segmenter",
                ]

                tools_task_types = {
                    "Orientation Estimator, Object Detector": [
                        "Facing Direction Judgment",
                        "Maximum/Minimum Rotation Identification",
                        "Specific Orientation Classification",
                        "Multi-object Orientation Comparison",
                        "Orientation Outlier Detection",
                        "Orientation-based Object Filtering",
                        "Target Attribute Combined with Orientation"
                    ],
                    "Orientation Estimator, Object Detector, Depth Estimator": [
                        "Object Facing Direction with Depth Comparison",
                        "Which object is facing the camera and is also closest/farthest to the camera?",
                        "Is the most upright object also the closest to the camera?",
                        "Compare objects by both their tilt and distance",
                        "Orientation Outlier among objects at similar depths"
                    ],
                    "Orientation Estimator, Object Detector, Segmenter": [
                        "Orientation Judgment within Segmented Regions",
                        "Which segmented object is most upright?",
                        "Is the largest segmented object facing left or right?",
                        "Compare tilt of segmented vs. detected objects",
                        "Orientation-based Filtering within Segmented Objects"
                    ],
                    "Orientation Estimator, Object Detector, Depth Estimator, Segmenter": [
                        "Which segmented object is most upright and closest to the camera?",
                        "Orientation-depth combined outlier detection",
                        "Among segmented objects, which is both facing left and is farthest?",
                        "Segmented region tilt and distance analysis",
                        "Is the object with largest roll angle also the nearest segmented object?"
                    ],
                    "Object Detector, Depth Estimator": [
                        "Object Depth Comparison",
                        "Depth-based Object Ranking",
                        "Depth-based Object Filtering",
                        "Object Distance Judgement",
                    ],
                    "Object Detector, Segmenter": [
                        "Which detected object has the largest segmented area?",

                    ],
                    "Object Detector, Depth Estimator, Segmenter": [
                        "Which object has the greatest area and is also closest to the camera?",
                        "Rank detected objects by depth and segmented area.",
                    ],
                }
                selected_tools = random.choice(tools_types)
                selected_task = random.choice(tools_task_types[selected_tools])
                print(f"question type:{selected_task}\n {tools_types[0]}")
                # Construct user message
                user_prompt = USER_TPL.format(
                    api_meta=filtered_meta,
                    img_path=new_img_path,
                    task_type=selected_task,
                    tools_type = selected_tools,
                )

                images = [compress_image(Image.open(img_path),
                         max_side=MAX_SIDE,
                         fmt=IMG_FMT,
                         quality=IMG_QUAL)]
                         
                # images = [Image.open(img_path)]
                
                contents = [user_prompt] + images
                safety_settings = [
                types.SafetySetting(
                    category="HARM_CATEGORY_DANGEROUS_CONTENT",
                    threshold="BLOCK_ONLY_HIGH",
                        )
                    ]
                time.sleep(random.uniform(8, 10))
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_TPL,
                        temperature=0.4,
                        # maxOutputTokens=800,
                        safety_settings=safety_settings,
                    ),
                )
            except Exception as e:
                print(f"⚠️ API error on {img_path}: {e}")
                time.sleep(60)
                continue
            
            # GPT
            # content = response.choices[0].message.content.strip()

            # Gemini-2.5
            content = response.text
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
    # /workspace/ywen_ws/datasets/Spatial457/questions_sat/L4_pose_mcq.json
    # /workspace/ywen_ws/datasets/SUNRGB-D/random_kv2_200_image_list.json

    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="JSON")
    # multi_tools
    parser.add_argument("--out", default="/workspace/ywen_ws/datasets/single_tool_sft/multi_tools/multi_tools_qa.jsonl", help="output JSON") 
    parser.add_argument("--image_out_dir", default="/workspace/ywen_ws/datasets/single_tool_sft/multi_tools/multi_tools_imgs/", help="Directory to save copied QA images")
    # multi_tools +orientation estimator
    # parser.add_argument("--out", default="/workspace/ywen_ws/datasets/single_tool_sft/multi_tools_orientation/multi_orientation_qa.jsonl", help="output JSON") 
    # parser.add_argument("--image_out_dir", default="/workspace/ywen_ws/datasets/single_tool_sft/multi_tools_orientation/multi_orientation_imgs/", help="Directory to save copied QA images")
    args = parser.parse_args()
    main(args)
