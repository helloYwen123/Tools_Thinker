from utils.paths import *
from utils.vision_tower import DINOv2_MLP
from transformers import AutoImageProcessor
import torch
from PIL import Image
from typing import Dict, List, Tuple, Union
import torch.nn.functional as F
from utils.utils import *
from utils.inference import *

from huggingface_hub import hf_hub_download
import cv2
import numpy as np
from math import cos, sin, radians

import sys,os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
current_dir = os.path.dirname(os.path.abspath(__file__))
tools_dir   = os.path.dirname(current_dir)
sys.path.insert(0, tools_dir)
from basetool import BaseTool

class Orientation_Estimator_Tool(BaseTool):
    """
    Estimate object orientation (yaw, pitch, roll, confidence) for single objects (whole image)
    or multiple objects (with bounding boxes) using Orient-Anything (DINOv2-MLP).
    """

    ORIENT_REPO = "Viglong/Orient-Anything"
    ORIENT_FILE = "croplargeEX2/dino_weight.pt"
    DINO_LARGE  = "facebook/dinov2-giant"

    def __init__(self):
        super().__init__(
            tool_module_name="pose_estimator",
            tool_class_name="Pose_Estimator_Tool",
            tool_description="Estimate yaw, pitch, roll of objects in an image using Orient-Anything (DINOv2-MLP).",
            tool_version="1.0.0",
            input_types={
                 "image_boxes": "dict - {image_path (str): list}. "
                               "Pass an empty list for single-object images; "
                               "otherwise supply one or more bounding boxes [x0,y0,x1,y1].",
            },
            output_types = "dict - {image_path: List[(yaw, pitch, roll, confidence)]}. "
                         "The list order matches the input bounding‑box order. "
                         "If the list of boxes is empty, one tuple is returned for the whole image.",
            demo_commands=[
                {
                    "command": """
                                pose_tool = Pose_Estimator_Tool()
                                # Multi-object (multi-box) inference:
                                image_boxes = {
                                    "assets/04.png": [[50, 30, 300, 280], [320, 40, 620, 330]],  # Multiple objects in one image
                                    "examples/cat.jpg": [[80, 60, 260, 240]]
                                }
                                results = pose_tool.execute(image_boxes=image_boxes, remove_bg=True)
                                # Whole-image inference (single object, no box):
                                image_list = ["assets/04.png"]
                                single_results = pose_tool.execute(image_list, remove_bg=False)
                                                    """,
                    "description": "Batch estimate single or multiple objects per image, with or without bounding boxes.",
                    "output_example": "{'assets/04.png': [(12.3, -5.6, 0.2, 0.91), (-31.0, 3.4, -6.2, 0.88)], "
                                      "'examples/cat.jpg': [(15.2, 1.1, -0.4, 0.92)]}"
                }
            ],
            user_metadata={
                "note": (
                    "For multiple objects, pass all bounding boxes as a list for each image. "
                    "Output angles are in degrees, confidence ∈ [0,1]. "
                    "For whole-image inference, pass a list of image paths (no boxes). "
                    "Returned lists always match the input box order (or single-item for full-image inference)."
                )
            }
        )

    def _load_weight(self, cache_dir: str = "./") -> str:
        """
        Download model weight (if not cached) and return local path.
        """
        return hf_hub_download(
            repo_id=self.ORIENT_REPO,
            filename=self.ORIENT_FILE,
            repo_type="model",
            cache_dir=cache_dir,
            resume_download=True,
        )

    def build_tool(self, device: str = None):
        """
        Build and return the model, image processor, and device.
        """
        device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        ckpt_path = self._load_weight()

        model = DINOv2_MLP(
            dino_mode   = 'large',
            in_dim      = 1024,
            out_dim     = 360 + 180 + 180 + 2,
            evaluate    = True,
            mask_dino   = False,
            frozen_back = False
        ).to(device).eval()

        model.load_state_dict(torch.load(ckpt_path, map_location=device))

        image_processor = AutoImageProcessor.from_pretrained(self.DINO_LARGE, cache_dir="./")
        return model, image_processor, device

    @staticmethod
    def _crop(img: np.ndarray, box: List[int]) -> Image.Image:
        """
        Crop the input image (as np.ndarray) using bbox [x0, y0, x1, y1] and return as PIL.Image.
        """
        x0, y0, x1, y1 = box
        crop = img[y0:y1, x0:x1]
        return Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))

    def execute(
        self,
        image_boxes: Dict[str, List[List[int]]],   # always dict now
        remove_bg: bool = False,
        device: str = None,
        verbose: bool = False,
        **kwargs
    ) -> Dict[str, List[Tuple[float, float, float, float]]]:
        """
        Parameters
        ----------
        image_boxes : dict
            {image_path: list}
            • If the list is empty → treat as single-object / whole-image inference.  
            • If the list contains one or more boxes → run per-box inference in list order.
        """

        model, img_proc, device = self.build_tool(device)
        results = {}

        for img_path, boxes in image_boxes.items():
            if verbose:
                mode = "full-image" if len(boxes) == 0 else f"{len(boxes)} box(es)"
                print(f"\n[Pose_Estimator] Processing {img_path} ({mode})")

            bgr = cv2.imread(img_path)
            if bgr is None:
                raise FileNotFoundError(f"Image not found: {img_path}")

            preds: List[Tuple[float, float, float, float]] = []

            # --- whole‑image path (empty list) ---
            if len(boxes) == 0:
                crop_pil = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
                # if remove_bg:
                #     crop_pil = background_preprocess(crop_pil, do_remove_background=True)
                angles = get_3angle(crop_pil, model, img_proc, device)
                preds.append(tuple(map(float, angles)))   # single tuple
                if verbose:
                    yaw, pitch, roll, conf = preds[-1]
                    print(f"  [FULL] → (yaw={yaw:.2f}, pitch={pitch:.2f}, "
                          f"roll={roll:.2f}, conf={conf:.2f})")

            # --- per‑box path ---
            else:
                for box in boxes:
                    crop_pil = self._crop(bgr, box)
                    # if remove_bg:
                    #     crop_pil = background_preprocess(crop_pil, do_remove_background=True)
                    angles = get_3angle(crop_pil, model, img_proc, device)
                    preds.append(tuple(map(float, angles)))
                    if verbose:
                        yaw, pitch, roll, conf = preds[-1]
                        print(f"  box {box} → (yaw={yaw:.2f}, pitch={pitch:.2f}, "
                              f"roll={roll:.2f}, conf={conf:.2f})")

            results[img_path] = preds

        return results
    
