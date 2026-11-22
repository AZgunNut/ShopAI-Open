#!/usr/bin/env python3
"""ShopAI OCR Lab v1: offline, durable, warm-model PaddleOCR experiments.

Run with the existing isolated ShopAI PaddleOCR Python. No external downloads.
The schema explicitly separates experimentally observed outputs from unverified
quality guesses, and never treats OCR confidence as ground-truth accuracy.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import signal
import sqlite3
import statistics
import sys
import threading
import time
import traceback
from typing import Any

LAB_VERSION = 'ocr-lab-1.0.0'
SEED_DEFAULT = 20261022
BASE = Path('/mnt/shopai-data-new/cad-research')
PADDLE_KEYS = ('text_det_limit_side_len', 'text_det_limit_type',
               'text_det_thresh', 'text_det_box_thresh',
               'text_det_unclip_ratio', 'text_rec_score_thresh')


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False)


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    with tmp.open('wb') as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    # Commit directory entries as well as file data for abrupt power failures.
    fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def model_pair(root: Path, variant: str) -> tuple[Path, Path]:
    detname, recname = f'PP-OCRv5_{variant}_det', f'PP-OCRv5_{variant}_rec'
    if (root / detname).is_dir() and (root / recname).is_dir():
        return root / detname, root / recname
    # Avoid traversing arbitrary system directories; limit to approved research tree.
    for det in sorted(root.glob(f'**/{detname}')):
        rec = det.parent / recname
        if rec.is_dir():
            return det, rec
    raise FileNotFoundError(f'No offline {variant} det/rec pair in {root}')


def model_fingerprint(dirs: tuple[Path, Path]) -> str:
    """Metadata fingerprint to invalidate caches after local model replacement.
    This is NOT a cryptographic verification of model file contents.
    """
    manifest = []
    for p in dirs:
        for f in sorted(x for x in p.rglob('*') if x.is_file()):
            s = f.stat()
            manifest.append([str(f.relative_to(p)), p.name, s.st_size, s.st_mtime_ns])
    return sha_bytes(stable_json(manifest).encode())


# Every trial has a unique configuration until the finite search grid is exhausted.
# Mixed-radix permutation covers the entire grid without accidental duplicates.
PARAM_GRID = (
    ('pre.mode', ['original', 'gray', 'otsu', 'adaptive', 'black_ink']),
    ('pre.scale', [1.0, 1.5, 2.0, 2.5]),
    ('pre.clahe', [False, True]),
    ('pre.sharpen', [False, True]),
    ('pre.denoise', [False, True]),
    ('pre.contrast', [0.85, 1.0, 1.2]),
    ('paddle.text_det_limit_side_len', [640, 960, 1280]),
    ('paddle.text_det_limit_type', ['max', 'min']),
    ('paddle.text_det_thresh', [0.15, 0.25, 0.35, 0.45]),
    ('paddle.text_det_box_thresh', [0.4, 0.5, 0.6, 0.7]),
    ('paddle.text_det_unclip_ratio', [1.4, 1.8, 2.2, 2.6]),
)
SEARCH_SPACE = 1
for _name, _options in PARAM_GRID:
    SEARCH_SPACE *= len(_options)


def trial_config(index: int, seed: int = SEED_DEFAULT) -> dict:
    """Unique, reproducible configurations across up to SEARCH_SPACE trials.

    Multiplication by a prime coprime to 2/3/5 permutes the configuration space.
    Parameter 0 is a numerical threshold, not just a cosmetic data filter.
    """
    if not 0 <= index < SEARCH_SPACE:
        raise ValueError(f'trial index {index} outside unique search space {SEARCH_SPACE}')
    number = (index * 104729 + seed) % SEARCH_SPACE
    result = {'pre': {}, 'paddle': {'text_rec_score_thresh': 0.0}}
    for full_key, choices in PARAM_GRID:
        number, digit = divmod(number, len(choices))
        group, key = full_key.split('.',1)
        result[group][key] = choices[digit]
    return result

def preprocess(bgr, config: dict):
    """Return CV2 image with a stable, invertible scale transform.
    No rotation/crop; coordinates of the output are scaled only.
    """
    import cv2
    import numpy as np
    mode = config['mode']
    scale = float(config['scale'])
    if not 0.5 <= scale <= 4.0:
        raise ValueError('invalid scale')
    if mode == 'original':
        img = bgr.copy()
    elif mode == 'black_ink':
        # Black pigment has low value; saturated red/blue part boundaries should
        # not be confused with grayscale annotation strokes.
        mx = bgr.max(axis=2)
        mn = bgr.min(axis=2)
        mask = np.logical_and(mx < 190, (mx - mn) < 50)
        img = np.where(mask, 0, 255).astype(np.uint8)
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    else:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        if mode == 'gray':
            pass
        elif mode == 'otsu':
            _, gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        elif mode == 'adaptive':
            gray = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                         cv2.THRESH_BINARY, 21, 9)
        else:
            raise ValueError(f'unknown image mode: {mode}')
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    if config['clahe']:
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
        img = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    if config['denoise']:
        img = cv2.medianBlur(img, 3)
    if config['sharpen']:
        blur = cv2.GaussianBlur(img, (0, 0), 1.0)
        img = cv2.addWeighted(img, 1.7, blur, -0.7, 0)
    contrast = float(config['contrast'])
    if contrast != 1.0:
        img = np.clip((img.astype(np.float32) - 127.5) * contrast + 127.5,
                      0, 255).astype(np.uint8)
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale,
                         interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    return img


def json_compatible(obj):
    if hasattr(obj, 'tolist'):
        return obj.tolist()
    if isinstance(obj, dict):
        return {str(k): json_compatible(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_compatible(x) for x in obj]
    if isinstance(obj, (int, str, bool, float)) or obj is None:
        return obj
    return str(obj)


def iter_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            if isinstance(child, (list, dict)):
                yield from iter_nodes(child)
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, (list, dict)):
                yield from iter_nodes(child)


def collect_predictions(results, scale: float) -> tuple[list[dict], list[Any]]:
    """Read PaddleOCR v3 .json, preserve complete original JSON and normalized boxes."""
    raw, found, seen = [], [], set()
    for res in results:
        item = getattr(res, 'json', res)
        if callable(item):
            item = item()
        if isinstance(item, str):
            item = json.loads(item)
        item = json_compatible(item)
        raw.append(item)
        for node in iter_nodes(item):
            texts = node.get('rec_texts')
            if not isinstance(texts, list):
                continue
            polys = node.get('rec_polys') or node.get('dt_polys') or []
            boxes = node.get('rec_boxes') or []
            conf = node.get('rec_scores') or []
            for i, text in enumerate(texts):
                text = str(text).strip()
                if not text:
                    continue
                poly = polys[i] if i < len(polys) else None
                bbox = None
                if poly is not None:
                    try:
                        xs = [float(p[0]) for p in poly]
                        ys = [float(p[1]) for p in poly]
                        bbox = [min(xs), min(ys), max(xs), max(ys)]
                    except (TypeError, ValueError, IndexError):
                        pass
                if bbox is None and i < len(boxes):
                    bbox = list(boxes[i][:4])
                if bbox is None:
                    continue
                original = [round(float(v) / scale, 2) for v in bbox]
                key = (text, *original)
                if key in seen:
                    continue
                seen.add(key)
                found.append({'text': text, 'bbox_original_px': original,
                              'bbox_processed_px': [round(float(v), 2) for v in bbox],
                              'polygon_processed_px': poly,
                              'confidence': float(conf[i]) if i < len(conf) else None})
    return found, raw


def init_db(dbpath: Path) -> sqlite3.Connection:
    dbpath.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(dbpath), timeout=60)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA synchronous=FULL')
    con.execute('PRAGMA busy_timeout=60000')
    con.executescript('''
    CREATE TABLE IF NOT EXISTS runs (
      run_id TEXT PRIMARY KEY, lab_version TEXT NOT NULL, engine TEXT NOT NULL,
      variant TEXT NOT NULL, image_path TEXT NOT NULL, image_sha256 TEXT NOT NULL,
      models_root TEXT NOT NULL, model_fingerprint TEXT NOT NULL,
      software_version TEXT NOT NULL, source_sha256 TEXT NOT NULL,
      seed INTEGER NOT NULL, created_utc TEXT NOT NULL, last_utc TEXT NOT NULL,
      init_seconds REAL, warmup_seconds REAL,
      target_trials INTEGER NOT NULL, status TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS trials (
      run_id TEXT NOT NULL, trial_index INTEGER NOT NULL,
      config_hash TEXT NOT NULL, config_json TEXT NOT NULL,
      status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 1,
      started_utc TEXT NOT NULL, finished_utc TEXT,
      preprocessing_sha256 TEXT, output_sha256 TEXT, semantic_sha256 TEXT,
      output_path TEXT, count_boxes INTEGER, count_chars INTEGER, average_confidence REAL,
      preprocess_seconds REAL, inference_seconds REAL, total_seconds REAL,
      error_text TEXT,
      PRIMARY KEY (run_id, trial_index),
      FOREIGN KEY (run_id) REFERENCES runs(run_id)
    );
    CREATE INDEX IF NOT EXISTS idx_trials_status ON trials(run_id,status);
    CREATE INDEX IF NOT EXISTS idx_trials_config ON trials(config_hash);
    CREATE INDEX IF NOT EXISTS idx_trials_output ON trials(output_sha256);
    CREATE INDEX IF NOT EXISTS idx_trials_semantic ON trials(semantic_sha256);
    CREATE TABLE IF NOT EXISTS evaluations (
      run_id TEXT NOT NULL, trial_index INTEGER NOT NULL,
      evaluator_id TEXT NOT NULL, reference_id TEXT NOT NULL,
      metric_name TEXT NOT NULL, metric_value REAL,
      details_json TEXT, evaluated_utc TEXT NOT NULL,
      PRIMARY KEY(run_id,trial_index,evaluator_id,reference_id,metric_name)
    );
    ''')
    con.commit()
    return con


def create_run(con, run: dict, target: int) -> str:
    run_id = sha_bytes(stable_json(run).encode())[:24]
    con.execute('''INSERT INTO runs(run_id,lab_version,engine,variant,image_path,
        image_sha256,models_root,model_fingerprint,software_version,
        source_sha256,seed,created_utc,last_utc,target_trials,status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(run_id) DO UPDATE SET
        target_trials=max(target_trials,excluded.target_trials),
        last_utc=excluded.last_utc,status='running' ''',
        (run_id, run['lab_version'], run['engine'], run['variant'],
         run['image_path'], run['image_sha256'], run['models_root'],
         run['model_fingerprint'], run['software_version'],
         run['source_sha256'], run['seed'], now_utc(), now_utc(), target, 'running'))
    con.commit()
    return run_id


def record_start(con, run_id: str, i: int, config: dict, config_hash: str) -> bool:
    row = con.execute('SELECT status FROM trials WHERE run_id=? AND trial_index=?',
                      (run_id, i)).fetchone()
    if row and row[0] == 'done':
        return False
    con.execute('''INSERT INTO trials(run_id,trial_index,config_hash,config_json,
            status,started_utc) VALUES (?,?,?,?,?,?)
         ON CONFLICT(run_id,trial_index) DO UPDATE SET
            status='running', attempts=attempts+1, started_utc=excluded.started_utc,
            error_text=NULL''',
         (run_id, i, config_hash, stable_json(config), 'running', now_utc()))
    con.commit()
    return True


def record_done(con, run_id: str, i: int, data: dict) -> None:
    con.execute('''UPDATE trials SET status='done',finished_utc=?,
       preprocessing_sha256=?,output_sha256=?,semantic_sha256=?,
       output_path=?,count_boxes=?,count_chars=?,average_confidence=?,
       preprocess_seconds=?,inference_seconds=?,total_seconds=?,error_text=NULL
       WHERE run_id=? AND trial_index=?''',
       (now_utc(), data['pre_hash'],data['output_hash'], data['semantic_hash'],
        data['output_path'],data['boxes'],data['chars'],data['avg_conf'],data['pre_s'],
        data['infer_s'],data['total_s'],run_id,i))
    con.execute('UPDATE runs SET last_utc=? WHERE run_id=?',(now_utc(),run_id))
    con.commit()  # full synchronous WAL durability after *each* completed trial


def record_error(con, run_id: str, i: int, err: str) -> None:
    con.execute('UPDATE trials SET status=?,finished_utc=?,error_text=? '
                'WHERE run_id=? AND trial_index=?',
                ('error', now_utc(), err[-16000:], run_id, i))
    con.commit()


def make_backup(dbpath: Path, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    name = f"lab-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.sqlite3"
    final = folder / name
    tmp = folder / (name + '.tmp')
    src = sqlite3.connect(str(dbpath),timeout=60)
    dest = sqlite3.connect(str(tmp),timeout=60)
    try:
        src.backup(dest)
    finally:
        dest.close()
        src.close()
    with tmp.open('rb') as fd:
        os.fsync(fd.fileno())
    os.replace(tmp, final)
    parentfd = os.open(str(folder), os.O_RDONLY)
    try:
        os.fsync(parentfd)
    finally:
        os.close(parentfd)
    backups = sorted(folder.glob('lab-*.sqlite3'))
    for old in backups[:-4]:
        old.unlink(missing_ok=True)
    return final


class Monitor:
    """Heartbeat every minute; 10-minute progress reports; 30-minute DB backups.
    Runs independently of slow predict() calls; read-only backup connection.
    """
    def __init__(self, workdir: Path, db: Path, status: dict,
                 heartbeat_interval: float = 60, report_interval: float = 600,
                 backup_interval: float = 1800):
        self.workdir, self.db, self.status = workdir, db, status
        self.hbi, self.ri, self.bi = heartbeat_interval, report_interval, backup_interval
        self.lock = threading.Lock()
        self.quit = threading.Event()
        self.thread = threading.Thread(target=self._loop,daemon=True)

    def update(self, **kwargs):
        with self.lock:
            self.status.update(kwargs)

    def snapshot(self):
        with self.lock:
            d = dict(self.status)
        d['heartbeat_utc'] = now_utc()
        d['pid'] = os.getpid()
        return d

    def heartbeat(self):
        atomic_write(self.workdir/'heartbeat.json',
                     (stable_json(self.snapshot())+'\n').encode())

    def report(self):
        d = self.snapshot()
        line = (f"[{d['heartbeat_utc']}] ALIVE done={d.get('done',0)}/"
                f"{d.get('target',0)} errors={d.get('errors',0)} "
                f"active={d.get('current','idle')} state={d.get('state','unknown')} "
                f"last_completed={d.get('last_completed_utc','none')}")
        print(line,flush=True)
        with (self.workdir/'progress.log').open('a',encoding='utf-8') as fh:
            fh.write(line+'\n')

    def backup(self):
        try:
            path = make_backup(self.db,self.workdir/'backups')
            print(f'CHECKPOINT={path}',flush=True)
        except Exception as exc:
            print(f'BACKUP_ERROR: {exc}',flush=True)

    def _loop(self):
        next_hb = time.monotonic()
        next_report = time.monotonic() + self.ri
        next_backup = time.monotonic() + self.bi
        while not self.quit.is_set():
            ts = time.monotonic()
            if ts >= next_hb:
                try: self.heartbeat()
                except Exception as exc: print(f'HEARTBEAT_ERROR: {exc}',flush=True)
                next_hb = ts + self.hbi
            if ts >= next_report:
                self.report()
                next_report = ts + self.ri
            if ts >= next_backup:
                self.backup()
                next_backup = ts + self.bi
            self.quit.wait(1.0)

    def start(self):
        self.heartbeat()
        self.thread.start()

    def close(self):
        self.quit.set()
        self.thread.join()
        self.heartbeat()
        self.backup()


def begin_paddle(det: Path, rec: Path):
    from paddleocr import PaddleOCR
    start = time.perf_counter()
    pipe = PaddleOCR(device='cpu', use_doc_orientation_classify=False,
                     use_doc_unwarping=False, use_textline_orientation=False,
                     text_detection_model_name=det.name,
                     text_recognition_model_name=rec.name,
                     text_detection_model_dir=str(det),
                     text_recognition_model_dir=str(rec),
                     text_rec_score_thresh=0.0)
    return pipe, time.perf_counter()-start


def run_one(pipe, bgr, config: dict, work: Path) -> dict:
    start = time.perf_counter()
    image = preprocess(bgr,config['pre'])
    pre_elapsed = time.perf_counter()-start
    prehash = sha_bytes(str((image.shape,image.dtype)).encode()+image.tobytes())
    infer_start = time.perf_counter()
    boxes, raw = collect_predictions(pipe.predict(image,**config['paddle']),
                                      config['pre']['scale'])
    infer_elapsed = time.perf_counter()-infer_start
    result = {'schema':1, 'preprocessing_sha256':prehash,
              'source_coordinate_system':'original_image_pixels',
              'preprocessing':config['pre'], 'inference_parameters':config['paddle'],
              'detections':boxes, 'raw_paddle_results':raw}
    content = stable_json(result).encode('utf-8')
    output_hash = sha_bytes(content)
    # Semantic grouping enables future recombination without requiring identical
    # model metadata or confidence estimates across parameter configurations.
    semantic = sorted([(b['text'],
                         [round(v) for v in b['bbox_original_px']])
                        for b in boxes], key=lambda x: stable_json(x))
    semantic_hash = sha_bytes(stable_json(semantic).encode())
    rel = Path('objects') / output_hash[:2] / f'{output_hash}.json.gz'
    output = work / rel
    if not output.exists():
        compressed = gzip.compress(content,compresslevel=6,mtime=0)
        atomic_write(output,compressed)
    confidences = [r['confidence'] for r in boxes if r['confidence'] is not None]
    return {'pre_hash':prehash, 'output_hash':output_hash,
            'semantic_hash':semantic_hash,'output_path':str(rel),
            'boxes':len(boxes),'chars':sum(len(b['text']) for b in boxes),
            'avg_conf':statistics.mean(confidences) if confidences else None,
            'pre_s':pre_elapsed,'infer_s':infer_elapsed,
            'total_s':time.perf_counter()-start}


def memory_available_gb() -> float | None:
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) / (1024 * 1024)
    except OSError:
        pass
    return None


def campaign(args, pipe_factory=begin_paddle):
    import cv2
    work = args.workdir.resolve()
    work.mkdir(parents=True,exist_ok=True)
    image_path = args.image.resolve()
    if not image_path.is_file():
        raise FileNotFoundError(image_path)
    if args.trials < 1 or args.trials > SEARCH_SPACE or args.max_hours <= 0:
        raise ValueError(f'trials must be 1..{SEARCH_SPACE}; max-hours positive')
    lockfile = (work/'worker.lock').open('a+')
    try:
        fcntl.flock(lockfile.fileno(),fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Another ShopAI OCR Lab worker is already active')
    print('WORKDIR='+str(work),flush=True)
    det,rec = model_pair(args.models_root,args.variant)
    print('LOCAL_MODELS='+str(det.parent)+' VARIANT='+args.variant,flush=True)
    image_sha = file_sha(image_path)
    model_sig = model_fingerprint((det,rec))
    bgr = cv2.imread(str(image_path),cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError('Image could not be decoded')
    try:
        import paddleocr
        import numpy
        software_version = (f'paddleocr={getattr(paddleocr,"__version__","unknown")}'
                            f'|opencv={cv2.__version__}|numpy={numpy.__version__}')
    except ImportError:
        if pipe_factory is begin_paddle:
            raise RuntimeError('PaddleOCR missing from selected Python venv')
        software_version = 'mock-for-tests'
    run_details = dict(lab_version=LAB_VERSION,engine='paddleocr',
                       variant=args.variant,image_path=str(image_path),
                       image_sha256=image_sha,models_root=str(det.parent),
                       model_fingerprint=model_sig,
                       software_version=software_version,
                       source_sha256=file_sha(Path(__file__).resolve()),
                       seed=args.seed)
    dbpath = work/'lab.sqlite3'
    con = init_db(dbpath)
    rid = create_run(con,run_details,args.trials)
    previous = con.execute('SELECT COUNT(*) FROM trials WHERE run_id=? AND status=?',
                           (rid,'done')).fetchone()[0]
    errors = con.execute('SELECT COUNT(*) FROM trials WHERE run_id=? AND status=?',
                         (rid,'error')).fetchone()[0]
    status = {'run_id':rid,'engine':'paddleocr','variant':args.variant,
              'target':args.trials,'done':previous,'errors':errors,
              'state':'initializing','current':'loading','started_utc':now_utc()}
    mon = Monitor(work,dbpath,status,heartbeat_interval=args.heartbeat_seconds,
                  report_interval=args.report_seconds,
                  backup_interval=args.backup_seconds)
    mon.start()
    quit_flag = [False]
    def stop_handler(sig, frame):
        print(f'SIGNAL={sig} finish current trial then stop',flush=True)
        quit_flag[0] = True
    old_int = signal.signal(signal.SIGINT,stop_handler)
    old_term = signal.signal(signal.SIGTERM,stop_handler)
    start = time.monotonic()
    done = previous
    consecutive_errors = 0
    try:
        print(f'RUN_ID={rid} PREVIOUS_COMPLETED={previous} TARGET={args.trials}',flush=True)
        pipe, init_seconds = pipe_factory(det,rec)
        con.execute('UPDATE runs SET init_seconds=? WHERE run_id=?',
                    (init_seconds,rid));con.commit()
        print(f'MODEL_LOAD_SECONDS={init_seconds:.3f}',flush=True)
        mon.update(state='warmup', current='warmup')
        # One timed warmup. Preprocessing and the model stay resident thereafter.
        warm_start = time.perf_counter()
        warm_cfg = trial_config(0,args.seed)
        warm_image = preprocess(bgr,warm_cfg['pre'])
        list(pipe.predict(warm_image,**warm_cfg['paddle']))
        warm_s = time.perf_counter()-warm_start
        con.execute('UPDATE runs SET warmup_seconds=? WHERE run_id=?',(warm_s,rid));con.commit()
        print(f'WARMUP_SECONDS={warm_s:.3f}',flush=True)
        for i in range(args.trials):
            if quit_flag[0] or (time.monotonic()-start >= args.max_hours*3600):
                break
            row = con.execute('SELECT status FROM trials WHERE run_id=? AND trial_index=?',
                              (rid,i)).fetchone()
            if row and row[0] == 'done':
                continue
            if row and row[0] == 'error' and not args.retry_errors:
                continue
            cfg = trial_config(i,args.seed)
            cfg_hash = sha_bytes(stable_json({'run_id':rid,'config':cfg}).encode())
            if not record_start(con,rid,i,cfg,cfg_hash):
                continue
            mon.update(state='running',current=i,trial_started_utc=now_utc())
            # Memory guard: wait without exiting, retains warm Paddle model.
            while (not quit_flag[0] and args.mem_floor_gb > 0 and
                   time.monotonic()-start < args.max_hours*3600):
                avail = memory_available_gb()
                if avail is None or avail >= args.mem_floor_gb:
                    break
                mon.update(state='paused_low_memory', available_gb=round(avail,2))
                time.sleep(15)
            if quit_flag[0] or time.monotonic()-start >= args.max_hours*3600:
                break
            mon.update(state='running')
            try:
                d = run_one(pipe,bgr,cfg,work)
                record_done(con,rid,i,d)
                done += 1
                mon.update(done=done, last_completed_utc=now_utc(),
                           last_inference_seconds=round(d['infer_s'],4))
                consecutive_errors = 0
                if done <= 3 or done % 50 == 0:
                    print(f'TRIAL={i} DONE={done}/{args.trials} '
                          f'INFER_SECONDS={d["infer_s"]:.3f} BOXES={d["boxes"]}',flush=True)
            except Exception as exc:
                err = traceback.format_exc()
                record_error(con,rid,i,err)
                errors += 1
                mon.update(errors=errors,last_error=str(exc))
                consecutive_errors += 1
                print(f'TRIAL_ERROR={i} {type(exc).__name__}: {exc}',flush=True)
                if consecutive_errors >= 3:
                    print('STOP: 3 consecutive inference failures; refusing to waste 2000 trials',flush=True)
                    break
        remaining = con.execute("SELECT COUNT(*) FROM trials WHERE run_id=? AND status='done'",
                                (rid,)).fetchone()[0]
        state = 'complete' if remaining >= args.trials else 'paused'
        con.execute('UPDATE runs SET status=?,last_utc=? WHERE run_id=?',
                    (state,now_utc(),rid));con.commit()
        mon.update(state=state,current='none',done=remaining)
        print(f'CAMPAIGN_STATE={state} COMPLETE={remaining}/{args.trials} '
              f'DB={dbpath}',flush=True)
    except BaseException:
        mon.update(state='failed',current='none')
        try:
            con.execute('UPDATE runs SET status=?,last_utc=? WHERE run_id=?',
                        ('failed',now_utc(),rid));con.commit()
        except Exception: pass
        raise
    finally:
        try: mon.close()
        finally:
            con.close()
            signal.signal(signal.SIGINT,old_int)
            signal.signal(signal.SIGTERM,old_term)
            lockfile.close()
    return 0


def status_cmd(args):
    work = args.workdir.resolve()
    dbpath = work/'lab.sqlite3'
    if not dbpath.exists():
        print('NO DATABASE YET: '+str(dbpath))
        return 1
    con = sqlite3.connect(f'file:{dbpath}?mode=ro',uri=True)
    row = con.execute('SELECT run_id,variant,target_trials,status,init_seconds,warmup_seconds '
                      'FROM runs ORDER BY last_utc DESC LIMIT 1').fetchone()
    if not row:
        print('NO RUNS YET');return 0
    rid,var,target,state,load,warm = row
    stats = con.execute('''SELECT status,COUNT(*),AVG(inference_seconds)
            FROM trials WHERE run_id=? GROUP BY status''',(rid,)).fetchall()
    groups = {s:(n,avg) for s,n,avg in stats}
    done = groups.get('done',(0,None))[0]
    speed = groups.get('done',(0,None))[1]
    median_row = con.execute('SELECT inference_seconds FROM trials '
                             "WHERE run_id=? AND status='done' ORDER BY inference_seconds",
                             (rid,)).fetchall()
    med = statistics.median([r[0] for r in median_row]) if median_row else None
    print(f'RUN={rid} VARIANT={var} STATUS={state} DONE={done}/{target} '
          f'ERRORS={groups.get("error",(0,None))[0]} '
          f'IN_PROGRESS={groups.get("running",(0,None))[0]}')
    print(f'LOAD_SECONDS={load} WARMUP_SECONDS={warm} '
          f'AVG_INFER_SECONDS={round(speed,3) if speed is not None else None} '
          f'MEDIAN_INFER_SECONDS={round(med,3) if med is not None else None}')
    hb = work/'heartbeat.json'
    if hb.is_file():
        d = json.loads(hb.read_text())
        print(f'HEARTBEAT={d.get("heartbeat_utc")} '
              f'ACTIVE_TRIAL={d.get("current")} PROCESS_STATE={d.get("state")} '
              f'PID={d.get("pid")}')
        if d.get('trial_started_utc'):
            print(f'TRIAL_STARTED={d["trial_started_utc"]} '
                  f'LAST_COMPLETED={d.get("last_completed_utc")}')
    print(f'DATABASE={dbpath} RESULTS={work/"objects"} BACKUPS={work/"backups"}')
    con.close()
    return 0


def export_cmd(args):
    work = args.workdir.resolve()
    con = sqlite3.connect(str(work/'lab.sqlite3'))
    dest = args.output or work/'trials.csv'
    dest.parent.mkdir(parents=True,exist_ok=True)
    with dest.open('w',encoding='utf-8',newline='') as fh:
        out = csv.writer(fh)
        out.writerow(['run_id','trial_index','variant','status','attempts','config_json',
                      'count_boxes','count_chars','average_confidence',
                      'preprocess_seconds','inference_seconds','total_seconds',
                      'output_sha256','semantic_sha256','output_path','error_text'])
        for r in con.execute('''SELECT t.run_id,t.trial_index,r.variant,t.status,t.attempts,
            t.config_json,t.count_boxes,t.count_chars,t.average_confidence,
            t.preprocess_seconds,t.inference_seconds,t.total_seconds,
            t.output_sha256,t.semantic_sha256,t.output_path,t.error_text
            FROM trials t JOIN runs r ON t.run_id=r.run_id
            ORDER BY t.run_id,t.trial_index'''):
            out.writerow(r)
    con.close()
    print('CSV='+str(dest))
    return 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command',required=True)
    r = sub.add_parser('run',help='persistent, warm PaddleOCR campaign')
    r.add_argument('--image',type=Path,default=Path(__file__).resolve().parent/'25-1.jpg')
    r.add_argument('--models-root',type=Path,default=BASE/'ocr-next')
    r.add_argument('--variant',choices=['server','mobile'],default='server')
    r.add_argument('--trials',type=int,default=2000)
    r.add_argument('--max-hours',type=float,default=72)
    r.add_argument('--seed',type=int,default=SEED_DEFAULT)
    r.add_argument('--retry-errors',action='store_true')
    r.add_argument('--mem-floor-gb',type=float,default=8)
    r.add_argument('--heartbeat-seconds',type=float,default=60)
    r.add_argument('--report-seconds',type=float,default=600)
    r.add_argument('--backup-seconds',type=float,default=1800)
    for name in ('status','export'):
        q = sub.add_parser(name)
        if name == 'export':
            q.add_argument('--output',type=Path)
    for q in (r,sub.choices['status'],sub.choices['export']):
        q.add_argument('--workdir',type=Path,
                       default=Path(__file__).resolve().parent/'experiments')
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.command == 'run': return campaign(args)
    if args.command == 'status': return status_cmd(args)
    if args.command == 'export': return export_cmd(args)
    raise RuntimeError('unknown command')


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'FATAL: {type(exc).__name__}: {exc}',file=sys.stderr,flush=True)
        sys.exit(1)
