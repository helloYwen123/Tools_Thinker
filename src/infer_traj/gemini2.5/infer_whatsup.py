import os
import json
import random
import time
import yaml
from tqdm import tqdm
from PIL import Image
from io import BytesIO
from google import genai
from google.genai import types

random.seed(42)

def load_tool_data(conf):
    active_tool_names = conf.get("available_tools", [])
    full_toolbox_metadata = conf.get("toolbox_metadata", {})
    filtered_metadata_dict = {
        tool_name: full_toolbox_metadata[tool_name]
        for tool_name in active_tool_names
        if tool_name in full_toolbox_metadata
    }
    return active_tool_names, filtered_metadata_dict

def main():
    dataset_prefix = "/nfs/data8/liao/wxie/datasets/whatsup"
    dataset_path = "visual_genome_relation.json"
    full_path = os.path.join(dataset_prefix, dataset_path)

    with open(full_path, "r") as f:
        raw_dataset = json.load(f)

    confiuration_file = "prompt.yaml"
    with open(confiuration_file, "r") as stream:
        conf = yaml.safe_load(stream)
    active_tool_names, filtered_metadata_dict = load_tool_data(conf)
    system_instruction = conf.get("system_prompt_template").format(
        available_tools=active_tool_names, toolbox_metadata=filtered_metadata_dict
    )
    PREFIX_PROMPT = "Please determine whether the caption is true or false based on the image. If the caption is true, answer 'yes'. If the caption is false, answer 'no'."

    # load progress
    progress_file = "whatsup_progress.json"
    if os.path.exists(progress_file):
        with open(progress_file, "r", encoding="utf-8") as f:
            json_results = json.load(f)
        done_idx = set(entry["idx"] for entry in json_results)
        print(f"Have finished {len(done_idx)} samples, resuming from there...")
    else:
        json_results = []
        done_idx = set()

    # initialize client and model
    client = genai.Client(api_key="AIzaSyBhhjYp_VcfIfu2Fi7rqEcy8I0CbuNVONc")
    model_name = "gemini-2.5-flash-preview-05-20"

    for sample in tqdm(raw_dataset[:1000], desc="Inferring"):
        idx = sample["image_id"]
        if idx in done_idx:
            continue  # have already processed this sample
        print(f"Processing image: {sample['image_path']}")
        image_path = os.path.join(dataset_prefix, "images", sample["image_path"])
        try:
            images = [Image.open(image_path)]
            if random.random() < 0.5:
                question = PREFIX_PROMPT + f"\nCaption: {sample['true_caption']}"
                answer = "yes"
            else:
                question = PREFIX_PROMPT + f"\nCaption: {sample['false_caption']}"
                answer = "no"

            prompt = conf.get("prompt_tamplate").format(question=question)
            contents = [prompt] + images

            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.1,
                )
            )

            time.sleep(1.0)

            result_dict = {
                "idx": idx,
                "source": os.path.basename(dataset_prefix),
                "question": question,
                "image_paths": [image_path],
                "answer": answer,
                "response": response.text,
            }

        except Exception as e:
            print(f"sample {idx} error: {e}")
            result_dict = {
                "idx": idx,
                "source": os.path.basename(dataset_prefix),
                "question": question,
                "image_paths": [image_path],
                "answer": answer,
                "response": "error",
                "error_msg": str(e),
            }

        json_results.append(result_dict)

        # 每个样本跑完都保存进度！
        with open(progress_file, "w", encoding="utf-8") as f:
            json.dump(json_results, f, indent=2, ensure_ascii=False)

    # 统计
    spatial_count = sum("spatial reasoning question" in entry["response"].lower() for entry in json_results if entry.get("response"))
    general_count = sum("general question" in entry["response"].lower() for entry in json_results if entry.get("response"))
    total_count = len(json_results)
    spatial_ratio = round(spatial_count / total_count * 100, 2) if total_count else 0
    general_ratio = round(general_count / total_count * 100, 2) if total_count else 0

    stats = {
        "spatial_count": spatial_count,
        "general_count": general_count,
        "total_count": total_count,
        "spatial_ratio": spatial_ratio,
        "general_ratio": general_ratio
    }

    final_output = {
        "stats": stats,
        "data": json_results
    }
    with open("Whatsup.json", "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)

    print("✅ 所有样本处理完毕！最终结果保存在: Whatsup.json")

if __name__ == "__main__":
    main()
