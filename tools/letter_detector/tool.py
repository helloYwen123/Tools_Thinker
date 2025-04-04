import os
import cv2
import numpy as np
import matplotlib.pyplot as plt
import easyocr
import json
import time
import torch
import re
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, root_dir)
from basetool import BaseTool
class Letter_Detector_Tool(BaseTool):
    def __init__(self):
        super().__init__(
            tool_module_name = "letter_detector",
            tool_class_name = "Letter_Detector_Tool",
            tool_description = "A tool that detects filtered letters in an image using EasyOCR.",
            tool_version = "1.0.0",
            input_types = {
                "image": "str - The path to the image file."
            },
            output_types = "list - A list of detected letters with bounding box coordinates, recognized text, and confidence score.",
            demo_commands = [
                {
                    "command": 'results = Letter_Detector_Tool.execute(image="path/to/image.png")',
                    "description": "Detect one letter A in an image using EasyOCR., return a tuple of bbx, text, and score.",
                    "output_example": '[[[100, 150], [200, 150], [200, 200], [100, 200], "A", 0.95]]'
                }
            ],
            user_metadata = {
                "usage_scenarios": "This tool can be very useful when needing to locate specific letters points in images."
            }
        )
        

    def preprocess_image(self, image_path):
        img = cv2.imread(image_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        eq = cv2.equalizeHist(gray)
        bin_img = cv2.adaptiveThreshold(eq, 255,
                                        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY_INV,
                                        15, 10)
        scale = 2
        resized = cv2.resize(bin_img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        return resized

    def detect_filtered_letters(self, image_path, max_retries=10, retry_delay=5, clear_cuda_cache=False):
        for attempt in range(max_retries):
            try:
                # image_np = self.preprocess_image(image_path)
                image_np = cv2.imread(image_path, cv2.IMREAD_COLOR)
                reader = easyocr.Reader(['en'], gpu=True)
                result = reader.readtext(image_np, 
                                         text_threshold=0.5, 
                                         low_text=0.3, 
                                         link_threshold=0.3, 
                                         canvas_size=2560,
                                         mag_ratio=2.0, 
                                         decoder='beamsearch',
                                         allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ')

                results_no_preprocess = []
                allowed_letters = {'A', 'B', 'C', 'D', 'E'}
                for bbox, text, score in result:
                    if score < 0.3:
                        continue
                    text = re.sub(r'[^A-Za-z]', '', text)
                    if len(text) == 1 and text.upper() in allowed_letters:
                        results_no_preprocess.append((bbox, text.upper(), score))
                    elif len(text) == 2:
                        # 如果是两个字母，优先保留第二个如果它合法
                        second = text[1].upper()
                        if second in allowed_letters:
                            results_no_preprocess.append((bbox, second, score))
                    
                
                if len(results_no_preprocess) < 2: 
                    print("Detection result is not good! Try to add pre-processing...")
                    image_np = self.preprocess_image(image_path)
                    result = reader.readtext(image_np, 
                                             text_threshold=0.5, 
                                             low_text=0.3, 
                                             link_threshold=0.3, 
                                             canvas_size=2560,
                                             mag_ratio=2.0, 
                                             decoder='beamsearch',
                                             allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ')
                    results_preprocess = []
                    for bbox, text, score in result:
                        if score < 0.3:
                            continue
                        text = re.sub(r'[^A-Za-z]', '', text)
                        if len(text) == 1 and text.upper() in allowed_letters:
                            results_preprocess.append((bbox, text.upper(), score))
                        elif len(text) == 2:
                            second = text[1].upper()
                            if second in allowed_letters:
                                results_preprocess.append((bbox, second, score))
                    return results_preprocess
                    
                return results_no_preprocess

            except RuntimeError as e:
                if "CUDA out of memory" in str(e):
                    print(f"CUDA out of memory error on attempt {attempt + 1}.")
                    if clear_cuda_cache:
                        print("Clearing CUDA cache and retrying...")
                        torch.cuda.empty_cache()
                    else:
                        print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"Runtime error: {e}")
                    break
            except Exception as e:
                print(f"Error detecting letters: {e}")
                break
        
        print(f"Failed to detect letters after {max_retries} attempts.")
        return []

    def visualize_letter_results(self, image_path, results, save_path="output_filtered_letters.png"):
        img_color = cv2.imread(image_path, cv2.IMREAD_COLOR)

        for bbox, text, score in results:
            pts = np.array(bbox, dtype=np.int32)
            cv2.polylines(img_color, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
            cv2.putText(img_color, f"{text} ({score:.2f})", 
                        (pts[0][0], pts[0][1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

        plt.figure(figsize=(12, 8))
        plt.imshow(cv2.cvtColor(img_color, cv2.COLOR_BGR2RGB))
        plt.axis('off')
        plt.title('Filtered Letters: A-E only')
        plt.show()

        cv2.imwrite(save_path, img_color)
        print(f"Filtered image saved to: {save_path}")

    def execute(self, image, max_retries=10, retry_delay=5, clear_cuda_cache=False):
        """
        Executes the letter detection tool on the provided image.

        Parameters:
            image (str): The path to the image file.
            max_retries (int): Maximum number of retry attempts.
            retry_delay (int): Delay in seconds between retry attempts.
            clear_cuda_cache (bool): Whether to clear CUDA cache on out-of-memory errors.

        Returns:
            list: A list of detected letters with bounding box coordinates, recognized text, and confidence score.
        """
        try:
            results = self.detect_filtered_letters(image, max_retries, retry_delay, clear_cuda_cache)
            return results
        except Exception as e:
            print(f"Error executing letter detection: {e}")
            return []

    def get_metadata(self):
        metadata = super().get_metadata()
        return metadata   

if __name__ == "__main__":
    tool = Letter_Detector_Tool()

    image_path = "./examples/04.png"
    results = tool.execute(image=image_path, max_retries=10, retry_delay=5, clear_cuda_cache=False)
    tool.visualize_letter_results(image_path, results)

    print("\nDetected Letters:")
    for bbox, text, score in results:
        print(f"[{score:.2f}] {text} — bbox: {bbox}")

    print("Done!")
