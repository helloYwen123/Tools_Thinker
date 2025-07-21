# SOTA Grounding DINO Object Detection Tool: Gounding-DINO 1.5 pro
# https://github.com/IDEA-Research/Grounding-DINO-1.5-API

import argparse
import os
import sys
from PIL import Image, ImageOps
import numpy as np
from collections import defaultdict
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, root_dir)
from basetool import BaseTool
import json
from dds_cloudapi_sdk import Config, Client
from dds_cloudapi_sdk.tasks.v2_task import V2Task

class Advanced_Object_Detector_Tool(BaseTool):
    def __init__(self):
        super().__init__(
            tool_module_name="advanced_object_detector",
            tool_class_name="Advanced_Object_Detector_Tool",
            tool_description=(
            "Advanced Object detector performs better than Object Detector. "
            "Supports single or multiple category prompts with optional cropping of detected objects."
            ),
            tool_version="1.0.0",
            input_types={
            "image": "str: Path to the input image file.",
            "labels": "List of object categories to detect, e.g., ['person', 'tree']",
            "threshold": "Detection score threshold. Only objects above this score will be returned.",
            "save_object": "Whether to save cropped images of detected objects (bool).",
            "saved_image_path": "Directory to save cropped object images if `save_object` is True.",
            "save_json": "bool - Whether to save detection results as a JSON file (default: False).",
            "json_path": "str - The file path to save the JSON results if save_json is True (default: 'detection_results.json')."
            
            },
            output_types={
            "results": ("a dict mapping each label to a list of detection results (each with box, confidence score, and optionally saved image path).",
                        "e.g., {'person': [{'box': (x1, y1, x2, y2), 'score': 0.95, 'saved_path': 'path/to/saved/image.png'}]}")
            },
            demo_commands=[{
                "command": """
                advanced_object_detector_tool = Advanced_Object_Detector_Tool()
                result= advanced_object_detector_tool.execute(image='path/to/demo', labels=['person', 'bicycle'], threshold=0.4, save_object=False, save_json=False)
                """,
                "description": "Detect 'person' and 'bicycle' in the image return dictionary with key `label` :  bounding boxes and confidence score.",
                "output_example": """
                "results" :  {'person': [{'box': (50, 30, 200, 400), 'score': 0.92, 'saved_path': None}],
                            'bicycle': [{'box': (400, 200, 550, 420), 'score': 0.85, 'saved_path': None}]}"""}],
            user_metadata={
               "potential usage": (
                    "The bounding box and masks can be used to determine precise object regions and pixel-level coordinates, enabling integration "
                    "with downstream tasks such as depth estimation, instance segmentation, or regions localization for sparse matching."
                )
            }
        )
        # self.DINO_KEY = os.environ.get("DINO_KEY") # Replace with your actual API key
        self.DINO_KEY = ""
        self.client = Client(Config(self.DINO_KEY))
        self.output_dir = None

    def save_detected_object(self, image, box, image_name, label, index, padding=20):
        """
        Save the detected object as an image with padding.
        """
        object_image = image.crop(box)
        padded_image = ImageOps.expand(object_image, border=padding, fill='white')

        filename = f"{image_name}_{label}_{index}.png"
        os.makedirs(self.output_dir, exist_ok=True)
        save_path = os.path.join(self.output_dir, filename)
        padded_image.save(save_path)
        return save_path


    def execute(self, image, labels, threshold=0.45, save_object=False, saved_image_path="detected_objects", save_json=False, json_path="./detected_objects/detection_results.json"):
        """
        """
        if save_object:
            self.output_dir = saved_image_path
            image_pil = Image.open(image)
            image_name = os.path.splitext(os.path.basename(image))[0]
            
        infer_image_url = self.client.upload_file(image)
        prompt_str = ".".join(labels)

        task = V2Task(api_path="/v2/task/grounding_dino/detection", api_body={
        "model": "GroundingDino-1.5-Pro",
        "image": infer_image_url,
        "prompt": {
            "type": "text",
            "text": prompt_str
        },
        "targets": ["bbox"],
        "bbox_threshold": threshold,
        "iou_threshold": 0.5
        })
        task.set_request_timeout(10)

        self.client.run_task(task)
        # print(f"{task.result}")
        objects = task.result.get("objects", [])

        grouped = defaultdict(list)
        object_counts = {}

        # Process the results
        for obj in objects:
            score = obj.get("score", 0)
            if score < threshold:
                continue

            category = obj.get("category", "unknown")
            bbox = obj.get("bbox", [])
            box = tuple(map(int, bbox))

            entry = {
            "box": box,
            "score": score,
            "saved_path": None
            }

            # Count the number of objects per category
            object_counts[category] = object_counts.get(category, 0) + 1
            index = object_counts[category]

            if save_object:
                saved_path = self.save_detected_object(image_pil, box, image_name, category, index)
                entry["saved_path"] = saved_path
            
            grouped[category].append(entry)

        if save_json:
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            grouped_results_for_json = {
                label: [
                    {
                        "box": list(obj["box"]),
                        "score": obj["score"],
                        "saved_image_path": obj["saved_path"]
                    } for obj in objs
                ] for label, objs in grouped.items()
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(grouped_results_for_json, f, ensure_ascii=False, indent=2)

        return dict(grouped)

    def get_metadata(self):
        metadata = super().get_metadata()
        return metadata

if __name__ == "__main__":
    tool = Advanced_Object_Detector_Tool()
    metadata = tool.get_metadata()

    image_path = './asset/01.png'
    labels = ['bird']
    results = tool.execute(image=image_path, labels=labels, threshold=0.30, save_object=True, save_json=True)

    results_dict= results
    for label, entries in results_dict.items():
        print(f"Label: {label}")
        for i, entry in enumerate(entries):
            print(f"  Detection {i + 1}:")
            print(f"    Confidence: {entry['score']}")
            print(f"    Bounding box: {entry['box']}")
            print(f"    Saved image path: {entry.get('saved_path', 'N/A')}")
        # print(f"  Total detections for {label}: {object_counts[label]}")

    # Save overlay visualizations
    # Save structured results to JSON (as string, quick version)
    # with open('./asset/demo_output.json', 'w') as f:
    #     f.write(str(results_dict))
    #     print("Saved raw result dict to ./asset/demo_output.json")
# 1. Initialize the client with your API token.
# from dds_cloudapi_sdk import Config
# from dds_cloudapi_sdk import Client

# token = "5cf9118fa07590654271566b4599070f"
# config = Config(token)
# client = Client(config)

# # 2. Upload local image to the server and get the URL.
# # infer_image_url = "https://dds-frontend.oss-accelerate.aliyuncs.com/static_files/playground/grounding_DINO-1.6/02.jpg"
# infer_image_url = client.upload_file("./asset/AB.png")  # you can also upload local file for processing

# # 3. Create a task with proper parameters.
# from dds_cloudapi_sdk.tasks.v2_task import V2Task

# task = V2Task(api_path="/v2/task/dinox/detection", api_body={
#     "model": "DINO-X-1.0",
#     "image": infer_image_url,
#     "prompt": {
#         "type":"text",
#         "text":"woman"
#     },
#     "targets": ["bbox"],
#     "bbox_threshold": 0.25,
#     "iou_threshold": 0.8
# })
# # task.set_request_timeout(10)  # set the request timeout in seconds，default is 5 seconds

# # 4. Run the task.
# client.run_task(task)

# # 5. Get the result.
# print(task.result)
