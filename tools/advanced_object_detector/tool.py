# SOTA Grounding DINO Object Detection Tool: Gounding-DINO 1.5 pro
# https://github.com/IDEA-Research/Grounding-DINO-1.5-API

import argparse
import os
import sys
from gdino import GroundingDINOAPIWrapper, visualize
from PIL import Image, ImageOps
import numpy as np
from collections import defaultdict
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, root_dir)
from basetool import BaseTool

class Advanced_Object_Detector(BaseTool):
    def __init__(self):
        super().__init__(
            tool_module_name="advanced_object_detector",
            tool_class_name="Advanced_Object_Detector",
            tool_description=(
            "Object detection tool using Grounding DINO 1.5 Pro. "
            "Supports single or multiple category prompts with optional cropping of detected objects."
            ),  
            tool_version="1.0.0",
            input_types={
            "image": "str: Path to the input image file.",
            "labels": "List of object categories to detect, e.g., ['person', 'tree']",
            "threshold": "Detection score threshold. Only objects above this score will be returned.",
            "save_object": "Whether to save cropped images of detected objects (bool).",
            "saved_image_path": "Directory to save cropped object images if `save_object` is True.",
            "mask": "Whether to return segmentation masks (binary mask: 255 inside object regions, 0 elsewhere) for each detected object (bool)."
            },
            output_types={
            "results": "A dictionary grouped by label, each containing list of detection entries with box, score, and optional mask/saved image path.",
            "object_counts": "A dictionary with count of detected objects for each label."
            },
            demo_commands=[{
                "command": "result, object_counts = tool.execute(image='demo.jpg', labels=['person', 'bicycle'], threshold=0.4, save_object=False, mask=True)",
                "description": "Detect 'person' and 'bicycle' in the image with bounding boxes and pixel-level segmentation masks.",
                "output_example": """
                results :  {'person': [{'box': (50, 30, 200, 400), 'score': 0.92, 'mask': '<numpy array representing mask>', 'saved_path': None}],
                            'bicycle': [{'box': (400, 200, 550, 420), 'score': 0.85, 'mask': '<numpy array representing mask>', 'saved_path': None}]}
                object_counts : {'person': 2, 'bicycle': 1}"""}],
            user_metadata={
               "potential usage": (
                    "The masks can be used to determine precise object regions and pixel-level coordinates, enabling integration "
                    "with downstream tasks such as depth estimation, instance segmentation, or semantic feature encoding. "
                )
            }  
        )
        self.DINO_KEY = os.environ.get("DINO_KEY") # Replace with your actual API key
    
    def save_detected_object(self, image, box, image_name, label, index, padding):
        object_image = image.crop(box)
        padded_image = ImageOps.expand(object_image, border=padding, fill='white')
        
        filename = f"{image_name}_{label}_{index}.png"
        os.makedirs(self.output_dir, exist_ok=True)
        save_path = os.path.join(self.output_dir, filename)
        
        padded_image.save(save_path)
        return save_path
    
    
    def execute(self, image, labels, threshold=0.45, save_object=False, saved_image_path="detected_objects", mask=False):
            padding = 20 # default padding
            
            self.DINO_KEY = "5cf9118fa07590654271566b4599070f" ## Replace with your actual API key
            gdino = GroundingDINOAPIWrapper(self.DINO_KEY)
            prompt_str = " . ".join(labels)
            
            prompts = dict(image=image, prompt=prompt_str)
            
            results = gdino.inference(prompts, return_mask= mask)
            
            if save_object:
                # Create the directory to save detected objects
                image_path = prompts['image']
                image = Image.open(image_path).convert("RGB")
                image_name = os.path.splitext(os.path.basename(image_path))[0]
                self.output_dir = saved_image_path
            
            grouped = defaultdict(list)
            object_counts = {}
            has_mask = bool(results.get("masks"))
            for box, category, score, *mask in zip(
                results["boxes"],
                results["categorys"],
                results["scores"],
                results["masks"] if has_mask else [None] * len(results["boxes"])
            ):  
                if score < threshold:  # optional filter
                    continue
                
                entry = {
                    "box": box,
                    "score": score,
                }
                
                if has_mask and mask[0] is not None:
                    alpha = mask[0].split()[-1]
                    alpha_array = np.array(alpha)  # binary mask
                    entry["mask"] = alpha_array
                    
                
                object_counts[category] = object_counts.get(category, 0) + 1
                index = object_counts[category]
                # Save the detected object image if requested
                entry["saved_path"] = None
                if save_object:
                    saved_path = self.save_detected_object(
                        image=image,
                        box=box,
                        image_name=image_name,
                        label=category,
                        index=index,
                        padding=padding
                    )
                    entry["saved_path"] = saved_path
                # Add the saved image path to the entry
                grouped[category].append(entry)
                
            results = dict(grouped)
            
            return results, object_counts
    
    def get_metadata(self):
        metadata = super().get_metadata()
        return metadata    
    
if __name__ == "__main__":

    # Use provided token or fallback to hardcoded (for testing)
    token = "5cf9118fa07590654271566b4599070f"
    
    tool = Advanced_Object_Detector()
    metadata = tool.get_metadata()
    
    image_path = './asset/AB.png'
    labels = ['woman']
    results = tool.execute(image=image_path, labels=labels, threshold=0.35, save_object=True, mask=True)
    
    results_dict, object_counts = results
    for label, entries in results_dict.items():
        print(f"Label: {label}")
        for i, entry in enumerate(entries):
            print(f"  Detection {i + 1}:")
            print(f"    Confidence: {entry['score']}")
            print(f"    Bounding box: {entry['box']}")
            print(f"    Saved image path: {entry.get('saved_path', 'N/A')}")
        print(f"  Total detections for {label}: {object_counts[label]}")


    # Save overlay visualizations
    # Save structured results to JSON (as string, quick version)
    with open('./asset/demo_output.json', 'w') as f:
        f.write(str(results_dict))
        print("Saved raw result dict to ./asset/demo_output.json")