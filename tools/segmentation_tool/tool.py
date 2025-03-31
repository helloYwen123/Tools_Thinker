#  SAM2 models can be loaded from Hugging Face 
#  https://huggingface.co/models?search=sam2
#  pip install huggingface_hub

import torch
from sam2.sam2_image_predictor import SAM2ImagePredictor, SAM2VideoPredictor
import os
# if using Apple MPS, fall back to CPU for unsupported ops
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image
from basetool import BaseTool

class SegmentationTool(BaseTool):
    def __init__(self):
        super().__init__(
            tool_module_name="segmentation_tool",
            tool_class_name="SegmentationTool",
            tool_description="A tool that performs segmentation using the SAM2 model.",
            input_types={
                "segmentation_mode": "str: The mode for segmentation input. Allowed values are 'points' for point-based input and 'boxes' for box-based input.",
                "input_prompts": (
                "list[dict]: A list of dictionaries, each containing segmentation inputs for one image. "
                "Each dictionary must include an 'image_path' key (str) specifying the image file path. "
                "If segmentation_mode is 'points', include an 'input_points' key with a list of [x, y] coordinates; "
                "if segmentation_mode is 'boxes', include an 'input_box' key with a list of bounding boxes defined as [x1, y1, x2, y2]."
            ),
                 "model_size": "str: The SAM2 model size to use, e.g., 'base_plus' or 'small'."
            },
            ["path01","path02"]
            output_types={
                 "masks": (
                    "list: A list of segmentation masks as numpy arrays. For a single image input, each object has one mask with shape (H, W). "
                    "For batch input, the output includes an extra dimension for the image number, e.g., shape (B, O, H, W), "
                    "where B is the number of images and O is the number of objects per image."
                ),
            },
            demo_commands=[{"command":(
                    "segmentation_tool.execute(segmentation_mode='points' , "
                    "input_prompts=[{'image_path': 'path/to/image.jpg', 'input_points': [[100,200], [300,400]]}], "
                    "model_size='base_plus')"
                        ),
                    "description":"Segment an image using point-based input. At least two points are required to avoid ambiguity."},
                    {
                    "command": (
                    "segmentation_tool.execute(segmentation_mode='boxes', "
                    "input_prompts=[{'image_path': 'path/to/image.jpg', 'input_box': [[425,680,700,875]]}], "
                    "model_size='small')"
                    ),
                    "description": "Segment an image using a bounding box."
                    },
                    {
                    "command": (
                    "segmentation_tool.execute(segmentation_mode='points', "
                    "input_prompts=["
                    "  {'image_path': 'path/to/image1.jpg', 'input_points': [[100,200], [300,400]]}, "
                    "  {'image_path': 'path/to/image2.jpg', 'input_points': [[150,250], [350,450]]}"
                    "], "
                    "model_size='base_plus')"
                    ),
                    "description": "Batch segmentation using point-based input for multiple images."
                    },
                    ],
            user_metadata={
                "Note": "This tool uses the SAM2 model for segmentation tasks."
            }
        )
        # select the device for computation
        if torch.cuda.is_available():
            self.device = torch.device("cuda")
        elif torch.backends.mps.is_available():
            self.device = torch.device("mps")
        else:
            device = torch.device("cpu")
        print(f"using device: {device}")
        if device.type == "cuda":
            # use bfloat16 for the entire script
            torch.autocast("cuda", dtype=torch.bfloat16).__enter__()
            
    def build_tool(self, model_size= 'base_plus' ):
        model_name = f"facebook/sam2-hiera-{model_size}"
        try:
            predictor = SAM2ImagePredictor.from_pretrained(model_name, device=self.device)
            return predictor
        except Exception as e:
            print(f"Error building the Object Detection tool: {e}")
            return None

    def execute(self,prompt_type: str, input_prompts: dict, model_size):
        
        if len(input_prompts) == 1:
            prompt = input_prompts[0]
            image = Image.open(prompt["image_path"])
            image = np.array(image.convert("RGB"))
            predictor = self.build_tool(model_size=model_size)
            predictor.set_image(image)
            
            if prompt_type == "points":
                input_points = np.array(prompt["input_points"])  # shape: (N, 2)
                # at least two points are required to avoid ambiguity
                assert input_points.shape[0] >= 2, "At least two points are required to avoid ambiguity."
                
                input_point = input_points[0]
                
                input_label = np.ones((input_point.shape[0],), dtype=int)
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
                input_label = np.ones((input_points.shape[0],), dtype=int)

                mask_input = logits[np.argmax(scores), :, :]
                # using 2 points to create unambiguous mask(1,H,W) 
                masks, scores, _ = predictor.predict(
                    point_coords=input_point,
                    point_labels=input_label,
                    mask_input=mask_input[None, :, :],
                    multimask_output=False,
                )
                final_masks = masks  # shape: (1, H, W)
                
                
            elif prompt_type == "boxes":
                if "input_box" not in prompt or len(prompt["input_box"]) == 0:
                    raise ValueError("input_box is required.")
                
                # if only one box is provided
                input_boxes = np.array(prompt["input_box"])
                if len(input_prompts["input_box"]) == 1:
                    input_boxes=input_boxes[None, :]
                else:
                    input_boxes = input_boxes
                final_masks, scores, _ = predictor.predict(
                    point_coords=None,
                    point_labels=None,
                    box= input_boxes,
                    multimask_output=False,
                )
            
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
                if prompt_type == "boxes":
                    # create a batch of boxes
                    boxes_batch.append(np.array(input_prompt["input_box"]))
                if prompt_type == "points":
                    pts = np.array(input_prompt["input_points"])
                    # create a batch of points
                    points_batch.append(pts)
                    # create a batch of labels
                    labels_batch.append(np.ones((pts.shape[0],), dtype=int))
                    
            # create a batch of images features   
            predictor.set_image_batch(image_batch)
            
            if prompt_type == "boxes":
                
                # create a batch of masks
                final_masks, scores_batch, _ = predictor.predict_batch(
                    points_batch=None, labels_batch=None, boxes_batch=boxes_batch, multimask_output=False
                    )
            if prompt_type == "points":
                # Select the best single mask per object
                final_masks = []
                masks_batch, scores_batch, _ = predictor.predict_batch(
                    points_batch, labels_batch, box_batch=None, multimask_output=True
                    )
                # here masks_batch shape is (M ,O ,N ,H ,W) 
                # where N is the number of masks, M is the number of images, O is the number of objects
                for masks, scores in zip(masks_batch,scores_batch):
                    final_masks.append(masks[range(len(masks)), np.argmax(scores, axis=-1)])
            return final_masks
        
