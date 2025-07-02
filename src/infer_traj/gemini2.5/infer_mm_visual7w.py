from google import genai
from google.genai import types
import yaml
import json
from PIL import Image
import time
import os
from tqdm import tqdm
import random

random.seed(42)

# Load selected tool data from prompt yaml file
def load_tool_data(conf):
    active_tool_names = conf.get("available_tools", [])
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

def main():
    client = genai.Client(api_key="AIzaSyBhhjYp_VcfIfu2Fi7rqEcy8I0CbuNVONc")
    model_name = "gemini-2.5-flash-preview-05-20"

    config_file = "prompt.yaml"
    with open(config_file, "r") as stream:
        conf = yaml.safe_load(stream)

    active_tool_names, filtered_metadata_dict = load_tool_data(conf)
    tool_reasoning_system_instructions = conf.get("system_prompt_template_4_multi").format(
        available_tools=active_tool_names,
        toolbox_metadata=filtered_metadata_dict
    )
    print(f"tool_reasoning_system_instructions:\n{tool_reasoning_system_instructions}")

    dataset_prefix = "/nfs/data8/liao/wxie/datasets/mm_visual7w"
    dataset_path = "mm_visual7w.json"
    full_path = os.path.join(dataset_prefix, dataset_path)
    
    with open(full_path, "r") as f:
        raw_dataset = json.load(f)

    # Load intermediate results if available
    progress_file = "infer_mm_visual7w_progress.json"
    if os.path.exists(progress_file):
        with open(progress_file, "r", encoding="utf-8") as f:
            json_results = json.load(f)
        done_idx = set(entry["idx"] for entry in json_results)
        print(f"Found {len(done_idx)} completed samples. Resuming from the remaining samples.")
    else:
        json_results = []
        done_idx = set()

    for sample in tqdm(raw_dataset[:1000], desc="Inferring Question Samples"):
        idx = sample["imageId"]
        if idx in done_idx:
            continue

        print(f"Processing image: {sample['image_path']}")
        image_path = os.path.join(dataset_prefix, sample["image_path"])
        images = [Image.open(image_path)]

        qa_dict = {"question": [], "answer": []}
        i = 0
        qa_data = sample["qa_data"]
        while i < len(qa_data):
            entry = qa_data[i]
            if entry["role"] == "user" and entry["modality"] == "text":
                question = entry["data"]
                if i + 1 < len(qa_data):
                    answer_entry = qa_data[i + 1]
                    if answer_entry["role"] == "assistant" and answer_entry["modality"] == "text":
                        answer = answer_entry["data"]
                        qa_dict["question"].append(question)
                        qa_dict["answer"].append(answer)
                i += 2
            else:
                i += 1

        try:
            prompt = conf.get("prompt_tamplate_4_multi").format(question=qa_dict["question"])
            contents = [prompt] + images

            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=tool_reasoning_system_instructions,
                    temperature=0.1,
                )
            )

            result_dict = {
                "idx": idx,
                "source": os.path.basename(dataset_prefix),
                "question": qa_dict["question"],
                "image_paths": [image_path],
                "answer": qa_dict["answer"],
                "response": response.text,
            }

        except Exception as e:
            print(f"Error on sample {idx}: {e}")
            result_dict = {
                "idx": idx,
                "source": os.path.basename(dataset_prefix),
                "question": qa_dict["question"],
                "image_paths": [image_path],
                "answer": qa_dict["answer"],
                "response": "error",
                "error_msg": str(e),
            }

        json_results.append(result_dict)

        # Save intermediate progress
        with open(progress_file, "w", encoding="utf-8") as f:
            json.dump(json_results, f, indent=2, ensure_ascii=False)

        time.sleep(random.uniform(0.1, 0.5))  # Avoid rate limiting

        print(f"response: {result_dict['response']}")

    # Calculate statistics
    spatial_count = sum(
        "spatial reasoning question" in entry["response"].lower()
        for entry in json_results if entry.get("response")
    )
    general_count = sum(
        "general question" in entry["response"].lower()
        for entry in json_results if entry.get("response")
    )
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

    with open("mm_visual7w.json", "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)

    print("All samples processed! Final results saved to infer_mm_visual7w_final.json")

if __name__ == "__main__":
    main()
