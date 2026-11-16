from .color_match import find_hsv_color
from .image_match import match_template

class VisionEngine:
    """统一识别入口；OCR 暂留接口。"""
    def color(self, image_path, lower, upper, roi=None):
        return find_hsv_color(image_path, lower, upper, roi)
    def image(self, image_path, template_path, threshold=0.85, roi=None):
        return match_template(image_path, template_path, threshold, roi)
