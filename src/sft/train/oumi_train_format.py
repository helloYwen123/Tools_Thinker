import json
import re
import os


system_prompt = """
You are a helpful assistant who is good at solving vision-based spatial problems with code step by step. You need generate Python program within <code></code> tags to answer question based on given tools module. The output of the program is used to answer the question. 
Feel free to select and combine the tools that are most suitable for solving the task.
Available Tools List:  Object_Detector_Tool, Text_Detector_Tool, Depth_Estimator_Tool, Segmenter_Tool, Matcher_Tool
Tools Metadata(Dict):  {'Object_Detector_Tool': {'tool_module_name': 'object_detector', 'tool_class_name': 'Object_Detector_Tool', 'tool_description': 'A tool that detects objects in an image.', 'input_types': {'image': 'str - The path to the image file.', 'labels': 'list - A list of object labels to detect.', 'save_object': 'bool - Whether to save the detected objects as `png` images (default: False).', 'saved_image_path': "str - The path to save the detected object `png` images (default: 'detected_objects').", 'save_json': 'bool - Whether to save detection results as a JSON file (default: False).', 'json_path': "str - The file path to save the JSON results if `save_json` is True (default: 'detection_results.json')."}, 'output_types': "a dictionary mapping each detected label to a list of detection entries e.g. {'baseball': [{'box': (xmin, ymin, xmax, ymax), 'score': 0.95, 'saved_image_path': 'path/to/saved/image.png','cropped_image': <PIL.Image.Image> }, ...]}. Note: the `box` is provided in `xyxy`(left-top, right-bottom) format and 'cropped_image' is object image in <PIL.Image.Image> format.\n", 'demo_commands': {'command': "object_detector_tool = Object_Detector_Tool()\ndetected_objects = object_detector_tool.execute(image='path/to/image', labels=['baseball', 'basket'] ,save_object=True, saved_image_path='detected_objects')\n", 'output_example': "detected_objects : {\n'baseball': [{'box':<tuple>,'score': <float>,'saved_image_path':<str>,'cropped_image':<PIL.Image.Image>}],\n'basket': [{'box':<tuple>,'score': <float>,'saved_image_path':<str>,'cropped_image' <PIL.Image.Image>}]\n}\n"}, 'user_metadata': {'potential usage': 'The bounding box obtained by tool can be used to determine precise object regions and pixel-level coordinates, enabling integration with downstream tasks such as depth estimation, object segmentation, or regions localization for sparse matching.\n'}}, 'Text_Detector_Tool': {'tool_module_name': 'text_detector', 'tool_class_name': 'Text_Detector_Tool', 'tool_description': 'A tool that detects text in an image.', 'input_types': {'image': 'str - The path to the image file.', 'languages': 'list - A list of language codes for the OCR model.', 'detail': 'int - The level of detail in the output. Set to 0 for simpler output, 1 for detailed output.'}, 'output_types': "list - A list of detected text blocks. Each block contains the four anchor coordinates of the bounding box, the recognized text, and the confidence score (float). e.g. [[[[x0, y0], [x1, y1], [x2, y2], [x3, y3]], 'Detected text', score], ...].\n", 'demo_commands': {'command': "text_detector_tool = Text_Detector_Tool()\nresult = text_detector_tool.execute(image='path/to/image', languages=['en', 'de'])\n", 'output_example': 'result: [<list[list]>, <str>, <float>], ...]'}, 'user_metadata': {'frequently_used_language': {'ch_sim': 'Simplified Chinese', 'de': 'German', 'en': 'English', 'ja': 'Japanese'}, 'important_note': 'The text detector may return additional text beyond the correct result. Make sure to extract the required text according to your needs.\n'}}, 'Depth_Estimator_Tool': {'tool_module_name': 'depth_estimator', 'tool_class_name': 'Depth_Estimator_Tool', 'tool_description': 'A tool that estimates pixel-level depth from image.', 'input_types': {'image_path': 'list[str] - The list of path to a single or several input images.', 'output': 'bool - If True, save the depth image (default: False).', 'outdir': "str - The output directory to save the depth images (default: './vis_depth')."}, 'output_types': "image_results: dict - A dictionary containing the depth maps for each input image. Each key is the input `image_path`(str) and the corresponding value is a dictionary with keys: e.g. 'assets/image1.jpg': {'depth_map': <numpy array with shape (H, W)>, 'output_image_path': 'path/to/saved/image.png'} # Note that in the depth map, larger pixel values represent greater depth (i.e., further from the camera).\n", 'demo_commands': {'command': "depth_estimator_tool = Depth_Estimator_Tool()\nimage_results = depth_estimator_tool.execute(image_path=['path/to/image1', 'path/to/image2'], output=True, outdir= './vis_depth')\n", 'output_example': "image_results: {'assets/image1.jpg': {'depth_map': <numpy array with shape (H, W)>, 'output_image_path': <str>},\n'assets/image2.jpg': {'depth_map': <numpy array with shape (H, W)>, 'output_image_path': <str>}}\n"}}, 'Segmenter_Tool': {'tool_module_name': 'segmenter', 'tool_class_name': 'Segmenter_Tool', 'tool_description': 'A segmentation tool is capable of accurately localizing specific objects at the pixel level using specific prompts(e.g., points or boxes).\n', 'input_types': {'prompt_type': "str: 'points' or 'boxes'.", 'input_prompts': "list[dict] - list of dicts each with an `image_path` key (str) and a prompt key based on the prompt_type. For the 'points' prompt type, prompt key should be 'input_points', a list of [x, y] coordinates with at least two points. For the 'boxes' prompt type, prompt key should be 'input_box', a list of bounding boxes in `xyxy` format (i.e., [xmin, ymin, xmax, ymax]).\n", 'model_size': "str: SAM2 model size, e.g., 'base_plus' or 'small' (default: 'small')."}, 'output_types': 'masks: np.ndarray or list[np.ndarray] - For a single image input, the output is a numpy array, each of shape (O, 1, H, W), where `O` denotes the number of objects to be segmented. For batch input, the output is a list of length N (number of input images), where each element is a numpy array for the corresponding image, with each set having shape (O, 1, H, W), where `O` represents the number of objects to segment in the image. # Note that in these output masks, pixels set to 1 represent the region of the segmented object.\n', 'demo_commands': {'command': "segmenter_tool = Segmenter_Tool()\nmasks = segmenter_tool.execute(prompt_type='boxes', input_prompts=[{'image_path': 'path/to/image1', 'input_box': [[100,150,400,500]]}, {'image_path': 'path/to/image2', 'input_box': [[50,80,300,350]]}], model_size='small')\n", 'output_example': 'masks: list[np.ndarray] - [mask_image1, mask_image2] # Example: mask_image1.shape -> (1, 1, Height1, Width1), mask_image2.shape -> (1, 1, Height2, Width2), where each mask matches the original image in height and width.\n', 'user_metadata': 'Before using the segmentation tools, it is advisable to consider how to obtain the points and bounding box coordinates for the visual prompt.'}}, 'Matcher_Tool': {'tool_module_name': 'matcher', 'tool_class_name': 'Matcher_Tool', 'tool_description': 'A tool that computes global semantic similarity and identifies corresponding local features among images.', 'input_types': {'matching_type': "str - 'global_match' or 'local_match'. (Default is 'global_match')", 'ref_img': 'list[str] - The list of paths to one reference image file.', 'candidate_img': 'list[str] - The list of paths to the candidate imagesfile.', 'ref_bbox': "list[list] - required for 'local_match' matching type, a list of 2 corner points of box representting a region in the reference image to be matched , in the format [[xmin, ymin], [xmax, ymax]].", 'candidate_bbox': "list[list] - required for 'local_match' matching type, a list of bounding boxes in the candidate image, each defined by 2 corner points coordinates [[xmin, ymin], [x2, y3]], the most similar box to the reference box will be selected.", 'output_types': "int - if 'matching_type' is 'global_match', return the best matching image idx in list of `candidate_img`. if 'matching_type' is 'local_match', return the best matching bounding box idx in `candidate_bbox`.\n", 'demo_commands': {'command(1)': "matcher_tool = Matcher_Tool()\nmatched_idx = matcher_tool.execute(matching_type='global_match', ref_img=['/path/to/ref.jpg'], candidate_img=['/path/to/candidate1.jpg', '/path/to/candidate2.jpg', '/path/to/candidate3.jpg'])\n", 'output_example': 'matched_idx = 1  # That means `candidate_img[1]` is the best matching image.', 'command(2)': "matcher_tool = Matcher_Tool()\nmatched_idx = matcher_tool.execute(matching_type='local_match', ref_img=['/path/to/ref.jpg'], candidate_img=['/path/to/candidate.jpg'], ref_bbox=[[[xmin, ymin], [x2, y2]]], candidate_bbox=[[[xmin, ymin], [xmax, ymax]],...])])\n", 'output_example(2)': 'matched_idx: 0 # That means the `candidate_bbox[0]` is the best matching one.'}}}}

Details and Rules:
1. Use correct provided image paths.
2. Use the `tool_module_name` and `tool_class_name` fields from each tool's metadata to import the correct module and class.
3. Assign the final answer for question to a variable named `final_result` within the Python code. 
"""

