from google import genai
from google.genai import types
import yaml
import json
from PIL import Image
import time
import os
from tqdm import tqdm

# Tool configuration
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

    configuration_file = "prompt.yaml"
    with open(configuration_file, "r") as stream:
        conf = yaml.safe_load(stream)

    active_tool_names, filtered_metadata_dict = load_tool_data(conf)
    tool_reasoning_system_instructions = conf.get("system_prompt_template").format(
        available_tools=active_tool_names,
        toolbox_metadata=filtered_metadata_dict
    )
    safety_settings = [
        types.SafetySetting(
            category="HARM_CATEGORY_DANGEROUS_CONTENT",
            threshold="BLOCK_ONLY_HIGH",
        ),
    ]

    dataset_prefix = "/nfs/data8/liao/wxie/datasets/GQA"
    dataset_path = "GQA.json"
    full_path = os.path.join(dataset_prefix, dataset_path)
    
    with open(full_path, "r") as f:
        raw_dataset = json.load(f)

    # Load previously saved intermediate results
    progress_file = "GQA_progress.json"
    if os.path.exists(progress_file):
        with open(progress_file, "r", encoding="utf-8") as f:
            json_results = json.load(f)
        done_idx = set(entry["idx"] for entry in json_results)
        print(f"Found {len(done_idx)} completed samples, continuing with remaining ones.")
    else:
        json_results = []
        done_idx = set()

    for sample in tqdm(raw_dataset[:1000], desc="Inferring Question Samples"):
        idx = sample["imageId"]
        if idx in done_idx:
            continue

        image_path = os.path.join(dataset_prefix, sample["image_path"])
        question = sample["question"]
        answer = sample["answer"]

        try:
            images = [Image.open(image_path)]
            prompt = conf.get("prompt_tamplate").format(question=question)
            contents = [prompt] + images

            time.sleep(1.0)  # Avoid rate limiting

            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=tool_reasoning_system_instructions,
                    temperature=0.1,
                    safety_settings=safety_settings,
                )
            )

            result_dict = {
                "idx": idx,
                "source": os.path.basename(dataset_prefix),
                "question": question,
                "image_paths": [image_path],
                "answer": answer,
                "response": response.text,
            }

        except Exception as e:
            print(f"Error on sample {idx}: {e}")
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

        # Save intermediate progress
        with open(progress_file, "w", encoding="utf-8") as f:
            json.dump(json_results, f, indent=2, ensure_ascii=False)

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

    with open("GQA.json", "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)

    print("Processing completed! Final results saved to GQA_final.json")

if __name__ == "__main__":
    main()
