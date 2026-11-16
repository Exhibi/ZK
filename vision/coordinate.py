def scale_point(x, y, source_size, target_size):
    sw, sh = source_size; tw, th = target_size
    if not sw or not sh: raise ValueError("源分辨率无效")
    return round(x*tw/sw), round(y*th/sh)