def convert_to_chat_format(input_json_path, output_json_path):
    with open(input_json_path, 'r') as f:
        data = json.load(f)

    with open(output_json_path, 'w') as f_out:
        for entry in data:
            image_paths = entry['image']
            question = entry['question']
            question = question.lower()
            
            # concatenate image paths info to promt
            image_info_text = "The inputs image paths:\n" + "\n".join([f"`{p}`" for p in image_paths])
            full_question = f"{question}\n{image_info_text}"

            # 提取最后的 code_ex
            code_keys = sorted([k for k in entry.keys() if k.startswith("code_ex")],
                               key=lambda x: int(re.findall(r'\d+', x)[0]))
            final_code = entry[code_keys[-1]].strip()

            # 构建 content：多个 image_path + 一个 text
            user_content = [{"type": "image_path", "content": p} for p in image_paths]
            user_content.append({"type": "text", "content": full_question})
            ground_truth = entry["GT"]
            chat_entry = {
                "conversation_id": entry["QAid"],
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": user_content
                    },
                    {
                        "role": "assistant",
                        "content": final_code
                    }
                ],
                "metadata": {"ground_truth": ground_truth}
            }

            f_out.write(json.dumps(chat_entry) + '\n')
#
json_path = "/nfs/data8/liao/syang/sft_data/only_acc/final_clevr_sat/clevr_sat_acc_all.json"
name = os.path.splitext(os.path.basename(json_path))[0]
convert_to_chat_format(json_path, f"json_files/oumi_{name}_success_traj.jsonl")
