#!/usr/bin/env python3
"""One-time final record of edited experimental source. Doesn't delete/alter source."""
import argparse, difflib, hashlib, json, time
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--attempt',type=Path,required=True)
    parser.add_argument('--parent-source',type=Path,help='previous verified/candidate source folder')
    args=parser.parse_args()
    a=args.attempt.expanduser().resolve(strict=True)
    src=a/'source'
    if not src.is_dir():raise SystemExit('Missing experiment source directory')
    target=a/'source_hashes_final.sha256'
    if target.exists():raise SystemExit('Already finalized. Do not rewrite past attempts.')
    current={str(p.relative_to(src)):p for p in src.rglob('*') if p.is_file()}
    hashes=[]
    for rel,path in sorted(current.items()):
        hashes.append(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  source/{rel}')
    target.write_text('\n'.join(hashes)+'\n')
    if args.parent_source:
        parent=args.parent_source.expanduser().resolve(strict=True)
        if not parent.is_dir():raise SystemExit('Invalid parent-source')
        older={str(p.relative_to(parent)):p for p in parent.rglob('*') if p.is_file()}
        diff=[]
        for rel in sorted(set(current)|set(older)):
            atext=older[rel].read_text(errors='replace').splitlines(keepends=True) if rel in older else []
            btext=current[rel].read_text(errors='replace').splitlines(keepends=True) if rel in current else []
            if atext!=btext:
                diff.extend(difflib.unified_diff(atext,btext,fromfile='parent/'+rel,tofile='source/'+rel))
        (a/'code_diff.patch').write_text(''.join(diff))
    (a/'FINALIZED.txt').write_text('Final source hashes recorded. Preserve this attempt, reports and logs.\n')
    print('Finalized source checksum:',target)
if __name__=='__main__':main()
