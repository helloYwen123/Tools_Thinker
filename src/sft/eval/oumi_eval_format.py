import json

system_prompt = """You are a helpful AI assistant. You need generate Python program within <code></code> tags to answer question based on given tools module. The output of the program is used to answer the question.\n\nFeel free to select and combine the tools that are most suitable for solving the task.\nAvailable Tools List:  Object_Detector_Tool, Text_Detector_Tool, Depth_Estimator_Tool, Segmenter_Tool, Matcher_Tool\nTools Metadata(Dict):  {'Object_Detector_Tool': {'tool_module_name': 'object_detector', 'tool_class_name': 'Object_Detector_Tool', 'tool_description': 'A tool that detects objects in an image using the Grounding DINO model and saves individual object images with empty padding.', 'input_types': {'image': 'str - The path to the image file.', 'labels': 'list - A list of object labels to detect.', 'model_size': "str - The size of the model to use ('tiny' or 'base', default: 'tiny').", 'threshold': 'float - The confidence threshold for detection (default: 0.35).', 'save_object': 'bool - Whether to save the detected objects as images (default: False).', 'saved_image_path': "str - The path to save the detected object images (default: 'detected_objects').", 'save_json': 'bool - Whether to save detection results as a JSON file (default: False).', 'json_path': "str - The file path to save the JSON results if `save_json` is True (default: 'detection_results.json')."}, 'output_types': "a dictionary mapping each detected label to a list of detection entries e.g. {'baseball': [{'box': (x1, y1, x2, y2), 'score': 0.95, 'saved_image_path': 'path/to/saved/image.png'}, ...]}. Note that the the box in dictionary is provided in `xyxy` format.\n", 'demo_commands': {'command': 'object_detector_tool = Object_Detector_Tool()\ndetected_objects = object_detector_tool.execute(image=\'path/to/image\', labels=[\'baseball\', \'basket\'] ,model_size="tiny" ,save_object=True, saved_image_path=\'detected_objects\')\n', 'description': 'Detects \'baseball\' and \'basket\' in the image. Returns a dictionary: (1) a dict mapping each label to a list of detection results (each with box, score, and optionally saved image path); If \'save_object\' is True, detected objects are cropped and saved to the specified directory."\n', 'output_example': "detected_objects : {\n'baseball': [{'box': (34, 50, 200, 220), 'score': 0.92, 'saved_image_path': 'detected_objects/image_baseball_1.png'}],\n'basket': [{'box': (220, 100, 400, 350), 'score': 0.85, 'saved_image_path': 'detected_objects/image_basket_1.png'}]\n}\n"}, 'user_metadata': {'potential usage': 'The bounding box obtained by tool can be used to determine precise object regions and pixel-level coordinates, enabling integration with downstream tasks such as depth estimation, object segmentation, or regions localization for sparse matching.\n'}}, 'Text_Detector_Tool': {'tool_module_name': 'text_detector', 'tool_class_name': 'Text_Detector_Tool', 'tool_description': 'A tool that detects text in an image using EasyOCR.', 'input_types': {'image': 'str - The path to the image file.', 'languages': 'list - A list of language codes for the OCR model.', 'detail': 'int - The level of detail in the output. Set to 0 for simpler output, 1 for detailed output.'}, 'output_types': "list - A list of detected text blocks. Each block contains the bounding box coordinates, the recognized text, and the confidence score (float). e.g. [[[[x0, y0], [x1, y1], [x2, y2], [x3, y3]], 'Detected text', score], ...]. An empty list is returned if text detection fails after retries.\n", 'demo_commands': {'command': "text_detector_tool = Text_Detector_Tool()\nresult = text_detector_tool.execute(image='path/to/image', languages=['en', 'de'])\n", 'description': 'Detect text in an image using multiple languages (English and German), including coordinates(provided with box in `xyxy` format) and confidence scores.', 'output_example': "result: [[[[100, 150], [200, 150], [200, 200], [100, 200]], 'Detected text', 0.95], ...]"}, 'user_metadata': {'frequently_used_language': {'ch_sim': 'Simplified Chinese', 'de': 'German', 'en': 'English', 'ja': 'Japanese'}, 'important_note': 'The text detector may return additional text beyond the correct result. Make sure to extract the required text according to your needs.\n'}}, 'Depth_Estimator_Tool': {'tool_module_name': 'depth_estimator', 'tool_class_name': 'Depth_Estimator_Tool', 'tool_description': 'A tool that estimates pixel-level depth from image or video, which is useful for distance estimation.', 'input_types': {'mode': "str - The mode of operation, either 'image' or 'video' (default='image').", 'image_path': 'list[str] - The list of path to a single or several input images.', 'video_path': 'list[str] - The list of path to a single or severatl input videos', 'output': 'bool - If True, save the depth image or depth video (default: False).', 'outdir': "str - The output directory to save the depth images/videos (default: './vis_depth')."}, 'output_types': "image_results: dict - A dictionary containing the depth maps for each input image. Each key is the input `image_path`(str) and the corresponding value is a dictionary with keys: e.g. 'assets/image1.jpg': {'depth_map': <numpy array with shape (H, W)>, 'output_image_path': 'path/to/saved/image.png'} # Note that in the depth map, larger pixel values represent greater depth (i.e., further from the camera). video_results: dict - A dictionary containing the depth maps for each input video. Each key is the input `video_path`(str) and the corresponding value is a dictionary with keys: e.g. 'assets/video1.mp4': {'video_depth_map': <list of numpy arrays with shape (H, W)>, 'output_video_path': 'path/to/saved/video.mp4'} # Note that in the depth map, larger pixel values represent greater depth (i.e., further from the camera).\n", 'demo_commands': {'command': "depth_estimator_tool = Depth_Estimator_Tool()\nimage_results = depth_estimator_tool.execute(image_path=['path/to/image1', 'path/to/image2'], output=True, outdir= './vis_depth')\n", 'description': 'Processes a list of input images, estimates their depth maps, and returns genereated depth images paths.', 'output_example': "image_results: {'assets/image1.jpg': {'depth_map': <numpy array with shape (H, W)>, 'output_image_path': './vis_depth/image1.png'},\n'assets/image2.jpg': {'depth_map': <numpy array with shape (H, W)>,'output_image_path': './vis_depth/image2.png'}}\n"}}, 'Segmenter_Tool': {'tool_module_name': 'segmenter', 'tool_class_name': 'Segmenter_Tool', 'tool_description': 'A segmentation tool based on the SAM2 model, capable of accurately localizing specific objects at the pixel level using specific prompts(e.g., point lists or boxes).\n', 'input_types': {'prompt_type': "str: 'points' or 'boxes'.", 'input_prompts': "list[dict] - list of dicts each with an `image_path` key (str) and a prompt key (str) based on the prompt_type. For the 'points' prompt type, prompt key should be 'input_points', a list of [x, y] coordinates with at least two points. For the 'boxes' prompt type, prompt key should be 'input_box', a list of bounding boxes in `xyxy` format (i.e., [x1, y1, x2, y2]).\n", 'model_size': "str: SAM2 model size, e.g., 'base_plus' or 'small' (default: 'small')."}, 'output_types': 'masks: np.ndarray or list[np.ndarray] - For a single image input, the output is a numpy array, each of shape (O, 1, H, W), where `O` denotes the number of objects to be segmented. For batch input, the output is a list of length N (number of input images), where each element is a numpy array for the corresponding image, with each set having shape (O, 1, H, W), where `O` represents the number of objects to segment in the image. # Note that in these output masks, pixels set to 1 represent the region of the segmented object.\n', 'demo_commands': {'command': "segmenter_tool = Segmenter_Tool()\nmasks = segmenter_tool.execute(prompt_type='boxes', input_prompts=[{'image_path': 'path/to/image1', 'input_box': [[100,150,400,500]]}, {'image_path': 'path/to/image2', 'input_box': [[50,80,300,350]]}], model_size='small')\n", 'description': 'Batch segmentation for multiple images using box-based input. Each image returns its segmentation mask as a numpy array.', 'output_example': 'masks: list[np.ndarray] - [mask_image1, mask_image2] # Example: mask_image1.shape -> (1, 1, H1, W1), mask_image2.shape -> (1, 1, H2, W2), where each mask is a numpy array representing the segmentation result.\n', 'user_metadata': 'Before using the segmentation tools, it is advisable to consider how to obtain the points and bounding box coordinates for the visual prompt.'}}, 'Matcher_Tool': {'tool_module_name': 'matcher', 'tool_class_name': 'Matcher_Tool', 'tool_description': 'A tool that computes global semantic similarity and identifies corresponding local features between a reference image and a candidate image, given bounding boxes as inputs.', 'input_types': {'matching_type': "str - 'global_match' or 'local_match'. (Default is 'global_match')", 'ref_img': 'list[str] - The list of paths to one reference image file.', 'candidate_img': 'list[str] - The list of paths to the candidate imagesfile.', 'ref_bbox': "list[list] - required for 'local_match' matching type, a list of 2 corner points of box representting a region in the reference image to be matched , in the format [[x1, y1], [x2, y2]].", 'candidate_bbox': "list[list] - required for 'local_match' matching type, a list of bounding boxes in the candidate image, each defined by 2 corner points coordinates [[x1, y1], [x2, y3]], the most similar box to the reference box will be selected.", 'output_types': "int - if 'matching_type' is 'global_match', return the best matching image idx in list of `candidate_img`. if 'matching_type' is 'local_match', return the best matching bounding box idx in `candidate_bbox`.\n", 'demo_commands': {'command(1)': "matcher_tool = Matcher_Tool()\nmatched_idx = matcher_tool.execute(matching_type='global_match', ref_img=['/path/to/ref.jpg'], candidate_img=['/path/to/candidate1.jpg', '/path/to/candidate2.jpg', '/path/to/candidate3.jpg'])\n", 'description': '`global_match` matching type is enabled: given one reference image and multiple candidate images, this command computes global semantic or style similarity  and returns the index of the best matching candidate image\n', 'output_example': 'matched_idx = 1  # That means `candidate_img[1]` is the best matching image.', 'command(2)': "matcher_tool = Matcher_Tool()\nmatched_idx = matcher_tool.execute(matching_type='local_match', ref_img=['/path/to/ref.jpg'], candidate_img=['/path/to/candidate.jpg'], ref_bbox=[[[x1, y1], [x2, y2]]], candidate_bbox=[[[x1, y1], [x2, y2]]]])\n", 'description(2)': 'local_match` matching_type is enabled: Given one reference image and one candidate image with bounding boxes,this command computes local feature correspondence and returns the index of the best matching bounding box in candidate_bbox.\n', 'output_example(2)': 'matched_idx: 0 # That means the `candidate_bbox[0]` is the best matching one.'}}}}\nDetails and Rules:\n1. Use correct image paths\n2. Use the `tool_module_name` and `tool_class_name` fields from each tool's metadata to import the correct module and class\n3. Assign the final answer for question to a variable named `final_result` within the Python code.\n4. Feel free to select and combine the tools that are most suitable for solving the task."""

