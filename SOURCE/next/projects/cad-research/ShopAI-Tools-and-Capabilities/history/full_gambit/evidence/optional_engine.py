import sys,json,pathlib,traceback
engine,src,out=sys.argv[1:4];out=pathlib.Path(out)
try:
    if engine=='easyocr':
        import easyocr
        reader=easyocr.Reader(['en'],gpu=False,download_enabled=False,verbose=False)
        data=reader.readtext(src,detail=1,paragraph=False)
        readings=[]
        for box,txt,conf in data:
            xs=[p[0] for p in box];ys=[p[1] for p in box]
            readings.append({'text':str(txt),'confidence':float(conf),'bbox_px':[min(xs),min(ys),max(xs),max(ys)]})
    elif engine=='rapidocr':
        try:from rapidocr_onnxruntime import RapidOCR
        except ImportError:from rapidocr import RapidOCR
        response=RapidOCR()(src)
        rows=response[0] if isinstance(response,tuple) else response
        readings=[]
        for item in rows or []:
            box,txt,conf=item[:3];xs=[p[0] for p in box];ys=[p[1] for p in box]
            readings.append({'text':str(txt),'confidence':float(conf),'bbox_px':[min(xs),min(ys),max(xs),max(ys)]})
    else:raise ValueError('unsupported engine '+engine)
    out.write_text(json.dumps({'engine':engine,'readings':readings},ensure_ascii=False,indent=2)+'\n')
    print('READINGS',len(readings))
except Exception:
    traceback.print_exc();sys.exit(3)
