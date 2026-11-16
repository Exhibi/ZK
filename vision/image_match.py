import cv2

def match_template(image_path, template_path, threshold=0.85, roi=None):
    img = cv2.imread(str(image_path)); tpl = cv2.imread(str(template_path))
    if img is None or tpl is None: raise ValueError("截图或模板图片无法读取")
    ox=oy=0
    if roi:
        x,y,w,h=map(int,roi); img=img[y:y+h,x:x+w]; ox,oy=x,y
    if tpl.shape[0] > img.shape[0] or tpl.shape[1] > img.shape[1]:
        raise ValueError("模板尺寸大于搜索区域")
    result=cv2.matchTemplate(img,tpl,cv2.TM_CCOEFF_NORMED)
    _,score,_,loc=cv2.minMaxLoc(result)
    return {"found": score >= float(threshold), "score": float(score),
            "x": int(loc[0]+ox), "y": int(loc[1]+oy),
            "width": int(tpl.shape[1]), "height": int(tpl.shape[0])}
