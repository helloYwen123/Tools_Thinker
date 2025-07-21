# Pixel-Level Depth Estimator
# https://github.com/DepthAnything/Depth-Anything-V2?tab=readme-ov-file#pre-trained-models

import argparse
import cv2
import glob
import matplotlib
import numpy as np
import os
import torch
import sys
# current_dir = os.path.dirname(os.path.abspath(__file__))
# root_dir = os.path.dirname(os.path.dirname(current_dir))
# sys.path.insert(0, root_dir)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
current_dir = os.path.dirname(os.path.abspath(__file__))
tools_dir   = os.path.dirname(current_dir)
sys.path.insert(0, tools_dir)
from basetool import BaseTool
from depth_anything_v2.dpt import DepthAnythingV2
from transformers import pipeline
from PIL import Image
import requests

import matplotlib.pyplot as plt

class Depth_Estimator_Tool(BaseTool):
    def __init__(self):
        super().__init__(
            tool_module_name="depth_estimator",
            tool_class_name="Depth_Estimator_Tool",
            tool_description="A tool that estimates pixel-level depth from image or video, which is useful for distance estimation.",
            input_types={
                "mode": "str - The mode of operation, either 'image' or 'video' (default='image').",
                "image_path": "list[str] - The list of path to a single or several input images.",
                "output": "bool - If True, save the depth image or depth video (default: False).",
                "outdir": "str - The output directory to save the depth images/videos (default: './vis_depth').",
            },
            output_types={
                "image_results": (
                    "dict - dict - A dictionary containing the depth maps for each input image."
                    "Each key is the input `image_path`(str) and the corresponding value is a dictionary with keys:"
                    "e.g. 'assets/image1.jpg': {'depth_map': <numpy array with shape (H, W)>, 'output_image_path': 'path/to/saved/image.png'}"
                    "# Note that in the depth map, larger pixel values represent greater depth (i.e., further from the camera)."
                ),
            },
            demo_commands= [
            {
                "command": """
                depth_estimator_tool = Depth_Estimator_Tool()
                image_results = depth_estimator_tool.execute(image_path=['assets/image1', 'assets/image2'], output=True, outdir= './vis_depth') 
                """,
                "description": "Processes a list of input images, estimates their depth maps, and returns genereated depth images paths.",
                "output_examples": (
                        "{\n"
                        "  'assets/image1': {\n"
                        "      'depth_map': <numpy array with shape (H, W)>,\n"
                        "      'output_image_path': './vis_depth/image1.png'\n"
                        "  },\n"
                        "  'assets/image2': {\n"
                        "      'depth_map': <numpy array with shape (H, W)>,\n"
                        "      'output_image_path': './vis_depth/image2.png'\n"
                        "  }\n"
                        "}"
                ),
            },

            ],
            user_metadata={
                "Note": "Before running this tool, \
                you need to know the approximate locations of the two objects in the image in order to compare their distances based on depth information."
            }
        )

    def execute(self, image_path: list[str], depth_estimation_type: str = "relative", output=False, outdir='./vis_depth'):
        if output:
            os.makedirs(outdir, exist_ok=True)    
            image_results = {}
        if depth_estimation_type == 'relative':
            input_size=518
            encoder='vitb'
            DEVICE = 'cuda' if torch.cuda.is_available() else 'mps' if torch.backends.mps.is_available() else 'cpu'
            model_configs = {
            'vits': {'encoder': 'vits', 'features': 64, 'out_channels': [48, 96, 192, 384]},
            'vitb': {'encoder': 'vitb', 'features': 128, 'out_channels': [96, 192, 384, 768]},
            'vitl': {'encoder': 'vitl', 'features': 256, 'out_channels': [256, 512, 1024, 1024]},
            'vitg': {'encoder': 'vitg', 'features': 384, 'out_channels': [1536, 1536, 1536, 1536]}
            }
            depth_anything = DepthAnythingV2(**model_configs[encoder])
            state_dict = torch.load(f'checkpoints/depth_anything_v2_{encoder}.pth', map_location='cpu')
            depth_anything.load_state_dict(state_dict)
            depth_anything = depth_anything.to(DEVICE).eval()
            print(f"loading model depth_anything_v2_{encoder}.pth on {DEVICE}")

            # iterate over image_path
            for k, filename in enumerate(image_path):
                print(f'Processing image {k+1}/{len(image_path)}: {filename}')
                raw_image = cv2.imread(filename)
                print(f"raw_image shape: {raw_image.shape}")
                if raw_image is None:
                    print(f"Warning: Failed to load image {filename}")
                    continue
                
                # depth esetimation
                depth = depth_anything.infer_image(raw_image, input_size)
                depth = (depth - depth.min()) / (depth.max() - depth.min()) * 255.0
                depth = depth.astype(np.uint8)
                
                base_name = os.path.splitext(os.path.basename(filename))[0]
                npy_path = os.path.join(outdir, f"{base_name}_depth.npy")
                np.save(npy_path, depth)
                
                # Save depth image
                output_filename = None
                if output:
                    output_filename = os.path.join(outdir, os.path.splitext(os.path.basename(filename))[0] + '.png')
                    depth = np.repeat(depth[..., np.newaxis], 3, axis=-1)
                    cv2.imwrite(output_filename, depth)
                    
                image_results[filename] = {
                    "depth_map": depth,
                    "output_image_path": output_filename,
                    "npy_path": npy_path
                }
            # print(f"results: {list(image_results.values())[0].shape}")
            
            # with open(os.path.join(outdir, 'depth.txt'), 'w') as f:
            #     for i in range(len(results)):
            #         f.write(f'{image_path[i]}: {results[i].shape}\n')
            #         f.write(f"result : {np.array2string(results[i])}\n")
                return image_results
        else:
            image_results = {}
            if depth_estimation_type == 'metric_outdoor':                
                # load pipe
                pipe = pipeline(task="depth-estimation", model="depth-anything/Depth-Anything-V2-Metric-Outdoor-Large-hf")
            elif depth_estimation_type == 'metric_indoor':
                # load pipe
                pipe = pipeline(task="depth-estimation", model="depth-anything/Depth-Anything-V2-Metric-Indoor-Large-hf")
            else:
                raise ValueError("No valid 'depth estimation type' ! \n ")
            if output:
                os.makedirs(outdir, exist_ok=True)
            for k, filename in enumerate(image_path):
                image = Image.open(filename).convert("RGB")
                # inference
                # metric
                depth = pipe(image)
                # print(depth["predicted_depth"].size())
                depth_metric = depth["predicted_depth"].squeeze(0).squeeze(0) # remove `dim==1`
                # depth info
                depth_info = depth["depth"]
                depth_info = np.array(depth_info)
                depth_info = depth_info[..., None]
                
                # # transfer to NumPy
                depth_np = depth_metric.cpu().numpy().astype(np.float32)
                
                base_name = os.path.splitext(os.path.basename(filename))[0]
                npy_path = os.path.join(outdir, f"{base_name}_depth.npy")
                np.save(npy_path, depth_np)
                

                # Save depth image
                output_filename = None
                if output:
                    output_filename = os.path.join(outdir, os.path.splitext(os.path.basename(filename))[0] + '.png')
                    depth = np.repeat(depth_info, 3, axis=-1)
                    cv2.imwrite(output_filename, depth)
                image_results[filename] = {
                    "depth_map": depth_metric,
                    "output_image_path": output_filename,
                    "npy_path": npy_path
                }
                return image_results
            
            
