#!/usr/bin/env python3
"""ShopAI additive full offline OCR/outline test across eight CAD PNGs.
Never edits existing OCR pipelines, data, models, config or services.
The truth tables are deliberately only consumed after inference for scoring.
"""
import ast
import collections
import copy
import csv
import datetime
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import re
import secrets
import string
import shlex
import shutil
import struct
import signal
import subprocess
import sys
import time
import traceback

ROOT=pathlib.Path(sys.argv[1]).resolve()
RUN=pathlib.Path(sys.argv[2]).resolve()
CODE=ROOT/'scripts'
ORDER=['p9','p15','p20','p12','P1','p2','p5','p27']
PADDLE=pathlib.Path('/mnt/shopai-data-new/cad-research/environments/paddleocr/bin/python')
COMMON=pathlib.Path('/mnt/shopai-data-new/cad-research/environments/common/bin/python')
EDOCR=pathlib.Path('/mnt/shopai-data-new/cad-research/environments/edocr2/bin/python')
BLIND=pathlib.Path('/mnt/shopai-data-new/cad-research/experiments/qwen-3-drawing-20261030-173652-610108/shopai_three_drawing_truth/batch_lab/baseline/ocr_selector/blind_test.py')
SRC=pathlib.Path('/mnt/shopai-data-new/cad-research/ocr-next/sources/edocr2-f6f96517a531')
MODELS=pathlib.Path('/mnt/shopai-data-new/cad-research/ocr-next/models/edocr2')
BASELINE=ROOT/'results'/'20261108T114456_2545669'
TERMINATE=RUN/'TERMINATE'
CVPY=COMMON if COMMON.is_file() else PADDLE


def emit(*parts):
    s=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')+' '+' '.join(map(str,parts))
    print(s,flush=True)
    with (RUN/'progress.log').open('a',encoding='utf-8') as f:f.write(s+'\n')


