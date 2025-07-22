#  SAM2 models can be loaded from Hugging Face 
#  https://huggingface.co/models?search=sam2
#  pip install huggingface_hub

import torch
from sam2.sam2_image_predictor import SAM2ImagePredictor
import os
# if using Apple MPS, fall back to CPU for unsupported ops
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
current_dir = os.path.dirname(os.path.abspath(__file__))
tools_dir   = os.path.dirname(current_dir)
sys.path.insert(0, tools_dir)

from basetool import BaseTool  # note

class Segmenter_Tool(BaseTool):
    def __init__(self):
        super().__init__(
            tool_module_name="segmenter",
            tool_class_name="Segmenter_Tool",
            tool_description=(
                "A segmentation tool based on the SAM2 model, capable of accurately localizing specific objects at the pixel level using specific prompts(e.g., point lists or boxes)."
            ),
            input_types={
                "prompt_type": "str: 'points' or 'boxes'.",
                "input_prompts": (
                "list[dict] - list of dicts each with an `image_path` key (str) and a prompt key (str) based on the prompt_type. "
                "For the 'points' prompt type, prompt key should be 'input_points', a list of [x, y] coordinates with at least two points."
                "For the 'boxes' prompt type, prompt key should be 'input_box', a list of bounding boxes in `xyxy` format (i.e., [x1, y1, x2, y2])."
                ),
                "model_size": "str: SAM2 model size, e.g., 'base_plus' or 'small' (default: 'small')."
            },
            output_types={
                "masks: ": (
                    "np.ndarray or list[np.ndarray] -"
                    "For a single image input, the output is a numpy array, each of shape (O, 1, H, W), where O denotes the number of objects to be segmented."
                    "For batch input, the output is a list of length N (number of input images), where each element is a numpy array for the corresponding image, with each set having shape (O, 1, H, W), where O represents the number of objects to segment in the image."
                    "# Note that in these output masks, pixels set to 1 represent the region of the segmented object."
                )
            },
            demo_commands = [
                {
                    "command": """
                    segmenter_tool = Segmenter_Tool()
                    masks = segmenter_tool.execute(prompt_type='boxes', input_prompts=[{'image_path': 'path/to/image1', 'input_box': [[100,150,400,500]]}, {'image_path': 'path/to/image2', 'input_box': [[50,80,300,350]]}], model_size='small')
                    """,
                    "description": "Batch segmentation for multiple images using box-based input. Each image returns its segmentation mask as a numpy array.",
                    "output_examples": (
                        "masks : [mask_image1, mask_image2]\n"
                        "# Example: mask_image1.shape -> (1, 1, H1, W1), mask_image2.shape -> (1, 1, H2, W2), "
                        "where each mask is a numpy array representing the pixel-level locations (masks) of those objects specified with boxes."
                    )
                }
            ],
            user_metadata={
                "suggestions": "Before using the segmentation tools, it is advisable to consider how to obtain the points and bounding box coordinates for the region of interest."

            }
        )
        # select the device for computation
        if torch.cuda.is_available():
            self.device = torch.device("cuda")
        elif torch.backends.mps.is_available():
            self.device = torch.device("mps")
        else:
            self.device = torch.device("cpu")
        print(f"using device: {self.device}")
        if self.device.type == "cuda":
            # use bfloat16 for the entire script
            torch.autocast("cuda", dtype=torch.bfloat16).__enter__()
            
    def build_tool(self, model_size= 'small' ):
        model_name = f"facebook/sam2-hiera-{model_size}"
        try:
            predictor = SAM2ImagePredictor.from_pretrained(model_name, device=self.device)
            return predictor
        except Exception as e:
            print(f"Error building the Segmentation tool: {e}")
            return None

    def execute(self, prompt_type: str, input_prompts: dict, model_size= "small"):
        print(len(input_prompts))
        
        mask_dict = {}                          # returned dictionary
        save_dir = "./masks_npy"                      # save masks file in directory
        os.makedirs(save_dir, exist_ok=True)
        
        if len(input_prompts) == 1:
            prompt = input_prompts[0]
            image = Image.open(prompt["image_path"])
            image = np.array(image.convert("RGB"))
            predictor = self.build_tool(model_size=model_size)
            predictor.set_image(image)
            
            print(predictor._features["image_embed"].shape, predictor._features["image_embed"][-1].shape)
            
            if prompt_type == "points":
                input_points = np.array(prompt["input_points"])  # shape: (N, 2)
                # print(input_points.shape)
                # at least two points are required to avoid ambiguity
                assert input_points.shape[0] >= 2, "At least two points are required to avoid ambiguity."
                
                input_point = np.array(input_points[0:1])
                
                input_label = np.ones((input_point.shape[0]), dtype=int)
                
               
                masks, scores, logits = predictor.predict(
                        point_coords=input_point,
                        point_labels=input_label,
                        multimask_output=True,
                    )
                
                
                # here masks shape is (N, H, W) where N is the number of masks
                sorted_ind = np.argsort(scores)[::-1] # sort in descending order
                masks = masks[sorted_ind]  
                scores = scores[sorted_ind]
                logits = logits[sorted_ind]
                
                # Select the best single mask per object
                input_labels = np.ones((input_points.shape[0],), dtype=int)
                print(f"input label {input_labels}")
                
                mask_input = logits[np.argmax(scores), :, :]
                # using 2 points to create unambiguous mask(1,H,W) 
                masks, scores, _ = predictor.predict(
                    point_coords=input_points,
                    point_labels=input_labels,
                    mask_input=mask_input[None, :, :],
                    multimask_output=False,
                )
                print(f"mask shape: {masks.shape}")
                if len(masks.shape) == 3:
                    masks = masks[np.newaxis, ...]
                final_masks = []
                final_masks.append(masks)  # shape: (1, H, W)
            elif prompt_type == "boxes":
                
                if "input_box" not in prompt or len(prompt["input_box"]) == 0:
                    raise ValueError("input_box is required.")
                
                # if only one box is provided
                
                input_boxes = np.array(prompt["input_box"])
                if len(prompt["input_box"]) == 1:
                    input_boxes=input_boxes[None, :]
                else:
                    input_boxes = input_boxes
                masks, scores, _ = predictor.predict(
                    point_coords=None,
                    point_labels=None,
                    box= input_boxes,
                    multimask_output=False,
                )
                # print(f"final masks: {masks.shape}")
                if len(masks.shape) == 3:
                    masks = masks[np.newaxis, ...]
                final_masks = []
                final_masks.append(masks)  # shape: (1, 1, H, W)
            #### saved file path ####
            for idx, single_mask in enumerate(final_masks):
                single_mask = single_mask.astype(np.uint8)
                base = os.path.splitext(os.path.basename(prompt["image_path"]))[0]
                mask_name = f"{base}_mask_{idx}.npy"
                mask_path = os.path.join(save_dir, mask_name)
                np.save(mask_path, single_mask)
                # print(type(single_mask), np.unique(single_mask))
                mask_dict[prompt["image_path"]] = {"mask": single_mask, 'npy_path': mask_path}
            #### saved file path ####
            return mask_dict
        else:
            image_batch = []
            boxes_batch = []
            points_batch = []
            labels_batch = []
            for input_prompt in input_prompts:
                image = Image.open(input_prompt["image_path"])
                # convert image to RGB
                image = np.array(image.convert("RGB"))
                image_batch.append(image)
                if prompt_type == "boxes":
                    # create a batch of boxes
                    boxes_batch.append(np.array(input_prompt["input_box"]))
                if prompt_type == "points":
                    pts = np.array(input_prompt["input_points"])
                    assert pts.shape[0] >= 2, "At least two points are required to avoid ambiguity."
                    # print(pts.shape)
                    # create a batch of points
                    points_batch.append(pts)
                    # create a batch of labels
                    labels_batch.append(np.ones((pts.shape[0]), dtype=int))
                    
            predictor = self.build_tool(model_size=model_size)        
            # create a batch of images features   
            predictor.set_image_batch(image_batch)
            
            if prompt_type == "boxes":
                # create a batch of masks
                masks, scores_batch, _ = predictor.predict_batch(
                    None, None, box_batch=boxes_batch, multimask_output=False
                    )
                final_masks = []
                for mask in masks:
                    if len(mask.shape) == 3:
                        mask = mask[np.newaxis, ...]
                    final_masks.append(mask)
                # final_masks = np.array(final_masks)
                # print(f"final_masks shape: {final_masks.shape}") # here can't not unify the shape of each layer mask

            if prompt_type == "points":
                # Select the best single mask per object
                final_masks = []
                masks_batch, scores_batch, _ = predictor.predict_batch(
                    points_batch, labels_batch, box_batch=None, multimask_output=True
                    )
                masks_batch = np.array(masks_batch)
                # here masks_batch shape is (M ,O ,1 ,H ,W)
                # where N is the number of masks, M is the number of images, O is the number of objects for corresponding image
                for masks, scores in zip(masks_batch, scores_batch):
                    best_mask_idx = np.argmax(scores, axis=-1)
                    selected_mask = masks[range(len(masks)), best_mask_idx]
                    if len(selected_mask.shape) == 3:
                        selected_mask = selected_mask[np.newaxis, ...]
                    final_masks.append(selected_mask)
            for mask in final_masks:
                print(f"every{mask.shape}")

            for idx, (prompt, final_mask) in enumerate(zip(input_prompts, final_masks)):
                final_mask = final_mask.astype(np.uint8)
                base = os.path.splitext(os.path.basename(prompt["image_path"]))[0]
                mask_name = f"{base}_mask_{idx}.npy"
                mask_path = os.path.join(save_dir, mask_name)
                np.save(mask_path, final_mask)
                # print(type(final_mask), np.unique(final_mask))
                mask_dict[prompt["image_path"]] = {"mask": final_mask, 'npy_path': mask_path}

            return mask_dict
        
    def get_metadata(self):
        metadata = super().get_metadata()
        return metadata
    
