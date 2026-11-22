#!/usr/bin/env python3
"""ShopAI additive eight drawing OCR + outline test. No existing services modified.
Independent draft comparison. Run one drawing and OCR subprocess at a time.
"""
import datetime,hashlib,json,os,pathlib,shutil,signal,subprocess,sys,time,traceback,fcntl
ROOT=pathlib.Path(__file__).resolve().parent.parent
RUNDIR=ROOT/'results'/(datetime.datetime.now().strftime('%Y%m%dT%H%M%S')+'_'+str(os.getpid()))
RUNDIR.mkdir(parents=True,exist_ok=False)
ORDER=['p9.png','p15.png','p20.png','p12.png','P1.png','p2.png','p5.png','p27.png']
PY_PADDLE=pathlib.Path('/mnt/shopai-data-new/cad-research/environments/paddleocr/bin/python')
PY_COMMON=pathlib.Path('/mnt/shopai-data-new/cad-research/environments/common/bin/python')
BLIND=pathlib.Path('/mnt/shopai-data-new/cad-research/experiments/qwen-3-drawing-20261030-173652-610108/shopai_three_drawing_truth/batch_lab/baseline/ocr_selector/blind_test.py')
STOP=ROOT/'TERMINATE'; SCRIPT=ROOT/'scripts'
STEPS=[]

def emit(*args):
    msg=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')+' '+' '.join(map(str,args))
    print(msg,flush=True)
    with (RUNDIR/'run.log').open('a') as f:f.write(msg+'\n')

def hash_file(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()

def run(label,cmd,logpath,cwd=None):
    emit('START',label)
    with logpath.open('w') as f:
        proc=subprocess.Popen(list(map(str,cmd)),stdout=f,stderr=subprocess.STDOUT,start_new_session=True,cwd=cwd)
    last_hb=time.monotonic();last_hour=last_hb
    try:
        while proc.poll() is None:
            if STOP.exists():
                emit('TERMINATE REQUESTED',label,'owned pid',proc.pid)
                os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=20)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL)
                raise KeyboardInterrupt('TERMINATE user sentinel')
            now=time.monotonic()
            if now-last_hb>=600:
                emit('HEARTBEAT',label,'owned_pid',proc.pid,'log_bytes',logpath.stat().st_size)
                last_hb=now
            if now-last_hour>=3600:
                emit('HOURLY',label,'log_bytes',logpath.stat().st_size)
                last_hour=now
            time.sleep(2)
        emit('END',label,'exit',proc.returncode,'log',logpath)
        return proc.returncode==0
    except BaseException:
        if proc.poll() is None:
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=20)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL)
        raise

def paddle_readings(path):
    obj=json.loads(path.read_text());rows=[row for row in obj.get('rows',[]) if row.get('profiles')=='1060+1947' and row.get('plan')=='whole']
    if len(rows)!=1:raise ValueError(f'Unexpected selector result: {len(rows)} whole rows')
    readings=[]
    for p in rows[0].get('results',[]):
        txt=p.get('selected_text')
        if isinstance(txt,str) and txt.strip():readings.append({'text':txt.strip(),'bbox_px':p.get('anchor'),'alternatives':p.get('alternatives',[])})
    return readings

def tesseract_readings(image,stdout):
    # Diagnostic OCR with words/coordinates, may split annotations.
    proc=subprocess.run(['tesseract',str(image),'stdout','tsv','--psm','11'],capture_output=True,text=True)
    stdout.write_text(proc.stdout)
    if proc.returncode:return []
    import csv,io
    rows=[]
    for row in csv.DictReader(io.StringIO(proc.stdout),delimiter='\t'):
        if row.get('level')!='5' or not row.get('text','').strip():continue
        try:
            conf=float(row['conf']);left=int(row['left']);top=int(row['top']);w=int(row['width']);h=int(row['height'])
        except (ValueError,KeyError):continue
        if conf<0:continue
        rows.append({'text':row['text'].strip(),'bbox_px':[left,top,left+w,top+h],'confidence':conf/100})
    return rows