def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(obj,indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf-8')
    os.replace(tmp,path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(cmd,logfile,label,env=None,cwd=None):
    if TERMINATE.exists():raise KeyboardInterrupt('TERMINATE requested')
    emit('START',label)
    start=time.monotonic();hb=start;hour=start
    with logfile.open('w',encoding='utf-8') as handle:
        worker=subprocess.Popen([str(s) for s in cmd],stdout=handle,stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,start_new_session=True,env=env,cwd=cwd)
        try:
            while worker.poll() is None:
                now=time.monotonic()
                if TERMINATE.exists():raise KeyboardInterrupt('TERMINATE requested')
                if now-hb>=600:
                    emit('HEARTBEAT',label,'minutes',round((now-start)/60,1),'pid',worker.pid,'log_bytes',logfile.stat().st_size)
                    hb=now
                if now-hour>=3600:
                    emit('HOURLY',label,'minutes',round((now-start)/60,1),'pid',worker.pid)
                    hour=now
                time.sleep(2)
        except BaseException:
            if worker.poll() is None:
                os.killpg(worker.pid,signal.SIGTERM)
                try:worker.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(worker.pid,signal.SIGKILL);worker.wait()
            raise
    emit('END',label,'rc',worker.returncode,'seconds',round(time.monotonic()-start,1))
    return worker.returncode==0


def score(truth,readings,dest,label):
    inputfile=dest.with_name(dest.stem+'_readings.json')
    dump(inputfile,{'engine':label,'readings':readings})
    ok=run([sys.executable,'-B',CODE/'score_characters.py',truth,inputfile,dest],
        dest.with_suffix('.log'),label+' SCORE')
    if not ok:raise RuntimeError('Score failed '+str(dest))
    dat=json.loads(dest.read_text())
    return {'label':label,'characters':dat['character_inventory_overlap_provisional'],
            'expected':dat['expected_provisional_character_instances'],
            'annotation_matches':dat['provisional_annotation_matches'],
            'missing_characters':dat['missing_characters'],
            'extra_characters':dat['extra_characters'],
            'missing_count':sum(dat['missing_characters'].values()),
            'extra_count':sum(dat['extra_characters'].values()),
            'annotations':dat['provisional_annotation_total'],
            'score':str(dest.relative_to(RUN)),'n_readings':len(readings)}


def inventory():
    envroot=pathlib.Path('/mnt/shopai-data-new/cad-research/environments')
    candidates=[pathlib.Path('/usr/bin/python3')]
    if envroot.is_dir():
        candidates+=sorted(envroot.glob('*/bin/python'))
    probe="""import json,sys,importlib.util\nmods=['paddleocr','pytesseract','easyocr','rapidocr','rapidocr_onnxruntime','surya','doctr','mmocr','keras_ocr','tensorflow','transformers','cv2','torch']\nprint(json.dumps({'python':sys.executable,'modules':{m:importlib.util.find_spec(m) is not None for m in mods}}))"""
    found=[]
    for p in candidates:
        if not p.is_file():continue
        try:
            o=subprocess.run([str(p),'-B','-c',probe],capture_output=True,text=True,timeout=30)
            v=json.loads(o.stdout.strip()) if o.returncode==0 else {'python':str(p),'error':o.stderr[-400:]}
        except Exception as exc:v={'python':str(p),'error':repr(exc)}
        found.append(v)
    files={}
    for group,directory in [('edocr2_models',MODELS),('ocr_next_models',MODELS.parent),('ocr_next_sources',SRC.parent)]:
        files[group]=[]
        if directory.is_dir():
            for entry in sorted(directory.glob('*')):
                files[group].append({'name':entry.name,'size':entry.stat().st_size if entry.is_file() else None})
    result={'python_environments':found,'assets':files,'tesseract':shutil.which('tesseract'),
      'paddle_baseline':str(BLIND) if BLIND.is_file() else None,
      'edocr2_weights':str(MODELS/'recognizer_dimensions_2.keras') if (MODELS/'recognizer_dimensions_2.keras').is_file() else None}
    model_root=pathlib.Path('/mnt/shopai-data-new/AI-Models')
    candidate_roots=[pathlib.Path('/mnt/shopai-data-new/cad-research/ocr-next'),model_root]
    model_files=[]
    for base in candidate_roots:
        if not base.is_dir():continue
        for path in base.rglob('*'):
            if path.is_file() and path.suffix.lower() in ('.onnx','.keras','.gguf','.safetensors','.pt','.pth','.ckpt','.h5'):
                model_files.append({'path':str(path),'size_bytes':path.stat().st_size})
    result['other_local_model_files']=model_files
    dump(RUN/'inventory.json',result)
    for i in found:
        avail=[k for k,v in i.get('modules',{}).items() if v]
        emit('ENV',i.get('python'),'installed:',','.join(avail) if avail else 'none identified')
    return result


def opencv_prepare(image,outdir):
    # New image variants only. No source file modifications.
    program=r'''import cv2,sys,json,pathlib
src=pathlib.Path(sys.argv[1]);out=pathlib.Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
im=cv2.imread(str(src));assert im is not None
variants={'raw':im}
gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
cl=cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8)).apply(gray)
variants['clahe']=cv2.cvtColor(cl,cv2.COLOR_GRAY2BGR)
_,bw=cv2.threshold(gray,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
variants['otsu']=cv2.cvtColor(bw,cv2.COLOR_GRAY2BGR)
ops={0:None,90:cv2.ROTATE_90_CLOCKWISE,180:cv2.ROTATE_180,270:cv2.ROTATE_90_COUNTERCLOCKWISE}
for v,arr in variants.items():
  for deg,rot in ops.items():
    result=arr if rot is None else cv2.rotate(arr,rot)
    assert cv2.imwrite(str(out/f'{v}_cw{deg}.png'),result)
print(json.dumps({'original_size':[im.shape[1],im.shape[0]],'variants':list(variants),'rotations':list(ops)}))'''
    logfile=outdir/'preprocess.log'
    if not run([CVPY,'-B','-c',program,image,outdir],logfile,'IMAGE VARIANTS'):
        raise RuntimeError(logfile.read_text(errors='replace')[-900:])


def unrotate_box(box,deg,w,h):
    if not isinstance(box,(list,tuple)) or len(box)!=4:return None
    try:
        x0,y0,x1,y1=map(float,box)
        points=[(x0,y0),(x1,y0),(x0,y1),(x1,y1)]
        def inverse(x,y):
            if deg==90:return (y,h-x)
            if deg==180:return (w-x,h-y)
            if deg==270:return (w-y,x)
            return (x,y)
        out=[inverse(x,y) for x,y in points]
        return [round(min(p[0] for p in out),2),round(min(p[1] for p in out),2),
                round(max(p[0] for p in out),2),round(max(p[1] for p in out),2)]
    except (ValueError,TypeError):return None


def paddle_extract(result,deg,w,h):
    obj=json.loads(result.read_text())
    rows=[row for row in obj.get('rows',[]) if row.get('plan')=='whole' and row.get('results')]
    outputs={}
    for row in rows:
        profile=str(row.get('profiles','unknown'))
        readings=[]
        for group in row.get('results',[]):
            txt=group.get('selected_text','')
            if not isinstance(txt,str) or not txt.strip():continue
            readings.append({'text':txt.strip(),'bbox_px':unrotate_box(group.get('anchor'),deg,w,h),
                'bbox_rotated_px':group.get('anchor'),'alternatives':group.get('alternatives',[])})
        outputs[profile]=readings
    return outputs


def tesseract_extract(image,deg,w,h,psm,tsv_file):
    proc=subprocess.run(['tesseract',str(image),'stdout','--psm',str(psm),'tsv'],
            capture_output=True,text=True,timeout=300)
    tsv_file.write_text(proc.stdout,encoding='utf-8')
    if proc.returncode:raise RuntimeError(proc.stderr[-700:])
    readings=[]
    for row in csv.DictReader(io.StringIO(proc.stdout),delimiter='\t'):
        if row.get('level')!='5' or not row.get('text','').strip():continue
        try:
            c=float(row['conf']);x=int(row['left']);y=int(row['top']);ww=int(row['width']);hh=int(row['height'])
        except (KeyError,ValueError):continue
        if c<0:continue
        readings.append({'text':row['text'].strip(),'confidence':round(c/100,4),
          'bbox_px':unrotate_box((x,y,x+ww,y+hh),deg,w,h)})
    return readings


def extra_engine_worker_script():
    # Optional installed OCR libraries. Model download explicitly disabled.
    return r'''import sys,json,pathlib,traceback
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
'''


def crop_symbol_worker_script():
    # Reuse detector boxes but independently re-read the crop pixels with
    # single-line/single-raw-line Tesseract; no known answer is injected.
    return r'''import sys,json,pathlib,subprocess,cv2
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
'''

def edocr2_worker_script():
    # Offline specialized CRNN models; inference-only model reconstruction avoids
    # the upstream Keras3-incompatible training/CTC decoder and download paths.
    return r'''import ast,copy,json,pathlib,sys,traceback
import cv2,numpy as np
import tensorflow as tf
from tensorflow import keras
src,weights,truth_free_boxes,image_name,outpath=sys.argv[1:6]
src=pathlib.Path(src);weights=pathlib.Path(weights);out=pathlib.Path(outpath)
file=src/'edocr2/keras_ocr/recognition.py'
if not file.is_file():raise SystemExit('recognition.py not installed at '+str(file))
tree=ast.parse(file.read_text())
selected=[]
for node in tree.body:
    if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DEFAULT_BUILD_PARAMS' for t in node.targets):selected.append(node)
    if isinstance(node,ast.FunctionDef) and node.name in ('_repeat','_meshgrid','_transform'):selected.append(node)
    if isinstance(node,ast.FunctionDef) and node.name=='build_model':
        clone=copy.deepcopy(node)
        for idx,statement in enumerate(clone.body):
            if isinstance(statement,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='model' for t in statement.targets):
                clone.body=clone.body[:idx+1]+[ast.Return(value=ast.Name(id='model',ctx=ast.Load()))];break
        else:raise RuntimeError('Upstream build_model structure changed, no safe inference model')
        selected.append(clone)
ns={'tf':tf,'keras':keras,'np':np,'cv2':cv2}
exec(compile(ast.fix_missing_locations(ast.Module(body=selected,type_ignores=[])),'<upstream-inference-only>','exec'),ns)
texts=json.loads(pathlib.Path(truth_free_boxes).read_text())['readings']
image=cv2.imread(str(image_name))
if image is None:raise RuntimeError('image not readable')
outputs=[]
for weight in (weights/'recognizer_dimensions_2.keras',weights/'recognizer_gdts.keras'):
    if not weight.is_file() or not weight.with_suffix('.txt').is_file():continue
    alphabet=weight.with_suffix('.txt').read_text().rstrip('\n\r')
    model=ns['build_model'](alphabet=alphabet,**ns['DEFAULT_BUILD_PARAMS'])
    model.load_weights(str(weight))
    count=0
    for item in texts:
        b=item.get('bbox_px')
        if not isinstance(b,(list,tuple)) or len(b)!=4:continue
        x0,y0,x1,y1=map(int,b)
        x0=max(0,x0-2);y0=max(0,y0-2);x1=min(image.shape[1],x1+2);y1=min(image.shape[0],y1+2)
        if x1<=x0 or y1<=y0:continue
        gray=cv2.cvtColor(image[y0:y1,x0:x1],cv2.COLOR_BGR2GRAY)
        ratio=min(200/gray.shape[1],31/gray.shape[0]);ww=max(1,int(round(gray.shape[1]*ratio)));hh=max(1,int(round(gray.shape[0]*ratio)))
        patch=cv2.resize(gray,(ww,hh),interpolation=cv2.INTER_CUBIC)
        canvas=np.zeros((31,200),dtype=np.uint8);canvas[:min(31,hh),:min(200,ww)]=patch[:31,:200]
        probs=model(canvas[None,:,:,None].astype('float32')/255.0,training=False).numpy()
        seq=tf.fill([1],tf.shape(probs)[1]);decoded,_=tf.nn.ctc_greedy_decoder(tf.transpose(probs,[1,0,2]),seq)
        ids=decoded[0].values.numpy().tolist()
        word=''.join(alphabet[i] for i in ids if 0<=i<len(alphabet))
        outputs.append({'text':word,'bbox_px':[x0,y0,x1,y1], 'source_bbox':b,
             'recognizer':weight.name,'detection_source':'existing Paddle baseline boxes'})
        count+=1
    print('MODEL',weight.name,'CROPS',count,flush=True)
    keras.backend.clear_session()
out.write_text(json.dumps({'engine':'eDOCr2 specialized recognizers on Paddle-detected crops','readings':outputs},indent=2,ensure_ascii=False)+'\n')
'''


def detect_extras(inv):
    available={}
    for ent in inv['python_environments']:
        mods=ent.get('modules',{})
        executable=pathlib.Path(ent['python'])
        for key,needs in [('easyocr',('easyocr',)),('rapidocr',('rapidocr','rapidocr_onnxruntime'))]:
            if key not in available and executable.is_file() and any(mods.get(m) for m in needs):
                available[key]=executable
    return available


def main():
    RUN.mkdir(parents=True,exist_ok=False)
    stopcode=''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24))
    (RUN/'STOP_CODE').write_text(stopcode+'\n');(RUN/'STOP_CODE').chmod(0o600)
    stopscript=RUN/'stop_with_code.sh'
    stopscript.write_text('#!/usr/bin/env bash\nset -Eeuo pipefail\numask 077\nR='+shlex.quote(str(RUN))+'\n'
        +'[[ "${1:-}" == "$(cat "$R/STOP_CODE")" ]] || { echo BAD_CODE; exit 2; }\n'
        +'touch "$R/TERMINATE"\necho TERMINATE_SENTINEL_CREATED\n')
    stopscript.chmod(0o700)
    fd=(RUN/'suite.lock').open('w')
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    # Suite-wide lock in existing root avoids simultaneous own-test runs but
    # never touches the older experiment's lock or service files.
    rootlock=(ROOT/'full_gambit_suite.lock').open('a+')
    try:fcntl.flock(rootlock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('Another full gambit run owns the suite lock')
    emit('BEGIN','eight drawings, full offline recognition gambit; geometry scoring DISABLED')
    env=os.environ.copy();env.update(PYTHONDONTWRITEBYTECODE='1',PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True',
       HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TF_CPP_MIN_LOG_LEVEL='2')
    inv=inventory();extra=detect_extras(inv)
    dump(RUN/'configuration.json',{'run':str(RUN),'baseline':str(BASELINE),'order':ORDER,
         'paddle_rotations':[0,90,180,270],'paddle_preprocessing':['raw','clahe','otsu'],
         'tesseract_psm':[3,6,11,12],'tesseract_preprocessing':['raw','clahe','otsu'],
         'optional_engines':{k:str(v) for k,v in extra.items()},'truth_blind_inference':True,
         'edocr2_inference':'installed weights; Paddle-detected crops (not independent detection)',
         'outline':'legacy and overlay plus Canny; no geometry score'})
    sourcehelper=RUN/'optional_engine.py';sourcehelper.write_text(extra_engine_worker_script())
    edocrhelper=RUN/'edocr2_inference.py';edocrhelper.write_text(edocr2_worker_script())
    crophelper=RUN/'ocr_cropped_symbols.py';crophelper.write_text(crop_symbol_worker_script())
    summary=[]
    for stem in ORDER:
        if TERMINATE.exists():emit('TERMINATE BEFORE',stem);break
        dr=RUN/stem;dr.mkdir()
        image=ROOT/'images'/(stem+'.png');truth=ROOT/'truths'/(stem+'.truth.json')
        state={'drawing':stem,'status':'running','methods':[],'errors':[]}
        try:
            if not image.is_file() or not truth.is_file():raise RuntimeError('Missing source image/truth')
            sha=digest(image);doc=json.loads(truth.read_text())
            if doc.get('sha256')!=sha:raise RuntimeError('Original image hash differs from draft truth')
            state['sha256']=sha
            # Carry forward true untuned baseline as a reference, not a new rerun.
            prior=BASELINE/stem/'paddle_readings.json'
            if prior.is_file():
                obs=json.loads(prior.read_text()).get('readings',[])
                state['methods'].append(score(truth,obs,dr/'baseline_paddle_score.json','EXISTING BASELINE Paddle'))
            variants=dr/'variants';variants.mkdir()
            opencv_prepare(image,variants)
            with image.open('rb') as f: header=f.read(24)
            if header[:8]!=b'\x89PNG\r\n\x1a\n':raise RuntimeError('Not an original PNG')
            w,h=struct.unpack('>II',header[16:24])
            for preproc in ('raw','clahe','otsu'):
                for deg in (0,90,180,270):
                    if TERMINATE.exists():raise KeyboardInterrupt('TERMINATE requested')
                    view=variants/f'{preproc}_cw{deg}.png'
                    tag=f'{preproc}_cw{deg}'
                    if PADDLE.is_file() and BLIND.is_file():
                        outwork=dr/'paddle_runs'/tag;outwork.mkdir(parents=True)
                        logfile=dr/f'paddle_{tag}.log'
                        try:
                            good=run([PADDLE,'-B',BLIND,'--image',view,'--workdir',outwork],logfile,'PADDLE '+stem+' '+tag,env=env,cwd=BLIND.parent)
                            out=outwork/'selector'/'selector_v2_results.json'
                            if not good or not out.is_file():raise RuntimeError('Paddle runner failed: '+str(logfile))
                            readings_by_profile=paddle_extract(out,deg,w,h)
                            if not readings_by_profile:raise RuntimeError('No whole-image Paddle rows')
                            for profile,readings in readings_by_profile.items():
                                key=re.sub(r'[^A-Za-z0-9_]+','_',profile)
                                path=dr/f'paddle_{tag}_{key}_score.json'
                                state['methods'].append(score(truth,readings,path,'PADDLE '+tag+' '+profile))
                        except Exception as exc:
                            state['errors'].append(f'Paddle {tag}: {exc}')
                            emit('ERROR',stem,'PADDLE',tag,repr(exc))
                    if shutil.which('tesseract'):
                        for psm in (3,6,11,12):
                            lab=f'TESSERACT {stem} {tag} PSM{psm}'
                            try:
                                tsv=dr/f'tesseract_{tag}_psm{psm}.tsv'
                                readings=tesseract_extract(view,deg,w,h,psm,tsv)
                                path=dr/f'tesseract_{tag}_psm{psm}_score.json'
                                state['methods'].append(score(truth,readings,path,lab))
                            except Exception as exc:
                                state['errors'].append(f'{lab}: {exc}')
                                emit('ERROR',lab,repr(exc))
            # Independent optional OCR engines on raw and four rotations. These are
            # attempted only when their importable Python environment exists.
            for name,py in sorted(extra.items()):
                for deg in (0,90,180,270):
                    view=variants/f'raw_cw{deg}.png';lab=f'{name} cw{deg}'
                    dest=dr/f'{name}_cw{deg}.json';logfile=dr/f'{name}_cw{deg}.log'
                    try:
                        if not run([py,'-B',sourcehelper,name,view,dest],logfile,lab,env=env):
                            raise RuntimeError('Inference failed; see '+str(logfile))
                        readings=json.loads(dest.read_text())['readings']
                        for item in readings:item['bbox_px']=unrotate_box(item.get('bbox_px'),deg,w,h)
                        state['methods'].append(score(truth,readings,dr/f'{name}_cw{deg}_score.json',lab))
                    except Exception as exc:
                        state['errors'].append(f'{lab}: {exc}')
                        emit('ERROR',lab,repr(exc))
                        # Missing predownloaded weights => no benefit retrying rotations.
                        if deg==0:break
            # Symbol and tiny punctuation recovery: Tesseract single-line reading
            # on existing detection boxes (not a new independent detector).
            baseboxes=BASELINE/stem/'paddle_readings.json'
            if baseboxes.is_file() and shutil.which('tesseract') and CVPY.is_file():
                lab='Tesseract cropped symbol recovery '+stem
                output=dr/'tesseract_symbol_crops.json';logfile=dr/'tesseract_symbol_crops.log'
                try:
                    if not run([CVPY,'-B',crophelper,image,baseboxes,output],logfile,lab,env=env):
                        raise RuntimeError('Crop OCR failed; see '+str(logfile))
                    for variant,readings in json.loads(output.read_text())['results'].items():
                        state['methods'].append(score(truth,readings,dr/f'crop_{variant}_score.json',lab+' '+variant))
                except Exception as exc:
                    state['errors'].append('Tesseract cropped: '+str(exc));emit('ERROR',stem,repr(exc))
            # eDOCr2 recognizes crops supplied by original Paddle. Never claim
            # that it detects otherwise missed character locations independently.
            baseboxes=BASELINE/stem/'paddle_readings.json'
            if EDOCR.is_file() and SRC.is_dir() and (MODELS/'recognizer_dimensions_2.keras').is_file() and baseboxes.is_file():
                lab='eDOCr2 specialized recognizers on baseline Paddle boxes'
                outfile=dr/'edocr2_results.json';logfile=dr/'edocr2.log'
                try:
                    if not run([EDOCR,'-B',edocrhelper,SRC,MODELS,baseboxes,image,outfile],logfile,lab,env=env):
                        raise RuntimeError('eDOCr2 inference failed; see '+str(logfile))
                    observations=json.loads(outfile.read_text())['readings']
                    for typ in ('recognizer_dimensions_2.keras','recognizer_gdts.keras'):
                        filtered=[v for v in observations if v['recognizer']==typ]
                        if filtered:state['methods'].append(score(truth,filtered,dr/f'edocr2_{typ}_score.json','eDOCr2 '+typ))
                except Exception as exc:
                    state['errors'].append(f'eDOCr2: {exc}');emit('ERROR',stem,'eDOCr2',repr(exc))
            else:
                state['errors'].append('eDOCr2 incomplete source/venv/weights or baseline detection boxes; see inventory')
            # Both existing outline algorithms plus a separate Canny diagnostic.
            if CVPY.is_file():
                for name,cmd in [('legacy_contours',[CVPY,'-B',CODE/'cv_extract_legacy_reference.py',image,dr/'legacy_contours.json']),
                   ('white_strokes',[CVPY,'-B',CODE/'outline_probe.py',image,dr/'outline'])]:
                    try:
                        if not run(cmd,dr/f'{name}.log',stem+' '+name,env=env):raise RuntimeError('outline method failed')
                    except Exception as exc:
                        state['errors'].append(f'{name}: {exc}');emit('ERROR',stem,name,repr(exc))
                try:
                    program=r'''import cv2,sys,numpy as np,json
im=cv2.imread(sys.argv[1]);gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
edge=cv2.Canny(gray,65,180)
contours,_=cv2.findContours(edge,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
out=im.copy();cv2.drawContours(out,contours,-1,(0,255,0),1)
cv2.imwrite(sys.argv[2],out)
open(sys.argv[3],'w').write(json.dumps({'edge_pixels':int(np.count_nonzero(edge)),'contours':len(contours),'visual_only':True})+'\n')'''
                    run([CVPY,'-B','-c',program,image,dr/'canny_overlay.png',dr/'canny_stats.json'],dr/'canny.log',stem+' Canny outline',env=env)
                except Exception as exc:state['errors'].append(f'canny: {exc}')
            state['status']='complete' if not state['errors'] else 'completed_with_warnings'
            state['highest_posthoc_scores_NOT_blind_selection']=sorted(state['methods'],
                  key=lambda d:(d['missing_count']+d['extra_count'], -d['annotation_matches'], -d['characters']))[:10]
        except KeyboardInterrupt:
            state['status']='TERMINATED';raise
        except Exception as exc:
            state['status']='failed';state['errors'].append(repr(exc))
            (dr/'exception.txt').write_text(traceback.format_exc());emit('ERROR',stem,repr(exc))
        finally:
            dump(dr/'status.json',state);summary.append(state)
            dump(RUN/'summary.json',{'drawings':summary,'reference_drafts_not_certified':True,
                'score_type':'literal character inventory + full annotation; no geometry scoring'})
            best=state.get('highest_posthoc_scores_NOT_blind_selection',[])[:1]
            emit('DRAWING_COMPLETE',stem,state['status'],'tested_methods',len(state['methods']),
                 'best_provisional',best,'errors',len(state['errors']))
    emit('FINISHED',len(summary),'of',len(ORDER),'results',RUN)
    print('FINAL_RESULT_DIR='+str(RUN),flush=True)

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:emit('TERMINATED, owned worker stopped')
    except BaseException:
        traceback.print_exc();raise

