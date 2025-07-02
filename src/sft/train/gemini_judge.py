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



def main():
    client = genai.Client(api_key="AIzaSyBhhjYp_VcfIfu2Fi7rqEcy8I0CbuNVONc")
    model_name = "gemini-2.5-flash-preview-05-20"

    # prompts preparation: general prompt file(yaml)
    confiuration_file = "prompt.yaml"

    with open(confiuration_file, "r") as stream:
            conf = yaml.safe_load(stream)
    
    tool_reasoning_system_instructions = conf.get("system_prompt_template")
    print(f"tool_reasoning_system_instructions: \n{tool_reasoning_system_instructions}")
    
    # set threshold for safty response
    safety_settings = [
        types.SafetySetting(
            category="HARM_CATEGORY_DANGEROUS_CONTENT",
            threshold="BLOCK_ONLY_HIGH",
        ),
    ]
    
    def load_jsonl(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)
                    
    jsonl_path = "conversations.jsonl"
    for sample in tqdm(load_jsonl(jsonl_path), desc="Inferring Question Samples"):
        
        print(f"iamge_path: {sample['image_path']}")
        image_paths = []
        # image_paths = ["/home/stud/wxie/BLINK_Dataset/Art_Style/val/images/val_Art_Style_1_image_1.jpg", "/home/stud/wxie/BLINK_Dataset/Art_Style/val/images/val_Art_Style_1_image_2.jpg"]
        images = [Image.open(path) for path in image_paths]
        idx = sample["idx"]
        answer = 
        question = 
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
                temperature=0.3,
                safety_settings=safety_settings,
            )
        )

        
        print(f"response: {response.text}")
        result_dict = {
        "idx": idx,
        "question": question,
        "image_paths": image_paths,
        "answer": answer,
        "response": response.text,
        }
        json_results.append(result_dict)

        


    # output the statistics
    final_output = {
    }
    with open("DARE.json", "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
    
if __name__ == "__main__":
    API_KEY = "AIzaSyBhhjYp_VcfIfu2Fi7rqEcy8I0CbuNVONc"
    client = genai.Client(api_key= API_KEY)
    main()
