import torch
from transformers import CLIPImageProcessor
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
from pathlib import Path
from torchvision import transforms
from dinov2.models import build_model_from_cfg
from easydict import EasyDict as edict
from dinov2.utils.config import get_cfg
from dinov2.utils.utils import load_pretrained_weights

class Matcher_Tool(BaseTool):
    def __init__(self):
        # Initialize the base tool with metadata
        super().__init__(
            tool_module_name="matcher",
            tool_class_name="Matcher_Tool",
            tool_description=("A tool that computes global semantic similarity and identifies corresponding local features between a reference image and a candidate image, given bounding boxes as inputs."),
            tool_version="1.0.0",
            input_types={
                "matching_type": "str - 'global_match' or 'local_match'. (Default is 'global_match').",
                "ref_img": "list[str] - The list of paths to one reference image file.",
                "candidate_img": "list[str] - The list of paths to the candidate imagesfile.",
                "ref_bbox": "list - required for 'local_match' matching type,  a list of 2 corner points of box representting a region in the reference image to be matched , in the format [[x1, y1], [x2, y2]].",
                "candidate_bbox": "list - required for 'local_match' matching type, a list of bounding boxes in the candidate image, each defined by 2 corner points coordinates [[x1, y1], [x2, y3]], the most similar box to the reference box will be selected."

            },
            output_types = ("int - if 'matching_type' is 'global_match', return the best matching image idx in list of `candidate_img",
                            "if 'matching_type' is 'local_match', return the best matching bounding box idx in `candidate_bbox"),
            demo_commands=[
            {
                "command": """
                matcher_tool = Matcher_Tool()
                matched_idx = matcher_tool.execute(matching_type='global_match', ref_img=['/path/to/ref.jpg'], candidate_img=['/path/to/candidate1.jpg', '/path/to/candidate2.jpg', '/path/to/candidate3.jpg'])
                """,
                "description": (
                    "Global visual matching demo: Given one reference image and multiple candidate images, "
                    "this command computes global semantic or style similarity  and returns the index of the best matching candidate image"
                ),
                "output_example": "matched_idx: 1  # That means `candidate_img[1]` is the best matching image.",
            },
            {
                "command": """
                matcher_tool = Matcher_Tool()
                matched_idx = matcher_tool.execute(matching_type='local_match', ref_img=['/path/to/ref.jpg'], candidate_img=['/path/to/candidate.jpg'], ref_bbox=[[[x1, y1], [x2, y2]]], candidate_bbox=[[[x1, y1], [x2, y2]], [[x1, y1], [x2, y2]]])
                """,
                "description": (
                    "Local feature matching demo: Given one reference image and one candidate image with bounding boxes,"
                    "this command computes local feature correspondence and returns the index of the best matching bounding box in candidate_bbox."
                ),
                "output_example": "matched_idx: 0 # That means the `candidate_bbox[0]` is the best matching one.",
            }
            ]
        )
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
    def build_tool(self, clip_model_size='openai/clip-vit-large-patch14', Dino_model_size = 'dinov2_vitb14', matching_type="global_match"):
        try:
            if matching_type == 'global_match':
                # Load CLIP model
                encoder = CLIPImageProcessor.from_pretrained(clip_model_size, torch_dtype=torch.float16)
                print(f"Loaded CLIP model: {clip_model_size}")
                return encoder
                
            elif matching_type == 'local_match':
                # Load DINOv2 model
                cfg = get_cfg("dinov2/dinov2/configs/eval/vitb14_pretrain.yaml")
                model, _, embed_dim = build_model_from_cfg(cfg, only_teacher=False)
                model.to(device=self.device).eval()
                # print(f"embed_dim: {embed_dim}") # vitb14: embed_dim: 768
                load_pretrained_weights(model, 'weights/dinov2_vitb14_pretrain.pth', checkpoint_key="teacher")
                print(f"Loaded DINOv2 model: {Dino_model_size}")
                return model, embed_dim
            else:
                raise ValueError("Invalid matching type. Use 'global_match' or 'local_match'.")
        except Exception as e:
            print(f"Error building the Visual Encoder: {e}")
            return None, None

    def execute(self, matching_type = 'global_match', ref_img = None, candidate_img = None, ref_bbox = None, candidate_bbox = None):
        """
        """
        
        if matching_type == 'global_match':
            model = self.build_tool(matching_type = matching_type) # build clip model
        else:
            model, _ = self.build_tool(matching_type = matching_type) # build DINOv2 model
        
        if matching_type=='global_match':
            assert ref_img is not None and len(candidate_img) > 1, "Reference image and multiple candidate images are required for global visual matching."
            # Load the model and preprocess function
            ref = Image.open(ref_img[0]).convert('RGB')
            inputs = model(images=ref, return_tensors="pt")
            # key: pixel_values, Inputs_shape: torch.Size([1, 3, 224, 224])
            ref_feature = inputs["pixel_values"]
            ref_feature = ref_feature.view(ref_feature.size(0), -1, 1024)
            ref_feature = torch.mean(ref_feature, dim=1, keepdim=False).unsqueeze(0).clone()
            ref_feature = ref_feature / ref_feature.norm(dim=-1, keepdim=True)
            print(f"Reference feature shape: {ref_feature.shape}")
            
            # Load the candidate images
            candidates = []
            for img in candidate_img:
                candidate = Image.open(img).convert('RGB')
                inputs = model(images=candidate, return_tensors="pt")
                candidate_feature = inputs["pixel_values"]
                candidate_feature = candidate_feature.view(candidate_feature.size(0), -1, 1024)
                print(f"Candidate image shape: {inputs['pixel_values'].shape}")
                candidates.append(candidate_feature)
                
            candidate_features = torch.cat(candidates, dim=0)
            candidate_features = torch.mean(candidate_features, dim=1, keepdim=False).unsqueeze(0).clone()
            candidate_features = candidate_features / candidate_features.norm(dim=-1, keepdim=True)
            print(f"Reference feature shape: {candidate_features.shape}")
            similarities = (100 * ref_feature @ candidate_features.transpose(1, 2)).softmax(dim=-1)
            best_idx = similarities.argmax().item()
            
            print(f"The {best_idx + 1}-th candidate image is the best matching image.")
            
            return best_idx
        
        if matching_type=='local_match':
            
            assert ref_img is not None and len(candidate_img) == 1, "one Reference and one candidate images are required for local correspondence matching."
            # assert ref_bbox is not None and candidate_bbox is not None, "Reference and candidate bounding boxes are required for local correspondence matching."
            def compute_iou(boxA, boxB):
                """
                In order to get max IoU
                box: [x1, y1, x2, y2]
                """
                xA = max(boxA[0], boxB[0])
                yA = max(boxA[1], boxB[1])
                xB = min(boxA[2], boxB[2])
                yB = min(boxA[3], boxB[3])
                inter_area = max(0, xB - xA) * max(0, yB - yA)
                boxA_area = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
                boxB_area = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
                iou = inter_area / float(boxA_area + boxB_area - inter_area + 1e-6) # avoid division by zero
                return iou
            
            def get_best_patch_by_iou(ref_bbx, orig_size, resize_size=224, patch_size=14):
                """
                used for mapping bbx input to patch feature level for matching
                
                input: 
                ref_bbx: reference bounding box in the format [x1, y1, x2, y2]
                orig_size: original image size (width, height)
                """
                orig_w, orig_h = orig_size
                scale_x = resize_size / orig_w
                scale_y = resize_size / orig_h

                # resize the reference bounding box to original size
                ref_box = [
                    ref_bbx[0] * scale_x,
                    ref_bbx[1] * scale_y,
                    ref_bbx[2] * scale_x,
                    ref_bbx[3] * scale_y,
                ]

                grid_size = resize_size // patch_size

                best_patch_id = None
                best_iou = 0.0

                for row in range(grid_size):
                    for col in range(grid_size):
                        patch_box = [col * patch_size, row * patch_size, (col + 1) * patch_size, (row + 1) * patch_size]
                        current_iou = compute_iou(ref_box, patch_box)
                        if current_iou > best_iou:
                            best_iou = current_iou
                            best_patch_id = row * grid_size + col

                return best_patch_id
            
            # using DINOv2 to extract local features
            ref_pil_image = Image.open(ref_img[0]).convert('RGB')
            can_pil_image = Image.open(candidate_img[0]).convert('RGB')
            
            ref_origin_size = ref_pil_image.size
            print(f"Original image size: {ref_origin_size}")
            can_origin_size = can_pil_image.size
            print(f"Candidate image size: {can_origin_size}")
            # get patch idx
            ref_patch_id = get_best_patch_by_iou(ref_bbx=ref_bbox, orig_size=ref_origin_size)
            
            prep = transforms.Compose([
                transforms.Resize((224,224)), # resize to 224x224
                transforms.ToTensor(), # convert to tensor and scale to [0,1]
                transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)) # imageNet mean and std
            ])
            
            # preprocess ref and candidate images
            ref = prep(ref_pil_image).unsqueeze(0).to(self.device)
            candidate = prep(can_pil_image).unsqueeze(0).to(self.device)

            # feature extraction
            with torch.no_grad():
                ref_out = model(ref, is_training=True)
                candidate_out = model(candidate, is_training=True)
                
                #################################################################################################
                # dict_keys(['x_norm_clstoken', 'x_norm_regtokens', 'x_norm_patchtokens', 'x_prenorm', 'masks'])#
                # x_norm_clstoken: torch.Size([1, 768])                                                         # 
                # x_norm_regtokens: torch.Size([1, 0, 768])                                                     # 
                # x_norm_patchtokens: torch.Size([1, 256, 768])   # ViT-B embedding dim: 768                    #
                # x_prenorm: torch.Size([1, 257, 768])                                                          #
                # masks: None                                                                                   #
                #################################################################################################
                    
                # refence feature
                ref_feature = ref_out["x_norm_patchtokens"].cpu().detach()
                ref_feature = ref_feature[0, ref_patch_id][None,...] # i is the best patch id
                # ref_feature = ref_feature[0,10][None,...] # for testing: i is the best patch id
                ref_feature = ref_feature / ref_feature.norm(dim=-1, keepdim=True)
                print(ref_feature.shape)
                
                # candidate feature
                candidate_features = candidate_out["x_norm_patchtokens"].cpu().detach()
                candidate_features = candidate_features[0]
                candidate_features = candidate_features / candidate_features.norm(dim=-1, keepdim=True)
                print(f"Candidate feature shape: {candidate_features.shape}")
                
                # Calculate the cosine similarity
                similarities = (100 * ref_feature @ candidate_features.T).softmax(dim=-1)
                
                # Find the best match
                best_idx = similarities.argmax().item()
                print(f"Best patch index: {best_idx}")
                
                patch_size = 14 # dinov2 vitb14 patch size
                num_patches = candidate_features.shape[0]
                grid_size = int(num_patches / patch_size)
                
                row = best_idx // grid_size
                col = best_idx % grid_size
                
                # patch bounding box
                matched_patch_box_resized = [col * patch_size, row * patch_size, (col + 1) * patch_size, (row + 1) * patch_size]
                # print("match_patch_box_resized in resized image:", matched_patch_box_resized)
                # convert to original candidate image size
                can_w, can_h = can_origin_size
                
                # resized image size is 448x448
                scale_x = can_w / 224 
                scale_y = can_h / 224
                # print(f"scale_x: {scale_x}, scale_y: {scale_y}")
                
                # bbx : [left top, right bottom] convert best matched patch box to original image size
                patch_box_original = [
                    matched_patch_box_resized[0] * scale_x,
                    matched_patch_box_resized[1] * scale_y,
                    matched_patch_box_resized[2] * scale_x,
                    matched_patch_box_resized[3] * scale_y
                ]
                print("Candidate patch box in candidate image:", patch_box_original)
                
                max_iou = 0.0
                
                for idx, bbx in enumerate(candidate_bbox):
                    print("Candidate bbx in candidate image:", bbx)
                    # candidate_bbox假定已是[x1, y1, x2, y2]
                    iou = compute_iou(bbx, patch_box_original)
                    if iou > max_iou:
                        max_iou = iou
                        best_candidate_bbx_idx = idx

                print("Best candidate index:", best_candidate_bbx_idx)
                
                return best_candidate_bbx_idx
                
                
    def get_metadata(self):
        metadata = super().get_metadata()
        return metadata
    
