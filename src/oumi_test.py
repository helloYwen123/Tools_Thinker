from oumi.builders import build_processor, build_tokenizer
from oumi.core.configs import ModelParams
from oumi.datasets import VLJsonlinesDataset

model_name = "Qwen/Qwen2.5-VL-3B-Instruct"
tokenizer = build_tokenizer(ModelParams(model_name=model_name))
processor = build_processor(model_name, tokenizer, trust_remote_code=True)

# Load the dataset
dataset = VLJsonlinesDataset(dataset_path="./oumi_success_traj.jsonl",
                             tokenizer=tokenizer,
                             processor=processor)

# Iterate through the dataset and print conversations
for i in range(5):
   print(dataset.conversation(i))