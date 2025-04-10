 PROMPT_TEMPLATE = conf.get("prompt_template")
    # for Blink Dataset
    def make_conversation_sat(example, prefix,
                        available_tools_str: str,
                        filtered_metadata_str: str,
                        base_model_prompt=False):
        # get answer
        answer = example["answer"].strip("()")
        image_paths = [os.path.join(prefix, img_path) for img_path in example["image_paths"]]
        images = [Image.open(path) for path in image_paths ]
        idx = example["idx"] 
        
         # Format the final prompt text using the provided strings
        formatted_question_part = PROMPT_TEMPLATE.format(
        question=example["prompt"],
        image_paths=", ".join(image_paths),
        available_tools=available_tools_str,        # Use the pre-formatted string
        toolbox_metadata=filtered_metadata_str      # Use the filtered metadata string
        )
        
        if base_model_prompt:
            prompt = f"""A conversation between User and Assistant. 
            The user asks a question about the image, and the Assistant solves it. 
            The assistant first thinks about the reasoning process in the mind and then provides the user with the answer.
            \nUser: {formatted_question_part} \nAssistant: <command>"""
            message_content = [ {"type": "image"} for _ in images ]
            message_content.append({
                "type": "text" , "text": "<image>" + prompt
            })
            idx = example["idx"]
            return {"image": images, # images
                "prompt": message_content,
                "solution": answer,  ###
                "QAid": idx
            }
        else:
            image_paths = [os.path.join(prefix, img_path) for img_path in example["image_paths"]]
            images = [Image.open(path) for path in image_paths ]
            message_content = [ {"type": "image"} for _ in images ]
            message_content.append({
                            "type": "text",
                            "text": formatted_question_part
                        })
            
            return {"image": "", # images 
                "image_path": image_paths,
                "prompt": [
                    {
                        "role": "user",
                        "content": message_content,
                    },
                ],
                "solution": answer, ###
                "QAid": idx
            }
    # load selected tooldata from prompt yaml file        
    def load_tool_data(conf):
        # --- Tool Metadata Filtering Logic ---
        active_tool_names = conf.get("available_tools", []) # Get the list from YAML
        full_toolbox_metadata = conf.get("toolbox_metadata", {})

        # Create a dictionary containing only the metadata for active tools
        filtered_metadata_dict = {
            tool_name: full_toolbox_metadata[tool_name]
            for tool_name in active_tool_names
            if tool_name in full_toolbox_metadata
        }

        # Warn for missing tools
        for tool_name in active_tool_names:
            if tool_name not in full_toolbox_metadata:
                print(f"Warning: Tool '{tool_name}' listed in available_tools but not found in toolbox_metadata.")

        # indent=2 makes it readable
        filtered_metadata_str = json.dumps(filtered_metadata_dict, indent=2)

        available_tools_str = ", ".join(active_tool_names)

        return available_tools_str, filtered_metadata_str

    #################### Data Loading Start ####################

    dataset_prefix = "/home/stud/wxie/"

    # Blink Dataloader
    task_names = ["Jigsaw"]
    dataset = {}
    all_samples = []

    for task in task_names:
        dataset_path = f"BLINK_Dataset/{task}/val/{task}_val.json"
        full_path = os.path.join(dataset_prefix, dataset_path)
        with open(full_path, 'r') as f:
            raw_dataset = json.load(f)
            available_tools_str, filtered_metadata_str = load_tool_data(conf=conf)
            processed_dataset = [make_conversation_sat(sample, dataset_prefix, available_tools_str, filtered_metadata_str,base_model_prompt) for sample in raw_dataset]
            all_samples.extend(processed_dataset)

    dataset = {"train": all_samples}