import torch
import clip
from PIL import Image
import math
import numpy as np
import os
import json
import cv2
import re
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, root_dir)
from basetool import BaseTool # note
from typing import Any, Dict, Generator, ItemsView, List, Tuple

class Matcher(BaseTool):
    def __init__(self):
        # Initialize the base tool with metadata
        super().__init__(
            tool_module_name="matcher",
            tool_class_name="Matcher",
            tool_description=("A tool that matches global similarity or local feature in images. It's very useful for Visual Similarity Judgement or "
                              "Local Feature Correspondence Task"),
            tool_version="1.0.0",
            input_types={
                "matching_type": "str - global_visual or local_correspondence. Default is 'global_visual'.",
                "bbox": "list - A list of bounding box coordinates[[[],[],[],[]]] in the format [[[x1, y1], [x2, y2], [x3, y3], [x4, y4]]].",
                "ref_img": "str - The paths to the reference image file.",
                "candidate_img": "str - The paths to the candidate image file."
            },
            output_types = "list - A list of matched features with bounding box coordinates, recognized text, and confidence score.",
            demo_commands=[
                {
                    "command": 'results = FeatureMatcher.execute(image="path/to/image.png", text="example")',
                    "description": "Match features in an image using CLIP.",
                    "output_example": '[[[100, 150], [200, 150], [200, 200], [100, 200], "example", 0.95]]'
                }
            ]
        )
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
    
    def build_tool(self, model_size= 'ViT-B/16' ):
            try:
                model, preprocess = clip.load(model_size, device=self.device)
                return model, preprocess
            except Exception as e:
                print(f"Error building the Visual Encoder: {e}")
                return None, None
            
    # The function is based on Github Link:        
    def generate_crop_boxes(
    im_size: Tuple[int, ...], n_layers: int, overlap_ratio: float
    ) -> Tuple[List[List[int]], List[int]]:
        """
        
        Generates a list of crop boxes of different sizes. Each layer
        has (2**i)**2 boxes for the ith layer.
        """
        crop_boxes, layer_idxs = [], []
        im_h, im_w = im_size
        short_side = min(im_h, im_w)

        # Original image
        crop_boxes.append([0, 0, im_w, im_h])
        layer_idxs.append(0)

        def crop_len(orig_len, n_crops, overlap):
            return int(math.ceil((overlap * (n_crops - 1) + orig_len) / n_crops))

        for i_layer in range(n_layers):
            n_crops_per_side = 2 ** (i_layer + 1)
            overlap = int(overlap_ratio * short_side * (2 / n_crops_per_side))

            crop_w = crop_len(im_w, n_crops_per_side, overlap)
            crop_h = crop_len(im_h, n_crops_per_side, overlap)

            crop_box_x0 = [int((crop_w - overlap) * i) for i in range(n_crops_per_side)]
            crop_box_y0 = [int((crop_h - overlap) * i) for i in range(n_crops_per_side)]

            # Crops in XYWH format
            for x0, y0 in product(crop_box_x0, crop_box_y0):
                box = [x0, y0, min(x0 + crop_w, im_w), min(y0 + crop_h, im_h)]
                crop_boxes.append(box)
                layer_idxs.append(i_layer + 1)

        return crop_boxes, layer_idxs

    def execute(self, mode = 'global_visual', matching_type = 'semantic', bbox = None, ref_img = None, candidate_img = None):
        model, preprocess = self.build_tool()
        if mode=='global_visual':
            assert ref_img is not None, "Reference image is required for semantic matching."
            # Load the model and preprocess function
            ref = preprocess(Image.open(ref_img)).unsqueeze(0).to(self.device)
            
            candidates = []
            for img in candidate_img:
                candidate = preprocess(Image.open(img)).unsqueeze(0).to(self.device)
                candidates.append(candidate)
            
            with torch.no_grad():
                ref_features = model.encode_image(ref)
                candidate_features = torch.cat([model.encode_image(candidate) for candidate in candidates], dim=0)
                # Normalize the features
                ref_features = ref_features / ref_features.norm(dim=-1, keepdim=True)
                candidate_features = candidate_features / candidate_features.norm(dim=-1, keepdim=True)
                
                # Calculate the cosine similarity
                similarities = (100 * ref_features @ candidate_features.T).softmax(dim=-1)
                # Find the best match
                best_idx = similarities.argmax().item()
                # bast_prob = similarities[best_idx].item()
                
                # values, indices = similarities[0].topk(5)
                # # Print the result
                # print("\nTop predictions:\n")
                # for value, index in zip(values, indices):
                #     print(f"{classes[index]}: {100 * value.item():.2f}%")
        if mode=='local_correspondence':
            
            pass
            
        return best_idx
    
    def get_metadata(self):
        metadata = super().get_metadata()
        return metadata
if __name__ == "__main__":
    print(clip.available_models())
    matcher = Matcher()
    ref = "./examples/Jigsaw/01.png"
    candidates = ["./examples/Jigsaw/03.png", "./examples/Jigsaw/02.png"]
    result = matcher.execute(ref_img=ref, candidate_img=candidates)
    print(result)