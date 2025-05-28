import os
import json
import shutil
from tqdm import tqdm

# 源文件路径配置
json_paths = [
    "/nfs/data8/liao/ruotong/SAT/SAT_QA.json",
    "/nfs/data8/liao/wxie/SAT/SAT_QA.json"
]
images_dirs = [
    "/nfs/data8/liao/ruotong/SAT/SAT_images",
    "/nfs/data8/liao/wxie/SAT/SAT_images"
]
# 目标文件夹
merged_images_dir = "/nfs/data8/liao/wxie/SAT/images"  # 新建一个文件夹存所有图片
os.makedirs(merged_images_dir, exist_ok=True)

merged_qa = []
global_entry_idx = 0

for src_idx, (json_path, img_dir) in enumerate(zip(json_paths, images_dirs)):
    print(f"Processing {json_path}")
    with open(json_path, "r") as f:
        data = json.load(f)

    for entry_idx, entry in enumerate(tqdm(data)):
        new_entry = entry.copy()
        new_img_list = []
        for img_idx, img_path in enumerate(entry["images"]):
            old_img_name = os.path.basename(img_path)
            # 新命名：数据源_全局entry序号_本entry第几张
            new_img_name = f"{src_idx}_{global_entry_idx}_{img_idx}.png"
            src_img_path = os.path.join(img_dir, old_img_name)
            dst_img_path = os.path.join(merged_images_dir, new_img_name)
            if os.path.exists(src_img_path):
                shutil.copy(src_img_path, dst_img_path)
            else:
                print(f"WARNING: {src_img_path} not found!")
            new_img_list.append(f"images/{new_img_name}")
        new_entry["images"] = new_img_list
        merged_qa.append(new_entry)
        global_entry_idx += 1

# 保存新json
with open("/nfs/data8/liao/wxie/SAT/merged_SAT_QA.json", "w") as f:
    json.dump(merged_qa, f, indent=2, ensure_ascii=False)

print(f"合并完成，共{len(merged_qa)}个entry，图片全部保存在 {merged_images_dir}")
