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
sys.path.insert(0, root_dir)
print(root_dir)
from tools.object_detector.tool import Object_Detector_Tool 
from transformers import Qwen2VLForConditionalGeneration, AutoTokenizer, AutoProcessor
from qwen_vl_utils import process_vision_info


tool = Object_Detector_Tool()
metadata = tool.get_metadata()
# tool.set_custom_output_dir("detected_objects")


# print(metadata)

relative_image_path = "examples/baseball.png"
image_path = os.path.join(root_dir,"tools","object_detector", relative_image_path)

# Execute the tool
try:
    execution = tool.execute(image=image_path, labels=["baseball", "basket"], padding=20)
    print("Detected Objects:")
    for obj in execution:
        print(f"Detected {obj['label']} with confidence {obj['confidence score']}")
        print(f"Bounding box: {obj['box']}")
        print(f"Saved image (with padding): {obj['saved_image_path']}")
        print()
except ValueError as e: 
    print(f"Execution failed: {e}")

print("Done!")
