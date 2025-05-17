import matplotlib.pyplot as plt
from matplotlib.widgets import RectangleSelector
from PIL import Image

# === 设置你的图像路径 ===
img_path = './examples/local_feature_bbx/01.png'
image = Image.open(img_path).convert('RGB')

fig, ax = plt.subplots()
ax.imshow(image)

bbox = []

def onselect(eclick, erelease):
    x1, y1 = int(eclick.xdata), int(eclick.ydata)
    x2, y2 = int(erelease.xdata), int(erelease.ydata)
    xmin, xmax = sorted([x1, x2])
    ymin, ymax = sorted([y1, y2])
    # 只存xyxy形式 (left-top, right-bottom)
    xyxy_box = [xmin, ymin, xmax, ymax]
    bbox.clear()
    bbox.extend(xyxy_box)
    print(f"Selected bbox [x1, y1, x2, y2]: {xyxy_box}")

toggle_selector = RectangleSelector(
    ax, onselect,
    useblit=True,
    button=[1],  # 左键
    minspanx=5, minspany=5,
    spancoords='pixels',
    interactive=True
)

plt.title("Drag to draw BBox, press ENTER to confirm")
plt.connect('key_press_event', lambda event: plt.close() if event.key == 'enter' else None)
plt.show()

# 使用 bbox 变量
if bbox:
    print("Final bbox [x1, y1, x2, y2]:", bbox)
else:
    print("No bbox selected.")