if __name__ == '__main__':
    np.random.seed(3)
    def save_mask(mask, save_path, random_color=False, borders=True):
        """
        save mask image to verify correctness
        """
        if random_color:
            color = np.concatenate([np.random.random(3), np.array([0.6])], axis=0)
        else:
            color = np.array([30/255, 144/255, 255/255, 0.6])
        
        # 
        h, w = mask.shape[-2:]
        mask = mask.astype(np.uint8)
        mask_image = mask.reshape(h, w, 1) * color.reshape(1, 1, -1)
        
        if borders:
            import cv2
            #
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            # 
            contours = [cv2.approxPolyDP(contour, epsilon=0.01, closed=True) for contour in contours]
            mask_image = cv2.drawContours(mask_image, contours, -1, (1, 1, 1, 0.5), thickness=2)
        
        plt.imsave(save_path, mask_image)
        print(f"Mask saved to: {save_path}")

    segmenter_tool = Segmenter_Tool()
    model_size = "small"
####################PASS single image + Input(points)######################## 
    single_point_input = [
        {
            "image_path": "./examples/images/truck.jpg",
            "input_points": [[500, 375], [1125, 625]]
        }
    ]

    print("Testing single image with point-based input:")
    try:
        masks_points = segmenter_tool.execute(
            prompt_type='points',
            input_prompts=single_point_input,
            model_size=model_size
        )

        print("Returned masks for point-based input:")
        for path, mask_arr in masks_points.items():
            print(f"Result shape: {mask_arr['mask'].shape}")  # e.g. (N, 1, H, W)
            print(f"Returned mask's type is {type(masks_points)}")

            for obj_idx, obj_mask in enumerate(mask_arr["mask"]):
                single = np.squeeze(obj_mask, axis=0)  # (1, H, W) → (H, W)
                save_path = f"./saved_masks/mask_point_{obj_idx}.png"
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                save_mask(single, save_path, borders=True)
                print(f"Saved: {save_path}")

    except Exception as e:
        print("Error in point-based segmentation for a single image:", e)

