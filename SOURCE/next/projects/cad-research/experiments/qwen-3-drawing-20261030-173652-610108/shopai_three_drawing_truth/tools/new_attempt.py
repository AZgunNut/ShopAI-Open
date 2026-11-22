#!/usr/bin/env python3
"""Create numbered, never-overwritten experiment snapshot from explicit COPIED source.
Does not modify live ShopAI or run any model. Standard library only.
"""
import argparse,datetime as dt,hashlib,json,os,shutil,sys
from pathlib import Path

def main():
    pa=argparse.ArgumentParser()
    pa.add_argument('--source-dir',type=Path,required=True)
    pa.add_argument('--attempts-dir',type=Path,required=True)
    pa.add_argument('--parent',default='baseline')
    pa.add_argument('--reason',default='new candidate for drawing test')
    pa.add_argument('--model',default='Qwen3-Coder-30B-A3B')
    opt=pa.parse_args()
    src=opt.source_dir.expanduser().resolve(strict=True)
    base=opt.attempts_dir.expanduser().resolve()
    if not src.is_dir():raise SystemExit('Source must be a directory')
    if src==base or src in base.parents:
        raise SystemExit('Source may not be the attempts directory or an ancestor of it')
    if src.is_symlink():
        raise SystemExit('Refusing symlinked source')
    for p in src.rglob('*'):
        if p.is_symlink():
            raise SystemExit('Refusing source tree with symlinks: '+str(p))
    base.mkdir(parents=True,exist_ok=True)
    nums=[int(p.name) for p in base.iterdir() if p.is_dir() and p.name.isdigit()]
    i=max(nums,default=0)+1
    dest=base/f'{i:04d}'
    dest.mkdir(exist_ok=False)
    try:
        shutil.copytree(src,dest/'source',symlinks=False,ignore=shutil.ignore_patterns('__pycache__','.git','*.pyc','.venv','venv','node_modules','*.gguf','*.safetensors'))
        for rel in ('predictions','evaluation','logs','overlays','intermediates'):(dest/rel).mkdir()
        lines=[]
        files=sorted(p for p in (dest/'source').rglob('*') if p.is_file())
        for p in files:
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            lines.append(f'{digest}  {p.relative_to(dest)}')
        (dest/'source_hashes.sha256').write_text('\n'.join(lines)+'\n')
        (dest/'metadata.json').write_text(json.dumps({
            'attempt':i,'created_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
            'parent':opt.parent,'reason':opt.reason,'model':opt.model,
            'source_dir':str(src),'source_file_count':len(files),'status':'created; not tested'},indent=2)+'\n')
    except BaseException:
        # Don't delete attempted folders: preserve diagnostic evidence.
        (dest/'FAILED_DURING_COPY.txt').write_text('Review incomplete source snapshot before use\n')
        raise
    print(dest)
    return 0
if __name__=='__main__':sys.exit(main())
