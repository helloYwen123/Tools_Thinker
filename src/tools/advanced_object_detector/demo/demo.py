import argparse
import os
from gdino import GroundingDINOAPIWrapper
from PIL import Image
import numpy as np
from collections import defaultdict
import matplotlib.pyplot as plt

def get_args():
    parser = argparse.ArgumentParser(description="Interactive Inference")
    parser.add_argument("--token", type=str, help="The token for T-Rex2 API.")
    parser.add_argument("--box_threshold", type=float, default=0.3, help="Box score threshold")
    parser.add_argument("--save_dir", type=str, default="../asset/vis_masks", help="Directory to save mask visualizations")
    return parser.parse_args()

def visualize_masks(image_path, results_dict, save_dir):
    os.makedirs(save_dir, exist_ok=True)
    image = Image.open(image_path).convert("RGB")

    for label, entries in results_dict.items():
        plt.figure(figsize=(8, 6))
        plt.imshow(image)
        for entry in entries:
            if "mask" in entry:
                plt.imshow(entry["mask"], alpha=0.4, cmap='Reds')
        plt.title(f"Overlay: {label}")
        plt.axis('off')
        save_path = os.path.join(save_dir, f"{label}_mask_overlay.png")
        plt.savefig(save_path, bbox_inches='tight')
        plt.close()
        print(f"Saved mask visualization for '{label}' to {save_path}")

if __name__ == "__main__":
    args = get_args()

    # Use provided token or fallback to hardcoded (for testing)
    token = args.token or "5cf9118fa07590654271566b4599070f"
    gdino = GroundingDINOAPIWrapper(token)

    image_path = '../asset/demo.jpg'
    prompts = dict(image=image_path, prompt='tree')
    results = gdino.inference(prompts, return_mask=True)

    grouped = defaultdict(list)
    has_mask = bool(results.get("masks"))

    if has_mask:
        masks = results["masks"]
        print(f"Number of masks: {len(masks)}")
        for i, mask in enumerate(masks):
            alpha = mask.split()[-1]  # PIL Image
            alpha_array = np.array(alpha)
            print(f"Mask {i} shape: {alpha_array.shape}, dtype: {alpha_array.dtype}")
            print(f"Mask {i} unique values: {np.unique(alpha_array)}")

            # Optional: save alpha mask as image for visualization
            alpha.save(f"../asset/mask_{i}_alpha.png")

    for box, category, score, *mask in zip(  # depending on mask existence
        results["boxes"],
        results["categorys"],
        results["scores"],
        results["masks"] if has_mask else [None] * len(results["boxes"])
    ):
        entry = {
            "box": box,
            "score": score,
        }
        if has_mask and mask and mask[0] is not None:
            alpha = mask[0].split()[-1]
            binary_mask = (np.array(alpha) > 0)
            entry["mask"] = binary_mask
        grouped[category].append(entry)

    results_dict = dict(grouped)

    # Save overlay visualizations
    # Save structured results to JSON (as string, quick version)
    with open('../asset/demo_output.json', 'w') as f:
        f.write(str(results_dict))
        print("Saved raw result dict to ../asset/demo_output.json")
