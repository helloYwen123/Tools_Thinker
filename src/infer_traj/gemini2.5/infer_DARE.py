from google import genai
from google.genai import types
import yaml
import json
from PIL import Image
import time
import io
import os
import requests
from io import BytesIO
from tqdm import tqdm
import random
# load selected tooldata from prompt yaml file        
def load_tool_data(conf):
    # --- Tool Metadata Filtering Logic ---
    active_tool_names = conf.get("available_tools", []) # Get the list from YAML
    full_toolbox_metadata = conf.get("toolbox_metadata", {})

    # Create a dictionary containing only the metadata for active tools
    filtered_metadata_dict = {
        tool_name: full_toolbox_metadata[tool_name]
        for tool_name in active_tool_names
        if tool_name in full_toolbox_metadata
    }

    # Warn for missing tools
    for tool_name in active_tool_names:
        if tool_name not in full_toolbox_metadata:
            print(f"Warning: Tool '{tool_name}' listed in available_tools but not found in toolbox_metadata.")

    return active_tool_names, filtered_metadata_dict


def main():
    client = genai.Client(api_key="AIzaSyBhhjYp_VcfIfu2Fi7rqEcy8I0CbuNVONc")
    model_name = "gemini-2.5-flash-preview-05-20"

    # prompts preparation: general prompt file(yaml)
    confiuration_file = "prompt.yaml"

    with open(confiuration_file, "r") as stream:
            conf = yaml.safe_load(stream)
    active_tool_names, filtered_metadata_dict = load_tool_data(conf)
    
    tool_reasoning_system_instructions = conf.get("system_prompt_template").format(available_tools = active_tool_names, toolbox_metadata = filtered_metadata_dict)
    print(f"tool_reasoning_system_instructions: \n{tool_reasoning_system_instructions}")
    # set threshold for safty response
    safety_settings = [
        types.SafetySetting(
            category="HARM_CATEGORY_DANGEROUS_CONTENT",
            threshold="BLOCK_ONLY_HIGH",
        ),
    ]
    dataset_prefix = "/nfs/data8/liao/wxie/datasets/DARE" # "/home/stud/wxie/SAT/"  # "/nfs/data8/liao/wxie/SAT/"  # "/home/stud/wxie/"
    dataset_path = "DARE.json" # "SAT_subtasks/SAT_Counting.json" BLINK_Dataset/Counting/val/Counting_val.json
    full_path = os.path.join(dataset_prefix, dataset_path)
    
    with open(full_path, 'r') as f:
        raw_dataset = json.load(f)

    json_results = []
    SHOW_PROMPT = True
    for sample in tqdm(raw_dataset[:], desc="Inferring Question Samples"):
        
        print(f"iamge_path: {sample['image_path']}")
        image_paths = []
        image_paths = [os.path.join(dataset_prefix, sample["image_path"]) ]
        # image_paths = ["/home/stud/wxie/BLINK_Dataset/Art_Style/val/images/val_Art_Style_1_image_1.jpg", "/home/stud/wxie/BLINK_Dataset/Art_Style/val/images/val_Art_Style_1_image_2.jpg"]
        images = [Image.open(path) for path in image_paths]
        idx = sample["idx"]
        answer = sample["answer"][0]
        question = sample["question"] + f"\nA:{sample['A']}" + f"\nB:{sample['B']}" + f"\nC:{sample['C']}" + f"\nD:{sample['D']}"
        prompt = conf.get("prompt_tamplate").format(question = question)
        # prompt = "please describe the two images briefly, e.g first image: <image1 description>, second image: <image2 description>. "
        contents = [prompt] + images

        time.sleep(random.uniform(0.5, 1.0)) # Avoid rate limiting
        
        # Run model
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config = types.GenerateContentConfig(
                system_instruction=tool_reasoning_system_instructions,
                temperature=0.1,
                safety_settings=safety_settings,
            )
        )

        
        print(f"response: {response.text}")
        result_dict = {
        "idx": idx,
        "source": os.path.basename(dataset_prefix),
        "question": question,
        "image_paths": image_paths,
        "answer": answer,
        "response": response.text,
        }
        json_results.append(result_dict)

        
    spatial_count = 0
    general_count = 0

    for entry in json_results:
        response = entry.get("response", None)
        if response is not None:
            response = response.lower().strip()
            if "spatial reasoning question" in response:
                spatial_count += 1
            elif "general question" in response:
                general_count += 1

    total_count = len(json_results)
    spatial_ratio = (spatial_count / total_count) * 100 if total_count else 0
    general_ratio = (general_count / total_count) * 100 if total_count else 0

    # Prepare statistics
    stats = {
        "spatial_count": spatial_count,
        "general_count": general_count,
        "total_count": total_count,
        "spatial_ratio": round(spatial_ratio, 2),
        "general_ratio": round(general_ratio, 2)
    }

    # output the statistics
    final_output = {
        "stats": stats,
        "data": json_results
    }
    with open("DARE.json", "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
    
if __name__ == "__main__":
    API_KEY = "AIzaSyBhhjYp_VcfIfu2Fi7rqEcy8I0CbuNVONc"
    client = genai.Client(api_key= API_KEY)
    main()
