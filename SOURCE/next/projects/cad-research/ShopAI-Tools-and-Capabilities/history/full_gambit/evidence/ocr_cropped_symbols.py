import sys,json,pathlib,subprocess,cv2
imgfile,boxes,outfile=sys.argv[1:4]
img=cv2.imread(imgfile)
if img is None:raise RuntimeError('image unavailable')
rows=json.loads(pathlib.Path(boxes).read_text()).get('readings',[])
outputs={f'pad{pad}_psm{psm}':[] for pad in (2,6) for psm in (7,13)}
for i,row in enumerate(rows):
    b=row.get('bbox_px')
    if not isinstance(b,(list,tuple)) or len(b)!=4:continue
    x0,y0,x1,y1=map(int,b)
    for pad in (2,6):
        l=max(0,x0-pad);t=max(0,y0-pad);r=min(img.shape[1],x1+pad);bottom=min(img.shape[0],y1+pad)
        if r<=l or bottom<=t:continue
        crop=cv2.cvtColor(img[t:bottom,l:r],cv2.COLOR_BGR2GRAY)
        scaled=cv2.resize(crop,None,fx=8,fy=8,interpolation=cv2.INTER_LANCZOS4)
        ok,encoded=cv2.imencode('.png',scaled)
        if not ok:continue
        for psm in (7,13):
            res=subprocess.run(['tesseract','stdin','stdout','-l','eng','--psm',str(psm)],input=encoded.tobytes(),capture_output=True,timeout=60)
            txt=res.stdout.decode('utf-8',errors='replace').strip()
            if txt:outputs[f'pad{pad}_psm{psm}'].append({'text':txt,'bbox_px':list(b),'source_box':i,'crop_px':[l,t,r,bottom]})
pathlib.Path(outfile).write_text(json.dumps({'engine':'Tesseract on existing Paddle boxes','results':outputs},ensure_ascii=False,indent=2)+'\n')
print('CROPS',len(rows),'VARIANTS',list(outputs),flush=True)