if __name__ == '__main__':
    import numpy as np

    # Test paths (update these paths with actual image/video locations)
    outdir = './vis_depth'

    # Create an instance of the Depth_Estimator_Tool
    tool = Depth_Estimator_Tool()
    # -----------------------
    # Test Image Mode
    # -----------------------
    # test_image_path = ['./assets/examples/demo01.jpg'] 
    # print("Testing image mode...")
    # # When testing image mode, the video_path parameter is not used.
    # image_results = tool.execute(
    #     mode='image',
    #     image_path=test_image_path,
    #     video_path='',  # Not used in image mode.
    #     output=True,    # Enable saving of depth images.
    #     outdir=outdir
    # )
    # print("Image mode depth results:")
    # for key, depth_img in image_results.items():
    #     print(f"Image {key}: depth map shape: {depth_img['depth_map'].shape}")
    # -----------------------------
    # metric type
    # -----------------------------
    test_image_path = ['./assets/examples/demo01.jpg'] 
    print("Testing image mode...")
    # When testing image mode, the video_path parameter is not used.
    image_results = tool.execute(
        depth_estimation_type='relative', # or metric_indoor relative
        image_path=test_image_path,
        output=True,    # Enable saving of depth images.
        outdir=outdir
    )
    for key, depth_img in image_results.items():
        print(f"Image {key}: depth map shape: {depth_img['depth_map'].shape}")
        print("min/max:", depth_img['depth_map'].min(), depth_img['depth_map'].max())
        
        depth_map = np.load(key)
        print(f"depth map size: {depth_map.shape}.")
        
