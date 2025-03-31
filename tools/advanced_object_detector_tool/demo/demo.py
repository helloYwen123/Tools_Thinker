import argparse
import os
from gdino import GroundingDINOAPIWrapper, visualize
from PIL import Image
import numpy as np
from collections import defaultdict

def get_args():
    parser = argparse.ArgumentParser(description="Interactive Inference")
    parser.add_argument(
        "--token",
        type=str,
        help="The token for T-Rex2 API. We are now opening free API access to T-Rex2",
    )
    parser.add_argument(
        "--box_threshold", type=float, default=0.3, help="The threshold for box score"
    )
    return parser.parse_args()

if __name__ == "__main__":
    args = get_args()
    token = "5cf9118fa07590654271566b4599070f"
    gdino = GroundingDINOAPIWrapper(token)
    prompts = dict(image='../asset/demo.jpg', prompt='person.pigeon.tree')
    results = gdino.inference(prompts,return_mask=True)

    # print the results
    # now visualize the results
    grouped = defaultdict(list)
    has_mask = bool(results.get("masks"))
    for box, category, score, *mask in zip(
        results["boxes"],
        results["categorys"],
        results["scores"],
        results["masks"] if has_mask else [None] * len(results["boxes"])
    ):
        entry = {
            "box": box,
            "score": score,
        }
        if has_mask and mask is not None:
            alpha = mask[0].split()[-1]
            entry["mask"] = (np.array(alpha) > 0)  # binary mask
        grouped[category].append(entry)
    results = dict(grouped)
    
    with open('../asset/demo_output.json', 'w') as f:
        f.write(str(results))