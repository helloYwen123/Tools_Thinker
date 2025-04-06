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
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, root_dir)
from basetool import BaseTool
from depth_anything_v2.dpt import DepthAnythingV2

class Pixel_Depth_Tool(BaseTool):
    def __init__(self):
        super().__init__(
            tool_module_name="pixel_level_depth_estimator",
            tool_class_name="Pixel_Depth_Tool",
            tool_description="A tool that estimates pixel-level depth from image or video, which is useful for distance estimation.",
            input_types={
                "mode": "str - The mode of operation, either 'image' or 'video' (default='image').",
                "image_path": "list[str] - The list of path to a single or several input images.",
                "video_path": "list[str] - The list of path to a single or severatl input videos",
                "output": "bool - If True, save the depth image or depth video (default: False).",
                "outdir": "str - The output directory to save the depth images/videos (default: './vis_depth').",
            },
            output_types={
                "image_results": (
                    "dict - A dictionary containing the depth maps for each input image. "
                    "Each key is the image path and the corresponding value is a dictionary with keys: "
                    "e.g. 'assets/image1.jpg': {'depth_map': <numpy array with shape (H, W)>, 'output_image_path': 'path/to/saved/image.png'}"
                ),
                "video_results": (
                    "dict - A dictionary containing the depth maps for each input video. "
                    "Each key is the video path and the corresponding value is a dictionary with keys: "
                    "e.g. 'assets/video1.mp4': {'video_depth_map': <list of numpy arrays with shape (H, W)>, 'output_video_path': 'path/to/saved/video.mp4'}"
                ),
            },
            demo_commands= [
            {
                "command": "image_results = Pixel_Depth_Tool.execute(image_path=['assets/image1.jpg', 'assets/image2.jpg'], output=True, outdir= './vis_depth') ",
                "description": "Processes a list of input images, estimates their depth maps, and returns genereated depth images paths.",
                "output_examples": (
                        "{\n"
                        "  'assets/image1.jpg': {\n"
                        "      'depth_map': <numpy array with shape (H, W)>,\n"
                        "      'output_image_path': './vis_depth/image1.png'\n"
                        "  },\n"
                        "  'assets/image2.jpg': {\n"
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

    def execute(self, mode: str, image_path: list[str], video_path:list[str], output=False, outdir='./vis_depth'):
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
        if output:
            os.makedirs(outdir, exist_ok=True)
        
        
        if mode == 'image':
            image_results = {}
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
                
                # Save depth image
                output_filename = None
                if output:
                    output_filename = os.path.join(outdir, os.path.splitext(os.path.basename(filename))[0] + '.png')
                    depth = np.repeat(depth[..., np.newaxis], 3, axis=-1)
                    cv2.imwrite(output_filename, depth)
                    
                image_results[filename] = {"depth_map": depth, "output_image_path": output_filename}
            # print(f"results: {list(image_results.values())[0].shape}")
            
            # with open(os.path.join(outdir, 'depth.txt'), 'w') as f:
            #     for i in range(len(results)):
            #         f.write(f'{image_path[i]}: {results[i].shape}\n')
            #         f.write(f"result : {np.array2string(results[i])}\n")
            return image_results
        
        elif mode == 'video':
            video_results = {}
            # iterate over video_path

            for k, filename in enumerate(video_path):
                print(f'Processing video {k+1}/{len(video_path)}: {filename}')

                raw_video = cv2.VideoCapture(filename)
                frame_width,frame_height = int(raw_video.get(cv2.CAP_PROP_FRAME_WIDTH)), int(raw_video.get(cv2.CAP_PROP_FRAME_HEIGHT))
                frame_rate = int(raw_video.get(cv2.CAP_PROP_FPS))
                depth_frames = [] # to store depth frames
                
                output_filename = None
                if output:
                    output_filename = os.path.join(outdir, os.path.splitext(os.path.basename(filename))[0] + '.mp4')
                    out = cv2.VideoWriter(output_filename, cv2.VideoWriter_fourcc(*"mp4v"), frame_rate, (frame_width, frame_height))
                
                while raw_video.isOpened():
                    ret, raw_frame = raw_video.read()
                    if not ret:
                        break
                    
                    depth = depth_anything.infer_image(raw_frame, input_size)
                    depth = (depth - depth.min()) / (depth.max() - depth.min()) * 255.0
                    depth = depth.astype(np.uint8) # 
                    depth_frames.append(depth) # list contains depth images for each frame.
                    
                    if output:
                        # Save depth video
                        depth = np.repeat(depth[..., np.newaxis], 3, axis=-1)
                        out.write(depth)

                # Release video and resource         
                raw_video.release()
                if output:
                    out.release()
                    
                video_results[filename] = {"video_depth_map": depth_frames, "output_video_path": output_filename}
                
            return video_results
if __name__ == '__main__':

    # Test paths (update these paths with actual image/video locations)
    
    
    outdir = './vis_depth'
    
    # Create an instance of the Pixel_Depth_Tool
    tool = Pixel_Depth_Tool()
    
    # -----------------------
    # Test Image Mode
    # -----------------------
    test_image_path = ['./assets/examples/demo01.jpg']  # Can be a single image file, directory, or a txt file containing image paths.
    print("Testing image mode...")
    # When testing image mode, the video_path parameter is not used.
    image_results = tool.execute(
        mode='image',
        image_path=test_image_path,
        video_path='',  # Not used in image mode.
        output=True,    # Enable saving of depth images.
        outdir=outdir
    )
    print("Image mode depth results:")
    for key, depth_img in image_results.items():
        print(f"Image {key}: depth map shape: {depth_img.shape}")
    
    # -----------------------
    # Test Video Mode
    # -----------------------
    # print("\nTesting video mode...")
    # test_video_path = ['./assets/examples_video/basketball.mp4']   # Can be a single video file, directory, or a txt file containing video paths.
    # # When testing video mode, the image_path parameter is not used.
    # video_results = tool.execute(
    #     mode='video',
    #     image_path='',   # Not used in video mode.
    #     video_path=test_video_path,
    #     output=True,     # Enable saving of depth videos.
    #     outdir=outdir
    # )
    # print("Video mode depth results:")
    # for key, video_frames in video_results.items():
    #     print(f"Video {key}: number of frames processed: {len(video_frames)}")
