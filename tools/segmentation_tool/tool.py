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
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, root_dir)
from basetool import BaseTool  # note

class Segmentation_Tool(BaseTool):
    def __init__(self):
        super().__init__(
            tool_module_name="segmentation_tool",
            tool_class_name="Segmentation_Tool",
            tool_description=(
                "A segmentation tool using the SAM2 model."
                "Supports point-based and box-based inputs for single or batch segmentation."
            ),
            input_types={
                "segmentation_mode": "str: 'points' or 'boxes'.",
                "input_prompts": (
                "list[dict]: Each dictionary must include an 'image_path' key (str). "
                "Optionally, include one of the keys 'input_points' or 'input_box'. "
                "For 'points' segmentation_mode, 'input_points' should be a list of [x, y] coordinates; "
                "for 'boxes' segmentation_mode, 'input_box' should be a list of bounding boxes defined as [x1, y1, x2, y2]."
                ),
                "model_size": "str: SAM2 model size, e.g., 'base_plus' or 'small' (default: 'small')."
            },
            output_types={
                "masks": (
                    "list: Segmentation masks as numpy arrays. "
                    "For single image input, the output is a list of masks, each of shape (O, 1, H, W). O is number of Obeject in image segmentation "
                    "For batch input, the output is a list of length equal to the number of input images, "
                    "where each element is a list of masks for that image (each mask with shape (O, 1, H, W))."
                    "Note that the number of masks may vary across images."
                )
            },
            demo_commands = [
                {
                    "command": """
                    segmentation_tool = Segmentation_Tool()
                    masks = segmentation_tool.execute(segmentation_mode='boxes', input_prompts=[{'image_path': 'path/to/image1', 'input_box': [[100,150,400,500]]}, {'image_path': 'path/to/image2', 'input_box': [[50,80,300,350]]}], model_size='small')
                    """,
                    "description": "Batch segmentation for multiple images using box-based input. Each image returns its segmentation mask as a numpy array.",
                    "output_examples": (
                        "masks = [mask_image1, mask_image2]\n"
                        "# Example: mask_image1.shape -> (1, 0, H1, W1), mask_image2.shape -> (1, 0, H2, W2)\n"
                        "# where each mask is a numpy array representing the segmentation result."
                    )
                }
            ],
            user_metadata={
                "Suggestions": "Before using the segmentation tools, it is advisable to consider how to obtain the points and bounding box coordinates for the region of interest."

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

    def execute(self, segmentation_mode: str, input_prompts: dict, model_size= "small"):
        print(len(input_prompts))
        if len(input_prompts) == 1:
            prompt = input_prompts[0]
            image = Image.open(prompt["image_path"])
            image = np.array(image.convert("RGB"))
            predictor = self.build_tool(model_size=model_size)
            predictor.set_image(image)
            
            print(predictor._features["image_embed"].shape, predictor._features["image_embed"][-1].shape)
            
            if segmentation_mode == "points":
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
                print(f"mask shape: {masks.shape}")
                
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
                print(masks.shape)
                final_masks = masks  # shape: (1, H, W)
                
                
            elif segmentation_mode == "boxes":
                
                if "input_box" not in prompt or len(prompt["input_box"]) == 0:
                    raise ValueError("input_box is required.")
                
                # if only one box is provided
                
                input_boxes = np.array(prompt["input_box"])
                if len(prompt["input_box"]) == 1:
                    input_boxes=input_boxes[None, :]
                else:
                    input_boxes = input_boxes
                final_masks, scores, _ = predictor.predict(
                    point_coords=None,
                    point_labels=None,
                    box= input_boxes,
                    multimask_output=False,
                )
                print(final_masks.shape)
            return final_masks
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
                if segmentation_mode == "boxes":
                    # create a batch of boxes
                    boxes_batch.append(np.array(input_prompt["input_box"]))
                if segmentation_mode == "points":
                    pts = np.array(input_prompt["input_points"])
                    assert pts.shape[0] >= 2, "At least two points are required to avoid ambiguity."
                    print(pts.shape)
                    # create a batch of points
                    points_batch.append(pts)
                    # create a batch of labels
                    labels_batch.append(np.ones((pts.shape[0]), dtype=int))
                    
            predictor = self.build_tool(model_size=model_size)        
            # create a batch of images features   
            predictor.set_image_batch(image_batch)
            
            if segmentation_mode == "boxes":
                # create a batch of masks
                final_masks, scores_batch, _ = predictor.predict_batch(
                    None, None, box_batch=boxes_batch, multimask_output=False
                    )
                # final_masks = np.array(final_masks)
                # print(f"final_masks shape: {final_masks.shape}") # here can't not unify the shape of each layer mask
            if segmentation_mode == "points":
                # Select the best single mask per object
                final_masks = []
                masks_batch, scores_batch, _ = predictor.predict_batch(
                    points_batch, labels_batch, box_batch=None, multimask_output=True
                    )
                masks_batch = np.array(masks_batch)
               
                # here masks_batch shape is (M ,O ,1 ,H ,W) 
                # where N is the number of masks, M is the number of images, O is the number of objects for corresponding image
                for masks, scores in zip(masks_batch,scores_batch):
                    final_masks.append(masks[range(len(masks)), np.argmax(scores, axis=-1)])
            for mask in final_masks:
                print(mask.shape)
            return final_masks
        
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

    segmentation_tool = Segmentation_Tool()
    model_size = "small"
####################PASS single image + Input(points)######################## 
    # single_point_input = [
    #     {
    #         "image_path": "./examples/images/truck.jpg",
    #         "input_points": [[500, 375], [1125, 625]]
    #     }
    # ]
    # print("Testing single image with point-based input:")
    # try:
    #     masks_points = segmentation_tool.execute(
    #         segmentation_mode='points',
    #         input_prompts=single_point_input,
    #         model_size=model_size
    #     )
    #     print("Returned masks for point-based input:")
    #     print(masks_points)
    #     print(f"Returned mask's type is {type(masks_points)}")
        
    #     #
    #     for idx, mask in enumerate(masks_points):
    #         save_path = f"./saved_masks/mask_point_{idx}.png"
            
    #         import os
    #         os.makedirs(os.path.dirname(save_path), exist_ok=True)
    #         save_mask(mask, save_path, borders=True)
    # except Exception as e:
    #     print("Error in point-based segmentation for a single image:", e)

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
    #     masks_boxes = segmentation_tool.execute(
    #         segmentation_mode='boxes',
    #         input_prompts=single_box_input,
    #         model_size=model_size
    #     )
    #     print("Returned masks for box-based input:")
    #     print(masks_boxes.shape)
    #     idx= 0
    #     for mask in masks_boxes:
    #         idx += 1
    #         save_path = f"./saved_masks/mask_box_{idx}.png"
    #         os.makedirs(os.path.dirname(save_path), exist_ok=True)
    #         save_mask(mask.squeeze(0), save_path, borders=True)
    # except Exception as e:
    #     print("Error in box-based segmentation for a single image:", e)

################## 
   # Pass image batch , based on bbx
    multi_box_input = [
        {
            "image_path": "./examples/images/truck.jpg",
            "input_box": [
                [75, 275, 1725, 850],
                [425, 600, 700, 875],
                [1375, 550, 1650, 800],
                [1240, 675, 1400, 750],
            ]
        },
        {
            "image_path": "./examples/images/groceries.jpg",
            "input_box": [
                [450, 170, 520, 350],
                [350, 190, 450, 350],
                # [500, 170, 580, 350],
                # [580, 170, 640, 350],
            ]
        }
    ]
    print("\nTesting multiple images with box-based input:")
    try:
        masks_multi_boxes = segmentation_tool.execute(
            segmentation_mode='boxes',
            input_prompts=multi_box_input,
            model_size=model_size
        )
        print("Returned masks for multiple images with box-based input:")
        print(masks_multi_boxes)
        
        for img_idx, masks in enumerate(masks_multi_boxes):
            for mask_idx, mask in enumerate(masks):
                save_path = f"./saved_masks/mask_multi_{img_idx}_{mask_idx}.png"
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                save_mask(mask.squeeze(0), save_path, borders=True)
    except Exception as e:
        print("Error in box-based segmentation for multiple images:", e)

    print("\nAll tests completed.")