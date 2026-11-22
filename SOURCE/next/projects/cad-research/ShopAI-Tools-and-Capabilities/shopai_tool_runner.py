#!/usr/bin/env python3
import os, sys, json, pathlib, subprocess, datetime, time, tomllib
P = pathlib.Path
ROOT = P(__file__).resolve().parent
ENV = P('/mnt/shopai-data-new/ShopAI-Next/projects/cad-research/environments')
REG = json.loads((ROOT / 'registry/tools.json').read_text())

def launch(tool, image, work):
    common = ENV / 'common/lib/python3.12/site-packages'
    pp = ENV / 'paddleocr/bin/python'
    co = ENV / 'common/bin/python'
    ed = ENV / 'edocr2/bin/python'
    vt = ENV / 'vtracer-standalone-v1/bin/python'
    src = ROOT / 'sources'

    env = dict(os.environ)
    env.update(
        PYTHONDONTWRITEBYTECODE='1',
        PIP_NO_INDEX='1',
        HF_HUB_OFFLINE='1',
        TRANSFORMERS_OFFLINE='1',
        HF_DATASETS_OFFLINE='1',
        TESSDATA_PREFIX=str(ROOT / 'models/tessdata'),
        TMPDIR=str(work / 'tmp'),
        XDG_CACHE_HOME=str(work / 'cache'),
        MPLCONFIGDIR=str(work / 'cache/mpl'),
        TF_CPP_MIN_LOG_LEVEL='2',
        TF_USE_LEGACY_KERAS='1'
    )
    (work / 'tmp').mkdir()
    (work / 'cache').mkdir()

    if tool == 'tesseract':
        return [
            'tesseract', str(image), str(work / 'recognized'),
            '--psm', '6', '-l', 'eng', '-c', 'tessedit_create_tsv=1'
        ], env

    if tool == 'paddleocr-v5':
        det = ROOT / 'models/paddle-v5/PP-OCRv5_server_det'
        rec = ROOT / 'models/paddle-v5/PP-OCRv5_server_rec'
        if not det.is_dir() or not rec.is_dir():
            raise RuntimeError('Archived Paddle v5 models missing')
        code = '''import sys,json,numpy as np
from paddleocr import PaddleOCR
ocr=PaddleOCR(
 text_detection_model_dir=sys.argv[2],
 text_recognition_model_dir=sys.argv[3],
 use_doc_orientation_classify=False,
 use_doc_unwarping=False,
 use_textline_orientation=False
)
def clean(x):
 if isinstance(x,np.ndarray):return x.tolist()
 if isinstance(x,(np.integer,np.floating)):return x.item()
 if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
 if isinstance(x,(list,tuple)):return [clean(v) for v in x]
 return x
out=[]
for p in ocr.predict(sys.argv[1]):
 out.append(clean(p.json if hasattr(p,"json") else p))
open("recognized.json","w").write(
 json.dumps(out,indent=2,ensure_ascii=False))
print("PADDLE_RESULTS",len(out))'''
        env['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
        return [str(pp), '-B', '-c', code,
                str(image), str(det), str(rec)], env

    if tool.startswith('cadocr-'):
        source = src / 'CADOCR-Paddle3-patched'
        env['PYTHONPATH'] = os.pathsep.join(
            [str(source), str(common)]
        )
        mode = tool.split('-', 1)[1]

        if mode == 'paddle':
            env['SHOPAI_OFFLINE_MODELS'] = str(ROOT / 'models/paddle-v6')
            env['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
            code = '''import sys,pathlib
from cadocr.pipeline import Pipeline,PipelineConfig
from cadocr.cli import _write_outputs
p=sys.argv[1]
r=Pipeline(PipelineConfig(engine="paddle")).process_file(p)
for i,obj in enumerate(r):
 name=pathlib.Path(p).stem+("_"+str(i) if len(r)>1 else "")
 _write_outputs(
  obj,str(pathlib.Path("native_output")/name),
  {"json","text","dxf"})
print("CAD_RESULTS",len(r))'''
            (work / 'native_output').mkdir()
            return [str(pp), '-B', '-c', code, str(image)], env

        args = [
            str(image), '-o', 'native_output',
            '--engine', 'tesseract'
        ]
        if mode == 'geometry':
            args.append('--no-ocr')

        return [
            str(co), '-B', '-c',
            'from cadocr.cli import main; raise SystemExit(main())',
            *args
        ], env

    if tool.startswith('drawing-to-dxf-'):
        source = src / 'Drawing-to-DXF'
        config = tomllib.loads((source / 'pyproject.toml').read_text())
        entry = config.get('project', {}).get(
            'scripts', {}
        ).get('drawing-to-dxf', '')

        if ':' not in entry:
            raise RuntimeError('Drawing-to-DXF entrypoint missing')

        code = '''import sys,importlib
mod,func=sys.argv[1].split(":")
sys.argv=["drawing-to-dxf"]+sys.argv[2:]
getattr(importlib.import_module(mod),func)()'''

        env['PYTHONPATH'] = os.pathsep.join([
            str(source / 'src'), str(source)
        ])
        args = [str(image), '-o', 'native_output']
        if tool.endswith('-geometry'):
            args.append('--skip-ocr')

        return [str(co), '-B', '-c', code, entry, *args], env

    if tool.startswith('vtracer-'):
        mode = tool.rsplit('-', 1)[1]
        code = '''import sys,vtracer
vtracer.convert_image_to_svg_py(
 sys.argv[1],sys.argv[2],colormode=sys.argv[3])'''
        output = work / (image.stem + '_' + mode + '.svg')
        return [
            str(vt), '-B', '-c', code,
            str(image), str(output), mode
        ], env

    if tool == 'edocr2-native':
        source = src / 'eDOCr2-native-p5-resize-patched'
        (work / 'edocr2/tools').mkdir(parents=True)
        (work / 'edocr2/models').symlink_to(
            source / 'edocr2/models', target_is_directory=True
        )
        (work / 'edocr2/tools/symbol_match').symlink_to(
            source / 'edocr2/tools/symbol_match',
            target_is_directory=True
        )

        env['PYTHONPATH'] = os.pathsep.join([
            str(ROOT / 'dependencies/imgaug-numpy2'),
            str(ROOT / 'dependencies/closure-added'),
            str(ROOT / 'dependencies/keras-added'),
            str(ROOT / 'dependencies/original-added'),
            str(source)
        ])

        code = '''import sys
from ocr_it import ocr_one_drawing
ocr_one_drawing(sys.argv[1])
print("EDOCR2_NATIVE_COMPLETED",flush=True)'''
        return [str(ed), '-B', '-c', code, str(image)], env

    if tool == 'dual-1060-1947-selector-v2':
        source = src / 'Dual-1060-1947-Selector-v2'
        script = source / 'blind_test.py'
        if not script.is_file():
            raise RuntimeError('Archived blind_test.py missing')

        env['PYTHONPATH'] = os.pathsep.join([
            str(source), str(ROOT / 'models/paddle-v5')
        ])

        # Historical entrypoint; requires next-session verification.
        return [
            str(pp), '-B', str(script),
            '--image', str(image),
            '--workdir', str(work)
        ], env

    # SHOPAI_NEXT_CADQUERY_STEP3_START: clone-only, no model launch.
    if tool == 'cadquery-parametric':
        env['PYTHONNOUSERSITE'] = '1'
        env.pop('PYTHONPATH', None)
        script = ROOT / 'tool-guides/cadquery-parametric/run.sh'
        return [str(script), str(image), str(work)], env
    # SHOPAI_NEXT_CADQUERY_STEP3_END

    # SHOPAI_DOCUMENT_TOOLS_V1_START: additive fallback for new non-image inputs.
    if tool in ('document-extract', 'rapidocr-image'):
        prefix = pathlib.Path('/mnt/shopai-data-new/ShopAI-Next/projects/cad-research/ShopAI-Shared-Document-Tools-v1')
        doc_script = ROOT / 'integrations/document_tools_v1/document_tools.py'
        python = prefix / 'envs' / ('core' if tool == 'document-extract' else 'ocr') / 'bin/python'
        if not python.is_file() or not doc_script.is_file():
            raise RuntimeError('Document tool runtime missing: ' + tool)
        action = 'extract' if tool == 'document-extract' else 'ocr-image'
        return [str(python), '-B', str(doc_script), action, str(image), str(work)], env
    # SHOPAI_DOCUMENT_TOOLS_V1_END

    raise RuntimeError('No executable launcher for ' + tool)

def main():
    if len(sys.argv) == 2 and sys.argv[1] == 'list':
        for item in REG['tools']:
            print(item['id'].ljust(36),
                  item['execution_status'])
        return 0

    if len(sys.argv) < 4 or sys.argv[1] != 'run':
        print('Usage: shopai-tool list | '
              'shopai-tool run TOOL_ID IMAGE [NEW_OUTPUT_DIR]')
        return 2

    tool = sys.argv[2]
    entries = {x['id']: x for x in REG['tools']}
    if tool not in entries:
        raise SystemExit('Unknown tool: ' + tool)
    if entries[tool]['execution_status'] == 'not_verified':
        raise SystemExit('Unverified tool; read its README')

    image = P(sys.argv[3]).expanduser().resolve()
    if not image.is_file():
        raise SystemExit('Input missing: ' + str(image))

    if len(sys.argv) > 4:
        work = P(sys.argv[4]).expanduser().resolve()
    else:
        timestamp = datetime.datetime.now(
            datetime.timezone.utc
        ).strftime('%Y%m%dT%H%M%SZ')
        work = ROOT / 'runs' / tool / (timestamp + '_' + str(os.getpid()))

    work.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    rc, cmd = 1, []

    try:
        cmd, env = launch(tool, image, work)
        with (work / 'console.log').open('wb') as log:
            p = subprocess.run(
                cmd, cwd=work, env=env,
                stdout=log, stderr=subprocess.STDOUT
            )
        rc = p.returncode
    except Exception as exc:
        (work / 'launch_error.txt').write_text(repr(exc) + '\n')
        print('Launch failed:', exc, file=sys.stderr)

    outputs = [
        str(x.relative_to(work))
        for x in work.rglob('*')
        if x.is_file() and x.name != 'console.log'
    ]

    (work / 'run_manifest.json').write_text(
        json.dumps({
            'tool': tool,
            'image': str(image),
            'exit_code': rc,
            'elapsed_s': round(time.monotonic() - started, 2),
            'outputs': outputs,
            'command': cmd
        }, indent=2)
    )

    print('RESULT_DIR=' + str(work))
    print('EXIT_CODE=' + str(rc))
    return rc

if __name__ == '__main__':
    sys.exit(main())
