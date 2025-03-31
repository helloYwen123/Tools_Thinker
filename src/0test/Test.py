import sys
import os

import time
import torch
import transformers
from transformers import pipeline
import torch.utils.data
from datasets import Dataset, IterableDataset

from PIL import Image, ImageOps

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))))
# sys.path.insert(0, root_dir)
# print(root_dir)
from object_detector import Object_Detector_Tool 
from transformers import Qwen2VLForConditionalGeneration, AutoTokenizer, AutoProcessor
from qwen_vl_utils import process_vision_info


tool = Object_Detector_Tool()
metadata = tool.get_metadata()
# tool.set_custom_output_dir("detected_objects")


# print(metadata)

def count_yellow_jackets(image_path, yellow_jackets):
    # Load the image using the objectdetector tool
    detection_tool = object_detector.Object_Detector_Tool()
    
    # Execute the detection tool with the given parameters
    execution = detection_tool.execute(image_path, ["yellow_jacket"], threshold=0.35, model_size="tiny", padding=20)
    
    # Get the bounding boxes for the detected yellow jackets
    yellow_jackets_with_boxes = []
    for detection in execution[0]:
        label = detection['label']
        confidence_score = detection['confidence score']
        box = tuple(detection['box'])
        
        # Add the detected yellow jacket to the result list
        yellow_jackets_with_boxes.append({'label': label, 'confidence score': confidence_score, 'box': box, 'saved_image_path': None})
    
    # Get the total number of yellow jackets detected
    total_yellow_jackets = 0
    for jacket in yellow_jackets_with_boxes:
        if jacket['label'] == 'yellow_jacket':
            total_yellow_jackets += 1
    
    return total_yellow_jackets

# Example usage
if __name__ == "__main__":
    # Remove the path arguments and execute the function
    count_result = count_yellow_jackets(image_path="/home/stud/wxie/BLINK_Dataset/Counting/val/images/val_Counting_103_image_1.jpg", yellow_jackets=None)
    final_result = count_result['yellow_jacket']
    print(f"The number of people wearing a yellow jacket is: {final_result}")
    print("Done!")
