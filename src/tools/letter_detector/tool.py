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
            output_types = "list - A list of detected letters with bounding box coordinates (relative to original image), recognized text, and confidence score.", # Clarified output
            demo_commands = [
                {
                    "command": "results = Letter_Detector_Tool.execute(image='path/to/image.png')",
                    "description": "Detect letters in an image, return the list of tuple (bbx, letter, and score). Bbox coordinates are relative to the original image.",
                    "output_example": '[[[100, 150], [200, 150], [200, 200], [100, 200]], "A", 0.95], ...]'
                }
            ],
            user_metadata = {
                "usage_scenarios": "This tool is very useful for locating specific regions labeled with letters in reference and target images."
            }
        )
        # Initialize reader once if possible, or handle potential GPU memory issues carefully
        # Consider initializing it in execute or making it lazy-loaded if memory is a concern
        # For simplicity here, we'll keep it in detect_filtered_letters but be aware of re-initialization
        # self.reader = easyocr.Reader(['en'], gpu=True) # Potential optimization


    def preprocess_image(self, image_path):
        img = cv2.imread(image_path)
        if img is None:
            print(f"Error: Could not read image at {image_path}")
            return None, 1.0 # Return None and scale 1 if image read fails

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Consider if histogram equalization is always beneficial, might enhance noise too
        eq = cv2.equalizeHist(gray)
        # Thresholding parameters might need tuning per image type
        bin_img = cv2.adaptiveThreshold(eq, 255,
                                        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY, # cv2.THRESH_BINARY_INV might be better sometimes
                                        15, 10)
        scale = 2.0 # Make it float for division later
        resized = cv2.resize(bin_img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        return resized, scale


    def detect_filtered_letters(self, image_path, max_retries=10, retry_delay=5, clear_cuda_cache=False):
        # It's generally better to initialize the reader once if the tool instance persists
        # If execute is called many times, this creates a new reader each time.
        # Consider moving reader initialization to __init__ if appropriate for your BaseTool usage
        try:
            reader = easyocr.Reader(['en'], gpu=True) # Or self.reader if initialized in __init__
        except Exception as e:
            print(f"Failed to initialize EasyOCR Reader: {e}")
            return []

        allowed_letters = {'A', 'B', 'C', 'D', 'E'}
        final_results = []
        scale_applied = 1.0 # Default scale is 1 (no scaling)

        for attempt in range(max_retries):
            try:
                # --- Attempt 1: No Preprocessing ---
                print(f"Attempt {attempt + 1}: Detecting on original image...")
                image_np_orig = cv2.imread(image_path, cv2.IMREAD_COLOR)
                if image_np_orig is None:
                     print(f"Error: Could not read image at {image_path} during detection.")
                     return []

                result_no_preprocess = reader.readtext(image_np_orig,
                                                     text_threshold=0.5,
                                                     low_text=0.3,
                                                     link_threshold=0.3,
                                                     canvas_size=2560,
                                                     mag_ratio=2.0,
                                                     decoder='beamsearch',
                                                     allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ')

                results_filtered_no_preprocess = []
                for bbox, text, score in result_no_preprocess:
                    if score < 0.3:
                        continue
                    text = re.sub(r'[^A-Za-z]', '', text)
                    if len(text) == 1 and text.upper() in allowed_letters:
                        results_filtered_no_preprocess.append((bbox, text.upper(), score))
                    elif len(text) == 2:
                        second = text[1].upper()
                        if second in allowed_letters:
                            results_filtered_no_preprocess.append((bbox, second, score))

                # --- Check if results are sufficient ---
                if len(results_filtered_no_preprocess) >= 2:
                    print("Sufficient results found without preprocessing.")
                    final_results = results_filtered_no_preprocess
                    scale_applied = 1.0 # Ensure scale is 1.0
                    break # Exit retry loop, we have good results

                # --- Attempt 2: With Preprocessing (if Attempt 1 failed) ---
                print("Detection result count low. Applying pre-processing...")
                image_np_processed, scale = self.preprocess_image(image_path)
                if image_np_processed is None:
                    print("Preprocessing failed.")
                    # Decide if you want to return empty or retry/fallback
                    # For now, let's break and return potentially empty results_filtered_no_preprocess
                    final_results = results_filtered_no_preprocess # Keep results from first attempt if any
                    scale_applied = 1.0
                    break

                result_preprocess = reader.readtext(image_np_processed,
                                                    text_threshold=0.5,
                                                    low_text=0.3,
                                                    link_threshold=0.3,
                                                    canvas_size=2560,
                                                    mag_ratio=2.0,
                                                    decoder='beamsearch',
                                                    allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ')

                results_filtered_preprocess = []
                for bbox, text, score in result_preprocess:
                    if score < 0.3:
                        continue
                    text = re.sub(r'[^A-Za-z]', '', text)
                    # --- *** Scale BBOX back to original coordinates *** ---
                    original_bbox = [[int(p[0] / scale), int(p[1] / scale)] for p in bbox]
                    # --- ******************************************* ---
                    if len(text) == 1 and text.upper() in allowed_letters:
                        results_filtered_preprocess.append((original_bbox, text.upper(), score))
                    elif len(text) == 2:
                        second = text[1].upper()
                        if second in allowed_letters:
                            results_filtered_preprocess.append((original_bbox, second, score))

                # Decide which result set is better or combine?
                # Current logic: If preprocess was run, always return its results.
                final_results = results_filtered_preprocess
                scale_applied = scale # Record the scale that was used
                print(f"Used preprocessed results with scale {scale_applied}.")
                break # Exit retry loop after successful preprocessing attempt

            except RuntimeError as e:
                if "CUDA out of memory" in str(e):
                    print(f"CUDA out of memory error on attempt {attempt + 1}.")
                    if clear_cuda_cache:
                        print("Clearing CUDA cache...")
                        del reader # Try deleting reader object
                        torch.cuda.empty_cache()
                        print("Re-initializing reader and retrying...")
                        # Re-initialize reader after clearing cache
                        try:
                            reader = easyocr.Reader(['en'], gpu=True)
                        except Exception as reinit_e:
                             print(f"Failed to re-initialize EasyOCR Reader after OOM: {reinit_e}")
                             return [] # Cannot continue if reader cannot be re-initialized
                    else:
                        print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue # Go to next attempt
                else:
                    print(f"Runtime error during detection: {e}")
                    # Consider if you should return [] or re-raise depending on tool requirements
                    return [] # Exit on other runtime errors
            except Exception as e:
                print(f"Error detecting letters on attempt {attempt + 1}: {e}")
                # Maybe retry on generic errors too? Or just break?
                # Let's retry after a delay for generic errors too for now
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                continue # Go to next attempt

        if attempt == max_retries - 1 and not final_results:
            print(f"Failed to detect letters after {max_retries} attempts.")

        # Clean up reader if it was created locally in this function?
        # If reader is a class member (self.reader), don't delete it here.
        if 'reader' in locals() and reader is not None:
             del reader
             if torch.cuda.is_available():
                 torch.cuda.empty_cache() # Good practice to clear cache when done

        return final_results # Always returns coordinates relative to original image


    # Visualization function now assumes coordinates are already relative to original image
    def visualize_letter_results(self, image_path, results, save_path="output_filtered_letters.png"):
        img_color = cv2.imread(image_path, cv2.IMREAD_COLOR)
        if img_color is None:
            print(f"Error: Could not read image for visualization: {image_path}")
            return

        if not results:
            print("No results to visualize.")
            # Optionally save the original image or do nothing
            # cv2.imwrite(save_path, img_color)
            return

        for bbox, text, score in results:
            # Bbox coordinates are now always relative to original image, no need to scale down
            try:
                # Ensure points are integers for drawing
                pts = np.array(bbox, dtype=np.int32)
                # Reshape for polylines if necessary (EasyOCR usually provides list of [x,y])
                pts = pts.reshape((-1, 1, 2))

                cv2.polylines(img_color, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
                # Put text near the top-left corner of the bbox
                text_origin_x = pts[0][0][0] # Top-left x
                text_origin_y = pts[0][0][1] - 10 # Top-left y, shifted up
                # Ensure text doesn't go off-screen (simple boundary check)
                text_origin_y = max(10, text_origin_y)

                cv2.putText(img_color, f"{text} ({score:.2f})",
                            (text_origin_x, text_origin_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            except Exception as e:
                print(f"Error drawing bounding box: {bbox}, Text: {text}, Error: {e}")
                # Continue trying to draw other boxes

        # Display using Matplotlib (optional)
        plt.figure(figsize=(12, 8))
        plt.imshow(cv2.cvtColor(img_color, cv2.COLOR_BGR2RGB))
        plt.axis('off')
        plt.title('Filtered Letters: A-E only (on Original Image)')
        plt.show()

        # Save the image
        try:
            cv2.imwrite(save_path, img_color)
            print(f"Filtered image saved to: {save_path}")
        except Exception as e:
            print(f"Error saving image to {save_path}: {e}")


    def execute(self, image, max_retries=10, retry_delay=5, clear_cuda_cache=False):
        """
        Executes the letter detection tool on the provided image.

        Parameters:
            image (str): The path to the image file.
            max_retries (int): Maximum number of retry attempts.
            retry_delay (int): Delay in seconds between retry attempts.
            clear_cuda_cache (bool): Whether to clear CUDA cache on out-of-memory errors.

        Returns:
            list: A list of detected letters with bounding box coordinates (relative to original image),
                  recognized text, and confidence score.
        """
        if not os.path.exists(image):
            print(f"Error: Image path does not exist: {image}")
            return []
        try:
            # detect_filtered_letters now always returns coordinates relative to the original image
            results = self.detect_filtered_letters(image, max_retries, retry_delay, clear_cuda_cache)
            # Convert bbox points to simple lists of [x, y] if they aren't already, for JSON compatibility etc.
            # EasyOCR usually returns list of lists, which is fine. Let's ensure consistency.
            final_results = []
            for bbox, text, score in results:
                 # Convert numpy arrays (if any point is numpy) to lists
                 list_bbox = [[int(p[0]), int(p[1])] for p in bbox]
                 final_results.append([list_bbox, text, score])

            return final_results
        except Exception as e:
            # Log the exception for debugging
            import traceback
            print(f"Error executing letter detection: {e}")
            print(traceback.format_exc()) # Print detailed traceback
            return []

    def get_metadata(self):
        metadata = super().get_metadata()
        return metadata   

if __name__ == "__main__":
    tool = Letter_Detector_Tool()

    image_path = "./examples/08.png"
    results = tool.execute(image=image_path, max_retries=10, retry_delay=5, clear_cuda_cache=False)
    tool.visualize_letter_results(image_path, results)

    print("\nDetected Letters:")
    for bbox, text, score in results:
        print(f"[{score:.2f}] {text} — bbox: {bbox}")

    print("Done!")
