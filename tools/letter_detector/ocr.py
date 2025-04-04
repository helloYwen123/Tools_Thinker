# import cv2
# import easyocr
# import numpy as np
# import matplotlib.pyplot as plt
# import re

# # 选择是否进行预处理
# USE_PREPROCESS = True

# # Step 1: 预处理（可选）
# def preprocess_image(image_path):
#     img = cv2.imread(image_path)
#     gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
#     eq = cv2.equalizeHist(gray)
#     bin_img = cv2.adaptiveThreshold(eq, 255,
#                                     cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
#                                     cv2.THRESH_BINARY_INV,
#                                     15, 10)
#     scale = 2
#     resized = cv2.resize(bin_img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
#     return resized

# # Step 2: 识别并过滤字母
# def detect_filtered_letters(image_np):
#     reader = easyocr.Reader(['en'], gpu=True)
#     result = reader.readtext(image_np, 
#                              text_threshold=0.5, 
#                              low_text=0.3, 
#                              link_threshold=0.3, 
#                              canvas_size=2560, 
#                              mag_ratio=2.0, 
#                              decoder='beamsearch',
#                              )

#     allowed_letters = {'A', 'B', 'C', 'D', 'E'}
#     filtered = []

#     for bbox, text, score in result:
#         if score < 0.3:
#             continue

#         # # 去掉非字母字符
#         # text = re.sub(r'[^A-Za-z]', '', text)
#         if len(text) == 2:
#             # 如果是两个字母，优先保留第二个如果它合法
#             second = text[1].upper()
#             if second in allowed_letters:
#                 filtered.append((bbox, second, score))
#         else:       
#             filtered.append((bbox, text, score))
#     return filtered

# # Step 3: 可视化
# def visualize_letter_results(image_np, results, save_path="output_filtered_letters.png"):
#     """在处理后的图片（如果有）或原图片上可视化"""
    
#     # 确保图像是彩色的（即便是预处理的灰度图，也转换成 BGR 以便可视化）
#     if len(image_np.shape) == 2:  # 说明是灰度图
#         img_color = cv2.cvtColor(image_np, cv2.COLOR_GRAY2BGR)
#     else:  # 说明已经是 BGR 彩色图
#         img_color = image_np.copy()

#     for bbox, text, score in results:
#         pts = np.array(bbox, dtype=np.int32)
#         cv2.polylines(img_color, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
#         cv2.putText(img_color, f"{text} ({score:.2f})", 
#                     (pts[0][0], pts[0][1] - 10),
#                     cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

#     plt.figure(figsize=(12, 8))
#     plt.imshow(cv2.cvtColor(img_color, cv2.COLOR_BGR2RGB))  # 转换为 Matplotlib 格式
#     plt.axis('off')
#     plt.title('Filtered Letters: A-E only')
#     plt.show()

#     cv2.imwrite(save_path, img_color)
#     print(f"✅ Filtered image saved to: {save_path}")

# # Main
# if __name__ == "__main__":
#     image_path = "./examples/AB.png"  # 替换成你的图像路径

#     # 先尝试不预处理
#     image_np = cv2.imread(image_path, cv2.IMREAD_COLOR)
#     results_no_preprocess = detect_filtered_letters(image_np)

#     if len(results_no_preprocess) < 2:  # 识别出的字母太少，尝试预处理
#         print("🔄 识别效果差，尝试预处理...")
#         image_np = preprocess_image(image_path)
#         results = detect_filtered_letters(image_np)
#     else:
#         results = results_no_preprocess
#     visualize_letter_results(image_np, results)  # 在正确的图像上可视化

#     print("\n🔤 识别的字母 (A-E only)：")
#     for bbox, text, score in results:
#         print(f"[{score:.2f}] {text} — bbox: {bbox}")

import cv2
import easyocr
import numpy as np
import matplotlib.pyplot as plt
import re

# 选择是否进行预处理
USE_PREPROCESS = True

# Step 1: 预处理（可选）
def preprocess_image(image_path):
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

# Step 2: 识别并过滤字母
def detect_filtered_letters(image_np):
    reader = easyocr.Reader(['en'], gpu=True)
    result = reader.readtext(image_np, 
                             text_threshold=0.5, 
                             low_text=0.3, 
                             link_threshold=0.3, 
                             canvas_size=5000, 
                             mag_ratio=2.0, 
                             decoder='beamsearch',
                             allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ')

    allowed_letters = {'A', 'B', 'C', 'D', 'E'}
    filtered = []

    for bbox, text, score in result:
        if score < 0.3:
            continue

        # 去掉非字母字符
        text = re.sub(r'[^A-Za-z]', '', text)

        if len(text) == 1 and text.upper() in allowed_letters:
            filtered.append((bbox, text.upper(), score))
        elif len(text) == 2:
            # 如果是两个字母，优先保留第二个如果它合法
            second = text[1].upper()
            if second in allowed_letters:
                filtered.append((bbox, second, score))
    
    return filtered

# Step 3: 可视化
def visualize_letter_results(image_np, results, save_path="output_filtered_letters.png"):
    """在处理后的图片（如果有）或原图片上可视化"""
    
    # 确保图像是彩色的（即便是预处理的灰度图，也转换成 BGR 以便可视化）
    if len(image_np.shape) == 2:  # 说明是灰度图
        img_color = cv2.cvtColor(image_np, cv2.COLOR_GRAY2BGR)
    else:  # 说明已经是 BGR 彩色图
        img_color = image_np.copy()

    for bbox, text, score in results:
        pts = np.array(bbox, dtype=np.int32)
        cv2.polylines(img_color, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
        cv2.putText(img_color, f"{text} ({score:.2f})", 
                    (pts[0][0], pts[0][1] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

    plt.figure(figsize=(12, 8))
    plt.imshow(cv2.cvtColor(img_color, cv2.COLOR_BGR2RGB))  # 转换为 Matplotlib 格式
    plt.axis('off')
    plt.title('Filtered Letters: A-E only')
    plt.show()

    cv2.imwrite(save_path, img_color)
    print(f"✅ Filtered image saved to: {save_path}")

# Main
if __name__ == "__main__":
    image_path = "./examples/03.png"  # 替换成你的图像路径

    # 先尝试不预处理
    image_np = cv2.imread(image_path, cv2.IMREAD_COLOR)
    results_no_preprocess = detect_filtered_letters(image_np)

    if len(results_no_preprocess) < 2:  # 识别出的字母太少，尝试预处理
        print("🔄 识别效果差，尝试预处理...")
        image_np = preprocess_image(image_path)
        results = detect_filtered_letters(image_np)
    else:
        results = results_no_preprocess
    visualize_letter_results(image_np, results)  # 在正确的图像上可视化

    print("\n🔤 识别的字母 (A-E only)：")
    for bbox, text, score in results:
        print(f"[{score:.2f}] {text} — bbox: {bbox}")