if __name__ == "__main__":
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.patches as patches
    from PIL import Image
    # # print(clip.available_models())
    
    matcher_tool = Matcher_Tool()
    # ########### local matching ##########
    # ref = ["./examples/local_feature_bbx/01.png"] #  头 [[633, 297], [854, 465]]
    # ref_bbox = [[633, 297], [854, 465]]
    # candidates = ["./examples/local_feature_bbx/02.png"] # [[175, 69], [350, 205]] GT;  
    # #[[287, 298], [438, 451]] 脖子 ；[[419, 924], [510, 1014]]脚； [[419, 924], [510, 1014]]尾巴
    # candidate_bbx = [[[287, 298], [438, 451]],  [[419, 924], [510, 1014]], [[419, 924], [510, 1014]],[[175, 69], [350, 205]]]
    # result = matcher_tool.execute(ref_img=ref, candidate_img=candidates, ref_bbox= ref_bbox, candidate_bbox=candidate_bbx, matching_type='local_match')
    # ########### local matching ##########
    
    ########## global matching ##########
    ref = ["./examples/semantic_full/01.png"]
    candidates = ["./examples/semantic_full/02.png","./examples/semantic_full/03.png"]
    result = matcher_tool.execute(ref_img=ref, candidate_img=candidates, matching_type='global_match')
    print(result)
    ########## global matching ##########
    
    # # validation and vasualization
    # img_path = './examples/local_feature_bbx/02.png'
    # bbx = [160.5, 64.0, 214.0, 128.0]  # (x_min, y_min, x_max, y_max)
    # image = Image.open(img_path).convert("RGB")
    # # 显示图片
    # fig, ax = plt.subplots(figsize=(10, 8))
    # ax.imshow(image)

    # # 解包 bbox 坐标
    # x_min, y_min, x_max, y_max = bbx
    # width = x_max - x_min
    # height = y_max - y_min

    # # 绘制矩形框
    # rect = patches.Rectangle(
    #     (x_min, y_min), width, height,
    #     linewidth=3, edgecolor='red', facecolor='none'
    # )
    # ax.add_patch(rect)

    # # 标注
    # ax.text(x_min, y_min - 10, "Selected BBox", color='red', fontsize=14, backgroundcolor='white')
    # plt.title("Visualize Selected BBox")
    # plt.axis('off')
    # plt.tight_layout()
    # plt.savefig("bbx_vis.png")  # 保存为图片