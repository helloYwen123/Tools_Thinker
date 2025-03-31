# SOTA Grounding DINO Object Detection Tool: Gounding-DINO 1.5 pro
# https://github.com/IDEA-Research/Grounding-DINO-1.5-API

import argparse
import os
from gdino import GroundingDINOAPIWrapper, visualize
from PIL import Image, ImageOps
import numpy as np
from collections import defaultdict
from base import BaseTool

class Advanced_Object_Detector_Tool(BaseTool):
    def __init__(self):
        super().__init__(
            tool_module_name="advanced_object_detector_tool",
            tool_class_name="Advanced_Object_Detector_Tool",
            tool_description=(
            "Object detection tool using Grounding DINO. "
            "Supports single or multiple category prompts with optional cropping of detected objects."
            ),  
            tool_version="1.0.0",
            iinput_types={
            "image": "str - Path to the input image file.",
            "labels": "list - List of target object categories (e.g., ['person'], ['cat', 'dog']).",
            "threshold": "float - Confidence threshold for filtering detections (default: 0.45).",
            "save_object": "bool - If True, crops and saves detected objects (default: False).",
            "saved_image_path": "str - Directory to save cropped images (default: 'detected_objects').",
            },
            output_types=(
                "tuple - (results_dict, object_counts_dict):\n"
                "- results_dict: Dictionary grouped by category. Each entry contains 'box', 'score', optional 'mask', and 'saved_path' if saving is enabled.\n"
                "- object_counts_dict: Dictionary mapping each category to the number of detected instances."
            ),
            demo_commands=[{
            "command": 'execution = Advanced_Object_Detector_Tool.execute(image="images/street_scene.jpg", labels=["person", "car"], threshold=0.5)',
            "description": "Detect 'person' and 'car' in the image, filter out predictions below 0.5 confidence, and return grouped detection results."
            },
            {
            "command": 'execution = Advanced_Object_Detector_Tool.execute(image="images/pets.jpg", labels=["dog", "cat"], threshold=0.6, save_object=True, saved_image_path="outputs/pets")',
            "description": "Detect 'dog' and 'cat' in the image with a 0.6 confidence threshold, save the cropped detected objects into 'outputs/pets/', and return their info and counts."
            },
        ],   
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
    
    
    def execute(self,image, labels, threshold=0.45, save_object=False, saved_image_path="detected_objects"):
        
        gdino = GroundingDINOAPIWrapper(self.DINO_KEY)
        prompt_str = " . ".join(labels)
        
        prompts = dict(image=image, prompt=prompt_str)
        
        results = gdino.inference(prompts)
        
        if save_object:
            # Create the directory to save detected objects
            image_path = self.input_types['image']
            image = Image.open(image_path).convert("RGB")
            image_name = os.path.splitext(os.path.basename(image_path))[0]
            self.output_dir = saved_image_path
        
        grouped = defaultdict(list)
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
                entry["mask"] = (np.array(alpha) > 0)  # binary mask
                
            object_counts = {}
            object_counts[category] = object_counts.get(category, 0) + 1
            index = object_counts[category]
            
            if save_object:
                saved_path = self.save_detected_object(
                    image=image,
                    box=box,
                    image_name=image_name,
                    label=category,
                    index=index,
                    padding=10
                )
            entry["saved_path"] = saved_path
            # Add the saved image path to the entry
            grouped[category].append(entry)
            
        results = dict(grouped)
        
        return results, object_counts
    
    def get_metadata(self):
        metadata = super().get_metadata()
        return metadata    
    
        