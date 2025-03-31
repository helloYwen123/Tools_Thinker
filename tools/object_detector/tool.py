# Grounding DINO Object Detection Tool
# https://huggingface.co/IDEA-Research/grounding-dino

import sys
import os
import time
import torch
from transformers import pipeline
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, root_dir)
from basetool import BaseTool
from PIL import Image, ImageOps

import os
# If CUDA_HOME is set, print the value
# print(os.environ.get('CUDA_HOME', 'CUDA_HOME is not set'))

# Suppress stderr by redirecting it to /dev/null
import sys
# sys.stderr = open(os.devnull, 'w')



class Object_Detector_Tool(BaseTool):
    def __init__(self):
        super().__init__(
            tool_module_name="object_detector",
            tool_class_name="Object_Detector_Tool",
            tool_description="A tool that detects objects in an image using the Grounding DINO model and saves individual object images with empty padding.",
            tool_version="1.0.0",
            input_types={
                "image": "str - The path to the image file.",
                "labels": "list - A list of object labels to detect.",
                "threshold": "float - The confidence threshold for detection (default: 0.45).",
                "model_size": "str - The size of the model to use ('tiny' or 'base', default: 'tiny').",
                "save_object": "bool - Whether to save the detected objects as images (default: False).",
                "saved_image_path": "str - The path to save the detected object images (default: 'detected_objects').",
            },
            output_types = "tuple - A tuple containing two elements: \
                            (1) a dictionary mapping each detected label to its grouped detection results, \
                            where each value is a dictionary with keys 'boxes', 'confidence_scores', and 'saved_image_paths'; \
                            (2) a dictionary mapping each label to its total count in the image.",
            demo_commands=[
                {
                    "command": 'detected_objects, object_number = Object_Detector_Tool.execute(image="path/to/image.png", labels=["baseball", "basket"], save_object=True, saved_image_path="detected_objects")',
                    "description": (
                            "Detects 'baseball' and 'basket' in the image. "
                            "Returns a tuple: (1) a dictionary grouping results by label with boxes, scores, and image paths; "
                            "(2) a dictionary with counts for each label. "
                            "Detected objects are saved to 'detected_objects' if 'save_object' is True."
                        )
                },
            ],
            user_metadata={
                "limitation": "The model may not always detect objects accurately.",
                "potential usage": "The tool can be used for locating interest-objects in images."
            }
        )

    def preprocess_caption(self, caption):
        result = caption.lower().strip()
        if result.endswith("."):
            return result
        return result + "."

    def build_tool(self, model_size='tiny'):
        model_name = f"IDEA-Research/grounding-dino-{model_size}"
        device = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            pipe = pipeline(model=model_name, task="zero-shot-object-detection", device=device)
            return pipe
        except Exception as e:
            print(f"Error building the Object Detection tool: {e}")
            return None

    def save_detected_object(self, image, box, image_name, label, index, padding):
        object_image = image.crop(box)
        padded_image = ImageOps.expand(object_image, border=padding, fill='white')
        
        filename = f"{image_name}_{label}_{index}.png"
        os.makedirs(self.output_dir, exist_ok=True)
        save_path = os.path.join(self.output_dir, filename)
        
        padded_image.save(save_path)
        return save_path

    def execute(self, image, labels, threshold=0.45, model_size='tiny', max_retries=10, retry_delay=2, clear_cuda_cache=False, save_object=False, saved_image_path="./objects_images"):
        
        # default padding value
        padding=20
        for attempt in range(max_retries):
            try:
                self.output_dir = saved_image_path

                pipe = self.build_tool(model_size)
                if pipe is None:
                    raise ValueError("Failed to build the Object Detection tool.")
                
                preprocessed_labels = [self.preprocess_caption(label) for label in labels]
                results = pipe(image, candidate_labels=preprocessed_labels, threshold=threshold)
                
                original_image = Image.open(image)
                image_name = os.path.splitext(os.path.basename(image))[0]
                
                object_counts = {}
                grouped_results = {}
                for result in results:
                    # pick box， label, and score
                    box = tuple(result["box"].values())
                    label = result["label"]
                    score = round(result["score"], 2)
                    if label.endswith("."):
                        label = label[:-1]
                    
                    object_counts[label] = object_counts.get(label, 0) + 1
                    index = object_counts[label]
                    
                    save_path = None
                    if save_object:
                        save_path = self.save_detected_object(original_image, box, image_name, label, index, padding)
                    
                    if label not in grouped_results:
                        grouped_results[label] = {
                            "boxes": [],
                            "confidence_scores": [],
                            "saved_image_paths": [],
                        }
                    # label is the key，box, score, and save_path are the values
                    grouped_results[label]["boxes"].append(box)
                    grouped_results[label]["confidence_scores"].append(score)
                    grouped_results[label]["saved_image_paths"].append(save_path)


                return grouped_results, object_counts
            
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
                print(f"Error detecting objects: {e}")
                break
        
        print(f"Failed to detect objects after {max_retries} attempts.")
        return []

    def get_metadata(self):
        metadata = super().get_metadata()
        return metadata

if __name__ == "__main__":
    # Test command:
    """
    Run the following commands in the terminal to test the script:
    
    cd octotools/tools/object_detector
    python tool.py
    """

    # Get the directory of the current script
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Example usage of the Object_Detector_Tool
    tool = Object_Detector_Tool()

    # Get tool metadata
    metadata = tool.get_metadata()
    print(metadata)

    # Construct the full path to the image using the script's directory
    relative_image_path = "examples/baseball.png"
    image_path = os.path.join(script_dir, relative_image_path)

    # Execute the tool
    try:
        objs, labels_num = tool.execute(image=image_path, labels=["baseball", "basket"], save_object=True, saved_image_path="detected_objects")
        print("Detected Objects:")
        for obj in objs:
            print(f"Detected {obj['label']} with confidence {obj['confidence score']}")
            print(f"Bounding box: {obj['box']}")
            print(f"Saved image (with padding): {obj['saved_image_path']}")
            print()
    except ValueError as e: 
        print(f"Execution failed: {e}")

    print("Done!")