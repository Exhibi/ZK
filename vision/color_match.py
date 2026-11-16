import cv2
import numpy as np

def find_hsv_color(image_path, lower, upper, roi=None):
    img = cv2.imread(str(image_path))
    if img is None: raise ValueError("无法读取截图")
    offset = (0,0)
    if roi:
        x,y,w,h = map(int, roi); img = img[y:y+h, x:x+w]; offset=(x,y)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(lower,dtype=np.uint8), np.array(upper,dtype=np.uint8))
    count = int(cv2.countNonZero(mask))
    ys, xs = np.where(mask > 0)
    center = None
    if len(xs):
        center = [int(xs.mean()+offset[0]), int(ys.mean()+offset[1])]
    return {"found": count > 0, "pixel_count": count, "center": center}
