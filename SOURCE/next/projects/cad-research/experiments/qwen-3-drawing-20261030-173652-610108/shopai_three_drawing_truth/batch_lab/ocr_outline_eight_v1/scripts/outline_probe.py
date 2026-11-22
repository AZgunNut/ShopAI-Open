#!/usr/bin/env python3
"""Visual outline diagnostics for CAD screenshots; NO geometry success score.
Runs alongside the historical contour extractor without editing it.
White-stroke color separation is a visual proxy, not human-verified outline truth.
"""
import json, pathlib,sys
import cv2,numpy as np
src,outdir=sys.argv[1:3]
out=pathlib.Path(outdir);out.mkdir(parents=True,exist_ok=True)
im=cv2.imread(src)
if im is None:raise SystemExit('Image unreadable')
h,w=im.shape[:2]
hsv=cv2.cvtColor(im,cv2.COLOR_BGR2HSV)
# Separate bright, low-saturation white/gray strokes in these CAD examples.
mask=cv2.inRange(hsv,(0,0,125),(179,80,255))
# Excludes much of low-contrast dark grid, but still includes labels, borders.
mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((2,2),np.uint8))
contours,_=cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
all_contours=len(contours)
contours=[c for c in contours if cv2.arcLength(c,False)>=max(8,min(h,w)*0.01)]
lines=cv2.HoughLinesP(mask,1,np.pi/180,threshold=max(12,int(min(w,h)*0.02)),
                      minLineLength=max(20,int(min(w,h)*0.04)),maxLineGap=5)
overlay=im.copy()
cv2.drawContours(overlay,contours,-1,(255,0,255),1) # magenta overlays on white pixels
nlines=0
if lines is not None:
    for x1,y1,x2,y2 in lines.reshape(-1,4):
        cv2.line(overlay,(int(x1),int(y1)),(int(x2),int(y2)),(0,255,255),1)
        nlines+=1
cv2.imwrite(str(out/'white_stroke_mask.png'),mask)
cv2.imwrite(str(out/'white_strokes_and_lines_overlay.png'),overlay)
summary={'source':src,'image_size_px':[w,h],'outline_truth_verified':False,
         'label':'DIAGNOSTIC ONLY; contours of light pixels include text and border, not guaranteed part boundaries',
         'white_stroke_pixels':int(cv2.countNonZero(mask)),
         'raw_contour_count':int(all_contours),'filtered_contour_count':len(contours),'straight_line_segments':nlines}
(out/'outline_visual_stats.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False))
