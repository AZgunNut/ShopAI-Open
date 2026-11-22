#!/usr/bin/env python3
import datetime, hashlib, json, os, pathlib, signal, subprocess, sys, time
R=pathlib.Path(__file__).resolve().parent
P=pathlib.Path('/mnt/shopai-data-new/cad-research/experiments/qwen-3-drawing-20261030-173652-610108/shopai_three_drawing_truth')
source=P/'batch_lab/baseline/ocr_selector/blind_test.py'
image=P/'images/drawing_03.jpg'
common='/mnt/shopai-data-new/cad-research/environments/common/bin/python'
paddle='/mnt/shopai-data-new/cad-research/environments/paddleocr/bin/python'
child=None

def log(*s):print(datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),*s,flush=True)
def write(name,obj):
    q=R/(name+'.tmp');q.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n');os.replace(q,R/name)
def check():
    if (R/'TERMINATE').exists():raise KeyboardInterrupt('TERMINATE requested')
def run(cmd,output):
    global child
    check(); log('START',output)
    env=os.environ.copy();env.update(PYTHONDONTWRITEBYTECODE='1',PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True')
    with (R/output).open('x') as fd:
        child=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=fd,stderr=subprocess.STDOUT,start_new_session=True,env=env)
        t=time.monotonic(); heartbeat=t; hour=t
        try:
            while child.poll() is None:
                if (R/'TERMINATE').exists():raise KeyboardInterrupt('TERMINATE requested')
                now=time.monotonic()
                if now-heartbeat>=600:log('HEARTBEAT',output,'elapsed_minutes',round((now-t)/60,2));heartbeat=now
                if now-hour>=3600:log('HOURLY_PROGRESS',output,'elapsed_minutes',round((now-t)/60,2));hour=now
                time.sleep(2)
        except BaseException:
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=15)
                except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL)
            raise
        rc=child.returncode
    child=None
    log('FINISHED',output,'rc',rc)
    if rc:raise RuntimeError(output+' failed (see file), exit code '+str(rc))

try:
    log('BEGIN','D3 existing OCR profiles 1060/1947; rotated views; Qwen untouched; mm physical / px image')
    check()
    # Create rotated PNGs with existing OpenCV interpreter; no image enhancement or unit guessing.
    script='''import cv2,sys,json
im=cv2.imread(sys.argv[1],cv2.IMREAD_COLOR)
if im is None:raise SystemExit('image read failed')
ops={90:cv2.ROTATE_90_CLOCKWISE,180:cv2.ROTATE_180,270:cv2.ROTATE_90_COUNTERCLOCKWISE}
for d,k in ops.items():
    dst=f'{sys.argv[2]}/D3_cw{d}.png'
    if not cv2.imwrite(dst,cv2.rotate(im,k)):raise SystemExit('image write failed')
open(sys.argv[2]+'/original_size.json','w').write(json.dumps({'width':im.shape[1],'height':im.shape[0]})+'\\n')
print('original image size',im.shape[1],im.shape[0])
'''
    run([common,'-B','-c',script,str(image),str(R)],'rotations.log')
    for deg in (90,180,270):
        check()
        w=R/('ocr_cw'+str(deg))
        if w.exists():raise RuntimeError('Refuse overwrite '+str(w))
        w.mkdir(mode=0o700)
        run([paddle,'-B',str(source),'--image',str(R/('D3_cw'+str(deg)+'.png')),'--workdir',str(w)],'ocr_cw'+str(deg)+'.log')
        result=w/'selector/selector_v2_results.json'
        if not result.is_file():raise RuntimeError('No OCR JSON '+str(result))
        doc=json.loads(result.read_text())
        rows=[x for x in doc.get('rows',[]) if x.get('profiles')=='1060+1947' and x.get('plan')=='whole']
        if len(rows)!=1:raise RuntimeError('Unexpected result schema '+str(result))
        gs=rows[0].get('results',[])
        # Undo rotation for group anchors; do not rewrite the OCR readings.
        sz=json.loads((R/'original_size.json').read_text()); W,H=sz['width'],sz['height']
        def inv(x,y):
            if deg==90:return (y,H-x)
            if deg==180:return (W-x,H-y)
            return (W-y,x)
        aligned=[]
        for g in gs:
            b=g.get('anchor')
            mapped=None
            if isinstance(b,list) and len(b)==4 and all(isinstance(z,(int,float)) for z in b):
                pts=[inv(x,y) for x in (b[0],b[2]) for y in (b[1],b[3])]
                mapped=[max(0,min(W,min(z[0] for z in pts))),max(0,min(H,min(z[1] for z in pts))),
                        max(0,min(W,max(z[0] for z in pts))),max(0,min(H,max(z[1] for z in pts)))]
            aligned.append({'selected_text':g.get('selected_text'),'alternatives':g.get('alternatives',[]),
                            'anchor_rotated_px':b,'anchor_original_px':mapped,
                            'source_items':g.get('source_items',[])})
        write('aligned_cw'+str(deg)+'.json',{'drawing_id':'D3','clockwise_rotation_degrees':deg,
              'image_size_original_px':[W,H],'physical_units':'mm','positions_units':'px',
              'source_selector_file':str(result),'groups':aligned})
        print_count=sum(len(g.get('alternatives',[])) for g in gs)
        log('ROTATION_RESULT','degrees',deg,'groups',len(gs),'candidate_entries',print_count,'result',result)
        write('progress.json',{'completed_degrees':deg,'groups':len(gs),'candidate_entries':print_count,'result':str(result),'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()})
    log('ALL_ROTATIONS_COMPLETE','Original files and OCR source unchanged; inspect results before modifying selector')
except KeyboardInterrupt as e:
    log('STOPPED',str(e))
except Exception as e:
    log('ERROR',type(e).__name__,str(e))
    raise
