# Pixel-Level Depth Estimator
# https://github.com/DepthAnything/Depth-Anything-V2?tab=readme-ov-file#pre-trained-models

import argparse
import cv2
import glob
import matplotlib
import numpy as np
import os
import torch
from basetool import BaseTool
from depth_anything_v2.dpt import DepthAnythingV2

class Pixel_Depth_Tool(BaseTool):
    def __init__(self):
        super().__init__(
            tool_module_name="pixel_level_depth_estimator",
            tool_class_name="Pixel_Depth_Tool",
            tool_description="A tool that estimates pixel-level depth from image or video using the Depth Anything V2 model.",
            input_types={
                "mode": "str - The mode of operation, either 'image' or 'video' (default='image').",
                "image_path": "str - The path to single image, directory or txt file list.",
                "video_path": "str - The path to single videos, directory or txt file list.",
                "output": "bool - If True, save the depth image or depth video (default: False).",
                "outdir": "str - The output directory to save the depth images (default: './vis_depth').",
            },
            output_types={
                "image mode":  "Returns a list of depth images as NumPy arrays. Each element in the list is a single-channel (uint8) depth map corresponding to an input image",
                "video mode":  "Returns a list of lists, where each inner list contains depth frames for the corresponding video. Each frame is a single-channel (uint8) depth map.",
                "save depth":  "If output is True, saves the depth images or videos in the specified outdir. The depth images are saved as PNG files, and the depth videos are saved in MP4 format."
                },
            demo_commands= [
                {
                    "command": "image_depth = Pixel_Depth_Tool.execute(mode='image', image_path='/path/to/images_directory', video_path=None, output=True, outdir='./vis_depth')",
                    "description": "Processes images in image mode. It returns a list of depth maps as NumPy arrays (one per image) and saves each depth map as a PNG file in './vis_depth'",
                },
                {
                    "command": "Pixel_Depth_Tool.execute(mode='video', image_path=None, video_path='/path/to/video', output=True, outdir='./vis_depth')",
                    "description": "Processes videos in video mode. It returns a list where each element is a list of depth frames (one per video) and saves each processed depth video as an MP4 file in './vis_depth' if output is enabled.",
                }
            ],
            user_metadata={
                "Note": "The tool has different output formats and types depending on different modes."
            }
        )
    def execute(self, mode: str, image_path: str, video_path:str, output=False, outdir='./vis_depth'):
        input_size=518
        encoder='vitl'
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
        
        if output:
            os.makedirs(outdir, exist_ok=True)
        results = []
        if mode == 'image':
            # image mode : supports single image, directory or txt file list
            if os.path.isfile(image_path): 
                if image_path.lower().endswith('txt'):  # if it is a txt file
                    with open(image_path, 'r') as f:
                        filenames = f.read().splitlines()
                else:
                    filenames = [image_path] # single image
            else:
                filenames = glob.glob(os.path.join(image_path, '**/*'), recursive=True) # directory
            
            for k, filename in enumerate(filenames):
                print(f'Processing image {k+1}/{len(filenames)}: {filename}')
                raw_image = cv2.imread(filename)
                if raw_image is None:
                    print(f"Warning: Failed to load image {filename}")
                    continue
                
                # depth esetimation
                depth = depth_anything.infer_image(raw_image, input_size)
                depth = (depth - depth.min()) / (depth.max() - depth.min()) * 255.0
                depth = depth.astype(np.uint8)
                results.append(depth)
                if output:
                    output_filename = os.path.join(outdir, os.path.splitext(os.path.basename(filename))[0] + '.png')
                    depth = np.repeat(depth[..., np.newaxis], 3, axis=-1)
                    cv2.imwrite(output_filename, depth)
                
            return results
    
        elif mode == 'video':
            video_results = []
            # video mode : supports single video, directory or txt file list
            if os.path.isfile(video_path):
                if video_path.lower().endswith('txt'):
                    with open(video_path, 'r') as f:
                        filenames = f.read().splitlines()
                else:
                    filenames = [video_path]
            else:
                filenames = glob.glob(os.path.join(video_path, '**/*'), recursive=True)

            for k, filename in enumerate(filenames):
                print(f'Processing video {k+1}/{len(filenames)}: {filename}')
                
                raw_video = cv2.VideoCapture(filename)
                frame_width = int(raw_video.get(cv2.CAP_PROP_FRAME_WIDTH))
                frame_height = int(raw_video.get(cv2.CAP_PROP_FRAME_HEIGHT))
                frame_rate = int(raw_video.get(cv2.CAP_PROP_FPS))
                frames_result = [] # to store depth frames
                
                if output:
                    output_width = frame_width
                    output_filename = os.path.join(outdir, os.path.splitext(os.path.basename(filename))[0] + '.mp4')
                    out = cv2.VideoWriter(output_filename, cv2.VideoWriter_fourcc(*"mp4v"), frame_rate, (output_width, frame_height))
                
                while raw_video.isOpened():
                    ret, raw_frame = raw_video.read()
                    if not ret:
                        break
                    
                    depth = depth_anything.infer_image(raw_frame, input_size)
                    depth = (depth - depth.min()) / (depth.max() - depth.min()) * 255.0
                    depth = depth.astype(np.uint8) # 
                    frames_result.append(depth)
                    
                    if output:
                        # Save depth video
                        depth = np.repeat(depth[..., np.newaxis], 3, axis=-1)
                        out.write(depth)
                    

                raw_video.release()
                if output:
                    out.release()
                video_results.append(frames_result)
                
            return video_results
if __name__ == '__main__':
    
    # Test paths (update these paths with actual image/video locations)
    test_image_path = '/assets/examples'  # Can be a single image file, directory, or a txt file containing image paths.
    test_video_path = '/assets/examples_video'    # Can be a single video file, directory, or a txt file containing video paths.
    outdir = './vis_depth'
    
    # Create an instance of the Pixel_Depth_Tool
    tool = Pixel_Depth_Tool()
    
    # -----------------------
    # Test Image Mode
    # -----------------------
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
    for idx, depth_img in enumerate(image_results):
        print(f"Image {idx+1}: depth map shape: {depth_img.shape}")
    
    # -----------------------
    # Test Video Mode
    # -----------------------
    print("\nTesting video mode...")
    # When testing video mode, the image_path parameter is not used.
    video_results = tool.execute(
        mode='video',
        image_path='',   # Not used in video mode.
        video_path=test_video_path,
        output=True,     # Enable saving of depth videos.
        outdir=outdir
    )
    print("Video mode depth results:")
    for vid_idx, frames in enumerate(video_results):
        print(f"Video {vid_idx+1}: number of frames processed: {len(frames)}")