def convert_to_chat_format(input_json_path, output_json_path):
    with open(input_json_path, 'r') as f:
        data = json.load(f)
    with open(output_json_path, 'w') as f_out:
        # for entry in data:
        #     image_paths = entry['image']
        #     question = entry['question']

        #     # 拼接 image paths info 到文本中
        #     image_info_text = "The inputs image paths:\n" + "\n".join([f"`{p}`" for p in image_paths])
        #     full_question = f"{question}\n{image_info_text}"

        #     # 构建 content：多个 image_path + 一个 text
        #     user_content = [{"type": "image_path", "content": p} for p in image_paths]
        #     user_content.append({"type": "text", "content": full_question})
        #     ground_truth = entry["GT"]
        #     chat_entry = {
        #         "conversation_id" : entry["QAid"],
        #         "messages": [
        #             {
        #                 "role": "system",
        #                 "content": system_prompt
        #             },
        #             {
        #                 "role": "user",
        #                 "content": user_content
        #             },
        #         ],
        #         "metadata": {"ground_truth": ground_truth}
        #     }
        data_prefix = "/home/stud/wxie/"
        for entry in data[:]:
            image_paths = entry['image_paths']
            question = entry['prompt']
            # question = question.replace("<image> Answer in natural language. ", "")
            # 拼接 image paths info 到文本中
            image_info_text = "The inputs image paths:\n" + "\n".join([f"`{data_prefix+p}`" for p in image_paths])
            full_question = f"{question}\n{image_info_text}"

            # 构建 content：多个 image_path + 一个 text
            
            user_content = [{"type": "image_path", "content": data_prefix+p} for p in image_paths]
            user_content.append({"type": "text", "content": full_question})
            letter_to_index = {
                "(A)": 0,
                "(B)": 1,
                "(C)": 2,
                "(D)": 3
            }
            ground_truth = letter_to_index[entry['answer']]
            chat_entry = {
                #"conversation_id" : image_paths[0].split("/")[-1].split(".")[0],
                "conversation_id" : entry['idx'],
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": user_content
                    },
                ],
                "metadata": {"ground_truth": ground_truth}
            }
            f_out.write(json.dumps(chat_entry) + '\n')

# 用法
convert_to_chat_format("/home/stud/wxie/BLINK_Dataset/Counting/val/Counting_val.json", "oumi_eval_traj.jsonl")