####################PASS single image + Input(boxes)######################## 
    # single_box_input = [
    #     {
    #         "image_path": "./examples/images/truck.jpg",
    #         "input_box": [
    #             [75, 275, 1725, 850],
    #             [425, 600, 700, 875],
    #             [1375, 550, 1650, 800],
    #             [1240, 675, 1400, 750],
    #         ]
    #     }
    # ]

    # print("\nTesting single image with box-based input:")
    # try:
    #     masks_boxes = segmenter_tool.execute(
    #         prompt_type='boxes',
    #         input_prompts=single_box_input,
    #         model_size=model_size
    #     )

    #     print("Returned masks for box-based input:")
    #     for path, mask_arr in masks_boxes.items():
    #         print(f"Result shape: {mask_arr["mask"].shape}")  # (N, 1, H, W)
            
    #         for obj_idx, obj_mask in enumerate(mask_arr["mask"]):
    #             single = np.squeeze(obj_mask, axis=0)  # (H, W)
    #             save_path = f"./saved_masks/mask_box_{obj_idx}.png"
    #             os.makedirs(os.path.dirname(save_path), exist_ok=True)
    #             save_mask(single, save_path, borders=True)

    # except Exception as e:
    #     print("Error in box-based segmentation for a single image:", e)

################## 
    # Pass image batch , based on bbx
    # multi_box_input = [
    #     {
    #         "image_path": "./examples/images/truck.jpg",
    #         "input_box": [
    #             [75, 275, 1725, 850],
    #             [425, 600, 700, 875],
    #             [1375, 550, 1650, 800],
    #             [1240, 675, 1400, 750],
    #         ]
    #     },
    #     {
    #         "image_path": "./examples/images/truck.jpg",
    #         "input_box": [
    #             [450, 170, 520, 350],
    #             # [350, 190, 450, 350],
    #             # [500, 170, 580, 350],
    #             # [580, 170, 640, 350],
    #         ]
    #     }
    # ]
    # print("\nTesting multiple images with box-based input:")
    # try:
    #     masks_multi_boxes = segmenter_tool.execute(
    #         prompt_type='boxes',
    #         input_prompts=multi_box_input,
    #         model_size=model_size
    #     )
    #     print("Returned masks for multiple images with box-based input:")
    #     print(masks_multi_boxes)
    #     print(f"Returned mask's type is {type(masks_multi_boxes)}")

    #     # --- ---
    #     for idx, (image_path, mask_arr) in enumerate(masks_multi_boxes.items()):
    #         # save_mask(mask, path, borders=True)
    #         for obj_idx, obj_mask in enumerate(mask_arr["mask"]):
    #             single = np.squeeze(obj_mask, axis=0)  # 去掉通道维 (1,H,W) → (H,W)
    #             png_path =  save_path = "./saved_masks/mask_box" + f"_{obj_idx}.png" # save mask as `png`
    #             save_mask(single, png_path, borders=True)
    #         print(f"Saved visual mask to {png_path}")

    # except Exception as e:
    #     print("Error in box-based segmentation for multiple images:", e)

    print("\nAll tests completed.")