if __name__ == '__main__':

    # Assume that the SegmentationTool class has been defined and imported.
    segmentation_tool = SegmentationTool()

    # Set the model size for testing
    model_size = "base_plus"

    # Test Case 1: Single image with point-based input
    single_point_input = [
        {
            "image_path": "path/to/test_image.jpg",
            "input_points": [[100, 200], [300, 400]]
        }
    ]

    print("Testing single image with point-based input:")
    try:
        masks_points = segmentation_tool.execute(
            segmentation_mode='points',
            input_prompts=single_point_input,
            model_size=model_size
        )
        print("Returned masks for point-based input:")
        print(masks_points)
    except Exception as e:
        print("Error in point-based segmentation for a single image:", e)

    # Test Case 2: Single image with box-based input
    single_box_input = [
        {
            "image_path": "path/to/test_image.jpg",
            "input_box": [[425, 680, 700, 875]]
        }
    ]

    print("\nTesting single image with box-based input:")
    try:
        masks_boxes = segmentation_tool.execute(
            segmentation_mode='boxes',
            input_prompts=single_box_input,
            model_size=model_size
        )
        print("Returned masks for box-based input:")
        print(masks_boxes)
    except Exception as e:
        print("Error in box-based segmentation for a single image:", e)

    # Test Case 3: Batch processing with point-based input
    batch_point_input = [
        {
            "image_path": "path/to/test_image1.jpg",
            "input_points": [[100, 200], [300, 400]]
        },
        {
            "image_path": "path/to/test_image2.jpg",
            "input_points": [[150, 250], [350, 450]]
        }
    ]

    print("\nTesting batch processing with point-based input:")
    try:
        batch_masks_points = segmentation_tool.execute(
            segmentation_mode='points',
            input_prompts=batch_point_input,
            model_size=model_size
        )
        print("Returned masks for batch point-based input:")
        print(batch_masks_points)
    except Exception as e:
        print("Error in batch point-based segmentation:", e)

    print("\nAll tests completed.")
