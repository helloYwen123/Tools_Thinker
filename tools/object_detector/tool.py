# Grounding DINO Object Detection Tool
# https://huggingface.co/IDEA-Research/grounding-dino

import sys
import os
import time
import torch
from transformers import pipeline
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, root_dir)
from basetool import BaseTool
from PIL import Image, ImageOps
import json
import os
# If CUDA_HOME is set, print the value
# print(os.environ.get('CUDA_HOME', 'CUDA_HOME is not set'))

# Suppress stderr by redirecting it to /dev/null
import sys
# sys.stderr = open(os.devnull, 'w')

class Object_Detector_Tool(BaseTool):
    def __init__(self):
        super().__init__(
            tool_module_name="object_detector",
            tool_class_name="Object_Detector_Tool",
            tool_description="A tool that detects objects in an image, optionally saves individual object images and exports detection outputs as a JSON file.",
            input_types={
                "image": "str - The path to the image file.",
                "labels": "list[str] - A list of object labels to detect.",
                "save_object": "bool - Whether to save the detected objects as images (default: False).",
                "saved_image_path": "str - The path to save the detected object images (default: 'detected_objects').",
                "save_json": "bool - Whether to save detection results as a JSON file (default: False).",
                "json_path": "str - The file path to save the JSON results if `save_json` is True (default: 'detection_results.json')."
            },
            output_types = "dict - A dictionary mapping each detected label to a list of detection entries. \
            a dictionary mapping each detected label to a list of detection entries containing bounding boxes(xyxy format),confidence score, saved image path, and cropped object images in PIL)",
            demo_commands = [
                {
                    "command": """
                    object_detector_tool = Object_Detector_Tool()
                    detected_objects = object_detector_tool.execute(image="path/to/image", labels=["baseball", "basket"], save_object=True, saved_image_path="detected_objects", save_json=True, json_path="detected_objects/results.json")
                    """,
                    "description": (
                        "Detects 'baseball' and 'basket' in the image. Returns a dictionary mapping each detected label to a list of detection entries.: "
                        "(1) a dict mapping each label to a list of detection results (each with box, score, cropped object images, optionally saved image paths and json files)"
                        "If 'save_object' is True, detected objects are cropped and saved to the specified directory."
                        "If 'save_json' is True, detection results are saved as JSON to 'detected_objects/results.json'."
                    ),
                    "output_example": """
                        detected_objects: {
                        'baseball': [{'box': (34, 50, 200, 220), 'score': float, 'saved_image_path': str}],
                        'basket': [{'box': (220, 100, 400, 350), 'score': float, 'saved_image_path': str}]
                        }
                    """
                }
            ],
            user_metadata={
                "potential usage": """
                The bounding box obtained by tool can be used to determine precise object regions and pixel-level coordinates, enabling integration
                with downstream tasks such as depth estimation, object segmentation, or regions localization for sparse matching.
                """
            }
        )

    def preprocess_caption(self, caption):
        result = caption.replace("_", " ").lower().strip()
        if result.endswith("."):
            return result
        return result + "."

    def build_tool(self, model_size='base'):
        model_name = f"IDEA-Research/grounding-dino-{model_size}"
        device = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            pipe = pipeline(model=model_name, task="zero-shot-object-detection", device=device)
            return pipe
        except Exception as e:
            raise RuntimeError(f"Failed to build GroundingDINO ({model_name}): {e}")

    def save_detected_object(self, image, box, image_name, label, index, padding):
        object_image = image.crop(box)
        padded_image = ImageOps.expand(object_image, border=padding, fill='white')
        
        filename = f"{image_name}_{label}_{index}.png"
        os.makedirs(self.output_dir, exist_ok=True)
        save_path = os.path.join(self.output_dir, filename)
        
        padded_image.save(save_path)
        return save_path

    def execute(
        self,
        image: str,
        labels: list[str],
        threshold: float = 0.35,
        model_size: str = "base",
        save_object: bool = False,
        saved_image_path: str = "./objects_images",
        save_json: bool = False,
        json_path: str = "./detection_results.json",
        padding: int = 20,
    ):
        # --------- 1. path and model check ----------
        if not os.path.exists(image):
            raise FileNotFoundError(f"Image not found: {image}")

        pipe = self.build_tool(model_size)
        self.output_dir = saved_image_path
        # --------- 2. inference ----------
        prep_labels = [self.preprocess_caption(lab) for lab in labels]
        results = pipe(image, candidate_labels=prep_labels, threshold=threshold)

        if not results:
            return {}

        # --------- 3. pre-processing ----------
        original_image = Image.open(image).convert("RGB")
        image_name = os.path.splitext(os.path.basename(image))[0]
        object_counts = {}
        grouped_results = {}

        for result in results:
            box = tuple(result["box"].values())  # (x1, y1, x2, y2)
            label = result["label"].rstrip(".")
            score = round(result["score"], 2)

            object_counts[label] = object_counts.get(label, 0) + 1
            index = object_counts[label]
                    
            save_path = None
            if save_object:
                save_path = self.save_detected_object(original_image, box, image_name, label, index, padding)
            
            if label not in grouped_results:
                grouped_results[label] = []
                
            grouped_results[label].append({
                "box": box,
                "score": score,
                "saved_image_path": save_path,
            })

        # --------- 4. writing JSON ----------
        # if save_json:
        #     os.makedirs(os.path.dirname(json_path), exist_ok=True)
        #     grouped_results_for_json = {
        #         label: [
        #             {
        #                 "box": list(obj["box"]),
        #                 "score": obj["score"],
        #                 "saved_image_path": obj["saved_image_path"]
        #             } for obj in objs
        #         ] for label, objs in grouped_results.items()
        #     }
        #     with open(json_path, "w", encoding="utf-8") as f:
        #         json.dump(grouped_results_for_json, f, ensure_ascii=False, indent=2)

        return grouped_results

    def get_metadata(self):
        metadata = super().get_metadata()
        return metadata

if __name__ == "__main__":
    # Test command:
    """
    Run the following commands in the terminal to test the script:
    
    cd octotools/tools/object_detector
    python tool.py
    """

    # Get the directory of the current script
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Example usage of the Object_Detector_Tool
    tool = Object_Detector_Tool()

    # Get tool metadata
    metadata = tool.get_metadata()
    # print(metadata)

    # Construct the full path to the image using the script's directory
    relative_image_path = "examples/baseball.png"
    image_path = os.path.join(script_dir, relative_image_path)
    image_path = "/home/stud/wxie/SAT/SAT_images_train/45_0.png"
    # Execute the tool
    try:
        detected_objects = tool.execute(image=image_path, labels=["painting"], save_object=True, save_json=False, saved_image_path="detected_objects",model_size='base')
        print("Detected Objects:")
        for key, value in detected_objects.items():
            print(f"key:{key}, num: {len(value)}\n")
            print(str(value))
    except ValueError as e: 
        print(f"Execution failed: {e}")

    print("Done!")