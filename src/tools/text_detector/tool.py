import os
import sys
import time
import cv2
import numpy as np
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, root_dir)
from basetool import BaseTool
import torch
import warnings
warnings.filterwarnings("ignore")

class Text_Detector_Tool(BaseTool):
    def __init__(self):
        super().__init__(
            tool_module_name="text_detector",
            tool_class_name="Text_Detector_Tool",
            tool_description="A tool that detects text in an image using EasyOCR.",
            tool_version="1.0.0",
            input_types={
                "image": "str - The path to the image file.",
                "languages": "list - A list of language codes for the OCR model.",
                "detail": "int - The level of detail in the output. Set to 0 for simpler output, 1 for detailed output."
            },
            output_types="list - A list of detected text blocks. \
                Each block contains the bounding box coordinates, the recognized text, and the confidence score (float). \
                e.g. [[[[x0, y0], [x1, y1], [x2, y2], [x3, y3]], 'Detected text', score], ...] ",
            demo_commands=[
                {
                    "command": 'result = Text_Detector_Tool.execute(image="path/to/image.png", languages=["en", "de"])',
                    "description": "Detect text in an image using multiple languages (English and German), including coordinates and confidence scores.",
                    "output_example":  '[[[[100, 150], [200, 150], [200, 200], [100, 200]], "Detected text", 0.95], ...]',
                },
            ],
            user_metadata={
                "frequently_used_language": {
                    "ch_sim": "Simplified Chinese",
                    "de": "German",
                    "en": "English",
                    "ja": "Japanese",
                },
                 "important_note": "The text detector may return additional text beyond the correct result. \
                                    Make sure to extract the required text according to your needs instead of using everything directly. \
                                    e.g. for bbox, text, score in results:\n if text == whatyouneed:\n then pick it",
            }
        )

    def build_tool(self, languages=None):
        """
        Builds and returns the EasyOCR reader model.

        Parameters:
            languages (list): A list of language codes for the OCR model.

        Returns:
            easyocr.Reader: An initialized EasyOCR Reader object.
        """
        languages = languages or ["en"]  # Default to English if no languages provided
        try:
            import easyocr
            reader = easyocr.Reader(languages)
            return reader
        except ImportError:
            raise ImportError("Please install the EasyOCR package using 'pip install easyocr'.")
        except Exception as e:
            print(f"Error building the OCR tool: {e}")
            return None
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
    
    def execute(self, image, languages=None, max_retries=10, retry_delay=5, clear_cuda_cache=False, **kwargs):
        """
        Executes the OCR tool to detect text in the provided image.

        Parameters:
            image (str): The path to the image file.
            languages (list): A list of language codes for the OCR model.
            max_retries (int): Maximum number of retry attempts.
            retry_delay (int): Delay in seconds between retry attempts.
            clear_cuda_cache (bool): Whether to clear CUDA cache on out-of-memory errors.
            **kwargs: Additional keyword arguments for the OCR reader.

        Returns:
            list: A list of detected text blocks.
        """
        languages = languages or ["en"]

        for attempt in range(max_retries):
            try:
                reader = self.build_tool(languages)
                if reader is None:
                    raise ValueError("Failed to build the OCR tool.")
                image = self.preprocess_image(image)
                result = reader.readtext(image, **kwargs)
                try:
                    # detail = 1: Convert numpy types to standard Python types
                    cleaned_result = [
                        ([[int(coord[0]), int(coord[1])] for coord in item[0]], item[1], round(float(item[2]), 2))
                        for item in result
                    ]
                    return cleaned_result
                except Exception as e:
                    # detail = 0
                    return result

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
                print(f"Error detecting text: {e}")
                break
        
        print(f"Failed to detect text after {max_retries} attempts.")
        return []

    def get_metadata(self):
        """
        Returns the metadata for the Text_Detector_Tool.

        Returns:
            dict: A dictionary containing the tool's metadata.
        """
        metadata = super().get_metadata()
        return metadata

if __name__ == "__main__":
    # Test command:
    """
    Run the following commands in the terminal to test the script:
    
    cd octotools/tools/text_detector
    python tool.py
    """
    import json

    # Get the directory of the current script
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Example usage of the Text_Detector_Tool
    tool = Text_Detector_Tool()

    # Get tool metadata
    metadata = tool.get_metadata()
    # print(metadata)

    # Construct the full path to the image using the script's directory
    # relative_image_path = "examples/chinese_tra.jpg"
    # relative_image_path = "examples/chinese.jpg"
    relative_image_path = "./examples/english.png"
    image_path = os.path.join(script_dir, relative_image_path)

    # Execute the tool
    try:
        execution = tool.execute(image=image_path, languages=['en'], detail=0)
        # execution = tool.execute(image=image_path, languages=["en", "ch_tra"])
        # execution = tool.execute(image=image_path, languages=["ch_tra"])
        print(json.dumps(execution))

        print("Detected Text:", execution)
    except ValueError as e:
        print(f"Execution failed: {e}")

    print("Done!")
