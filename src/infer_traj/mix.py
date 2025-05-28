import os
import json
import random
import shutil
from glob import glob
from tqdm import tqdm

random.seed(42)
# 配置路径
json_dir = "/nfs/data8/liao/ruotong/SAT/SAT_post_nomark.json"# "/nfs/data8/liao/wxie/SAT/SAT_nomark"  # "/nfs/data8/liao/ruotong/SAT/SAT_post_nomark.json"
image_src_dir = "/nfs/data8/liao/ruotong/SAT/SAT_images_train"# "/nfs/data8/liao/wxie/SAT/SAT_images_train" #"/nfs/data8/liao/ruotong/SAT/SAT_images_train"
output_image_dir = "/nfs/data8/liao/ruotong/SAT/SAT_images"# "/nfs/data8/liao/wxie/SAT/SAT_images"
output_json_path = "/nfs/data8/liao/ruotong/SAT/SAT_QA.json"# "/nfs/data8/liao/wxie/SAT/SAT_QA.json"

os.makedirs(output_image_dir, exist_ok=True)
all_sampled_entries = []

# 抽样
# for json_file in glob(os.path.join(json_dir, "*.json")):
#     print(f"Processing {json_file}")
#     with open(json_file, "r") as f:
#         data = json.load(f)
#     sampled = data if len(data) <= 250 else random.sample(data, 250)
#     all_sampled_entries.extend(sampled)

# 跨文件夹抽样
with open(json_dir,"r") as f:
    data = json.load(f)
sampled = data if len(data) <=500 else random.sample(data,500)
all_sampled_entries.extend(sampled)

# 处理与重命名
new_entries = []

for idx, entry in enumerate(tqdm(all_sampled_entries, desc="Copy & relabel images")):
    new_img_list = []
    for img_path in entry["images"]:
        old_img_name = os.path.basename(img_path)
        # 保留下划线后缀
        if "_" in old_img_name:
            suffix = old_img_name.split("_", 1)[1]
        else:
            suffix = old_img_name
        new_img_name = f"{idx}_{suffix}"
        src_img_path = os.path.join(image_src_dir, old_img_name)
        dst_img_path = os.path.join(output_image_dir, new_img_name)

        if os.path.exists(src_img_path):
            shutil.copy(src_img_path, dst_img_path)
        else:
            print(f"WARNING: {src_img_path} not found!")

        # 记录新的图片路径
        new_img_list.append(f"SAT_images/{new_img_name}")
    
    # 修改 entry 里的所有图片路径
    new_entry = entry.copy()
    new_entry["images"] = new_img_list
    new_entries.append(new_entry)

# 保存新 JSON
with open(output_json_path, "w") as f:
    json.dump(new_entries, f, indent=2, ensure_ascii=False)

print(f"Done! {len(new_entries)} entries saved in {output_json_path}")
print(f"Images saved in {output_image_dir}")