if __name__ == "__main__":
    import json
    import os
    import numpy as np
    from PIL import Image
    
    tool = Orientation_Estimator_Tool()
    os.makedirs("./vis", exist_ok=True)
    # ----------- single-object (whole-image) inference -----------
    # single_image_dict = {
    #     "assets/04.png": [],
    #     "assets/01.png": []
    # }
    # out1 = tool.execute(single_image_dict, remove_bg=False, verbose=True)
    # print("Full image (single object) inference:")
    # print(json.dumps(out1, indent=2))

    # os.makedirs("./vis", exist_ok=True)
    # for image_path in single_image_dict:
    #     yaw, pitch, roll, conf = out1[image_path][0]
    #     print(f"{image_path}: yaw={yaw}; pitch={pitch}; roll={roll}; confidence={conf}")

    #     origin_image = Image.open(image_path).convert('RGB')
    #     clean_img = background_preprocess(origin_image, do_remove_background=True)

    #     phi = np.radians(yaw)
    #     theta = np.radians(pitch)
    #     gamma = np.radians(roll)
    #     axis_canvas = render_3D_axis(phi, theta, gamma)  # returns PIL.Image

    #     composed = overlay_images_with_scaling(
    #         center_image=axis_canvas,
    #         background_image=clean_img,
    #         target_size=(512, 512)
    #     )
    #     out_name = f"demo_with_axis_{os.path.splitext(os.path.basename(image_path))[0]}.png"
    #     composed.save(os.path.join("./vis", out_name))
    #     print(f"Saved to ./vis/{out_name}")
    # -------------------------------------------------------------

    # # ----------- multi-object (multi-box) inference -----------
    sample_boxes = {
        "assets/04.png": [[50, 30, 300, 280], [320, 40, 620, 330]],
        "assets/01.png": [[50, 30, 300, 280], [320, 40, 620, 330]],
    }
    out2 = tool.execute(sample_boxes, remove_bg=False, verbose=True)
    print("Box-based (multi-object) inference:")
    print(json.dumps(out2, indent=2))

    for image_path, result_list in out2.items():
        origin_image = Image.open(image_path).convert('RGB')
        origin_np = np.array(origin_image)
        cvimg = cv2.cvtColor(origin_np, cv2.COLOR_RGB2BGR)
        boxes = sample_boxes[image_path]
        for box, (yaw, pitch, roll, confidence) in zip(boxes, result_list):
            print(f"{image_path} - box {box} → yaw: {yaw}; pitch: {pitch}; roll: {roll}; confidence: {confidence}")

            crop_pil = origin_image.crop((box[0], box[1], box[2], box[3]))
            clean_img = crop_pil  # or use background_preprocess if needed

            phi = np.radians(yaw)
            theta = np.radians(pitch)
            gamma = np.radians(roll)
            axis_canvas = render_3D_axis(phi, theta, gamma)

            composed = overlay_images_with_scaling(
                center_image=axis_canvas,
                background_image=clean_img,
                target_size=(box[2] - box[0], box[3] - box[1])
            )

            crop_save = os.path.join(
                "./vis",
                f"{os.path.splitext(os.path.basename(image_path))[0]}_{box[0]}_{box[1]}_{box[2]}_{box[3]}_poseaxis.png"
            )
            composed.save(crop_save)
            print(f"Saved crop+axis to {crop_save}")

            cv2.rectangle(cvimg, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 2)
            txt = f"Y:{yaw:.1f} P:{pitch:.1f} R:{roll:.1f}"
            cv2.putText(cvimg, txt, (box[0], box[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)

        full_vis_save = os.path.join(
            "./vis",
            f"{os.path.splitext(os.path.basename(image_path))[0]}_vis.png"
        )
        cv2.imwrite(full_vis_save, cvimg)
        print(f"Saved full image with boxes to {full_vis_save}")
