class OCREngine:
    """OCR 接口预留。本版本不安装 OCR 模型，不执行文字识别。"""
    def recognize(self, image_path, roi=None):
        raise NotImplementedError("OCR 模块尚未接入；后续可配置轻量 OCR 引擎。")