lockfd=(ROOT/'run.lock').open('w')
try:fcntl.flock(lockfd,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:raise SystemExit('Another run owns the suite lock')
if STOP.exists():raise SystemExit('TERMINATE exists in package root: clear only after confirming no active worker')
emit('BEGIN','sequential 8 PNG; OCR and outlines; source truth remains draft; no geometry scoring')
for name in ORDER:
    if STOP.exists():emit('STOPPED sentinel');break
    image=ROOT/'images'/name; truthpath=ROOT/'truths'/(name[:-4]+'.truth.json');r=RUNDIR/name[:-4];r.mkdir()
    state={'drawing':name,'image_sha256':hash_file(image),'status':'running','steps':{}}
    try:
        doc=json.loads(truthpath.read_text())
        if doc['sha256']!=state['image_sha256']:raise RuntimeError('Source SHA256 differs from truth manifest; refusing unreliable score')
        # Existing ShopAI Paddle+selector pipeline; write only to this run directory.
        if PY_PADDLE.is_file() and BLIND.is_file():
            work=r/'paddle_work';work.mkdir()
            ok=run(name+' PADDLE', [PY_PADDLE,'-B',BLIND,'--image',image,'--workdir',work],r/'paddle.log',cwd=BLIND.parent)
            selected=work/'selector/selector_v2_results.json'
            if ok and selected.is_file():
                pred={'engine':'ShopAI Paddle1060+1947 original selector','readings':paddle_readings(selected)}
                target=r/'paddle_readings.json';target.write_text(json.dumps(pred,indent=2,ensure_ascii=False)+'\n')
                run(name+' PADDLE_SCORE',[sys.executable,SCRIPT/'score_characters.py',truthpath,target,r/'paddle_score.json'],r/'paddle_score.log')
                state['steps']['paddle']='complete'
            else:
                state['steps']['paddle']='failed; see paddle.log'
        else:state['steps']['paddle']='not available: missing original Paddle env or baseline script'
        # Tesseract independent diagnostic baseline, NOT a replacement for Paddle.
        if shutil.which('tesseract'):
            words=tesseract_readings(image,r/'tesseract.tsv')
            pred={'engine':'Tesseract raw TSV word groups diagnostic','readings':words}
            target=r/'tesseract_readings.json';target.write_text(json.dumps(pred,indent=2,ensure_ascii=False)+'\n')
            run(name+' TESSERACT_SCORE',[sys.executable,SCRIPT/'score_characters.py',truthpath,target,r/'tesseract_score.json'],r/'tesseract_score.log')
            state['steps']['tesseract']='complete'
        else:state['steps']['tesseract']='not installed'
        # Historical existing OpenCV contour extraction: identical script copied into own isolated folder.
        cvpython=PY_COMMON if PY_COMMON.is_file() else PY_PADDLE
        if cvpython.is_file():
            state['steps']['legacy_contours']='complete' if run(name+' LEGACY_CONTOURS',
                [cvpython,'-B',SCRIPT/'cv_extract_legacy_reference.py',image,r/'legacy_contours.json'],r/'legacy_contours.log') else 'failed'
            state['steps']['outline_visual']='complete' if run(name+' OUTLINE_OVERLAY',
                [cvpython,'-B',SCRIPT/'outline_probe.py',image,r/'outline'],r/'outline.log') else 'failed'
        else:
            state['steps']['legacy_contours']='missing cv2 Python env'
            state['steps']['outline_visual']='missing cv2 Python env'
        state['status']='completed_with_warnings' if any('failed' in v or 'missing' in v or 'not available' in v for v in state['steps'].values()) else 'complete'
    except KeyboardInterrupt:
        state['status']='terminated';raise
    except Exception as exc:
        state['status']='failed';state['error']=repr(exc);(r/'exception.txt').write_text(traceback.format_exc());emit('FAIL',name,repr(exc))
    finally:
        (r/'status.json').write_text(json.dumps(state,indent=2)+'\n')
        STEPS.append(state)
        (RUNDIR/'summary.json').write_text(json.dumps({'results':STEPS,'root':str(RUNDIR)},indent=2)+'\n')
        emit('DRAWING_COMPLETE',name,state['status'])
emit('FINISHED',len(STEPS),'of',len(ORDER),'run_dir',RUNDIR)
print('FINAL_RESULT_DIR='+str(RUNDIR),flush=True)
