#!/usr/bin/env python3
"""Fast read-only image geometry features in original pixel coordinates."""
import cv2,json,sys
img=cv2.imread(sys.argv[1],cv2.IMREAD_GRAYSCALE)
if img is None:raise SystemExit('Cannot open image '+sys.argv[1])
h,w=img.shape[:2]
_,binary=cv2.threshold(img,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
contours,_=cv2.findContours(binary,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
features=[]
for cont in contours:
    area=cv2.contourArea(cont)
    if area<max(6,w*h*0.00002) or area>w*h*0.8:continue
    m=cv2.moments(cont)
    if abs(m['m00'])<1e-6:continue
    cx,cy=m['m10']/m['m00'],m['m01']/m['m00']
    x,y,cw,ch=cv2.boundingRect(cont)
    features.append({'cx':round(cx,2),'cy':round(cy,2),'area':round(float(area),2),'bbox_px':[x,y,x+cw,y+ch],
                     'shape':'contour'})
features.sort(key=lambda f:(-f['area'],f['cx'],f['cy']))
features=features[:300]
with open(sys.argv[2],'w') as fd:json.dump({'image_size_px':[w,h],'features_px':features,'units':'px'},fd)
