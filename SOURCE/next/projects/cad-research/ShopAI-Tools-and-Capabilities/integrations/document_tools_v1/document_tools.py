#!/usr/bin/env python3
"""ShopAI shared runner worker v1 — input file -> structured output files.

Called ONLY through the existing shopai_tool_runner.py / suite_jobs.py.
The source file is read-only; output is written only to the job work directory.
"""
import csv
import hashlib
import json
import pathlib
import sys
from html import unescape

RASTER = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.webp'}
TEXT = {'.txt','.md','.markdown','.log'}

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for piece in iter(lambda: f.read(1024*1024), b''): h.update(piece)
    return h.hexdigest()

def section(kind, index, text, **extra):
    return {'kind':kind, 'index':index, 'text':text, **extra}

def extract_document(path):
    ext=path.suffix.lower()
    blocks=[]
    meta={'file':str(path), 'format':ext, 'sha256':digest(path), 'size_bytes':path.stat().st_size}
    if ext=='.pdf':
        import fitz
        with fitz.open(str(path)) as doc:
            meta.update(page_count=len(doc), title=(doc.metadata or {}).get('title',''))
            for i,p in enumerate(doc):
                text=p.get_text('text', sort=True)
                positions=[]
                for item in p.get_text('blocks',sort=True):
                    if len(item)>4 and isinstance(item[4],str):
                        positions.append({'bbox':[float(v) for v in item[:4]],'text':item[4]})
                blocks.append(section('page',i+1,text,layout_blocks=positions,
                    embedded_image_count=len(p.get_images(full=True))))
    elif ext=='.docx':
        from docx import Document
        d=Document(str(path))
        meta['paragraph_count']=len(d.paragraphs)
        for i,p in enumerate(d.paragraphs):
            if p.text.strip(): blocks.append(section('paragraph',i+1,p.text, style=p.style.name if p.style else ''))
        for i,t in enumerate(d.tables):
            grid=[[cell.text for cell in row.cells] for row in t.rows]
            blocks.append(section('table',i+1,'\n'.join(' | '.join(r) for r in grid),rows=grid))
    elif ext=='.xlsx':
        from openpyxl import load_workbook
        book=load_workbook(str(path),read_only=True,data_only=False)
        try:
            for ws in book.worksheets:
                lines=[]; cells=[]
                for row in ws.iter_rows():
                    occupied=[]
                    for cell in row:
                        if cell.value is not None:
                            occupied.append(f'{cell.coordinate}={cell.value}')
                            cells.append({'cell':cell.coordinate,'value':str(cell.value),
                                'data_type':cell.data_type})
                    if occupied: lines.append(' | '.join(occupied))
                blocks.append(section('sheet',ws.title,'\n'.join(lines),cells=cells))
        finally:
            book.close()
    elif ext=='.pptx':
        from pptx import Presentation
        prs=Presentation(str(path))
        for i,slide in enumerate(prs.slides,1):
            lines=[]; tables=[]
            for s in slide.shapes:
                if s.has_text_frame and s.text:lines.append(s.text)
                if s.has_table:
                    grid=[[cell.text for cell in row.cells] for row in s.table.rows]
                    tables.append(grid);lines.extend(' | '.join(row) for row in grid)
            blocks.append(section('slide',i,'\n'.join(lines),tables=tables))
    elif ext in TEXT:
        blocks.append(section('text',1,path.read_text(encoding='utf-8-sig',errors='replace')))
    elif ext=='.csv':
        with path.open(newline='',encoding='utf-8-sig',errors='replace') as f:
            rows=list(csv.reader(f))
        blocks.append(section('table',1,'\n'.join(' | '.join(r) for r in rows),rows=rows))
    elif ext=='.json':
        with path.open(encoding='utf-8-sig') as f: obj=json.load(f)
        blocks.append(section('json',1,json.dumps(obj,ensure_ascii=False,indent=2)))
    elif ext in {'.html','.htm','.xml','.svg'}:
        from bs4 import BeautifulSoup
        content=path.read_text(encoding='utf-8-sig',errors='replace')
        soup=BeautifulSoup(content, 'xml' if ext in {'.xml','.svg'} else 'html.parser')
        if ext in {'.html','.htm'}:
            for tag in soup(['script','style']):tag.decompose()
        text=soup.get_text(separator='\n',strip=True)
        blocks.append(section('document',1,unescape(text)))
    elif ext=='.rtf':
        from striprtf.striprtf import rtf_to_text
        blocks.append(section('document',1,rtf_to_text(path.read_text(encoding='utf-8',errors='replace'))))
    elif ext=='.odt':
        from odf.opendocument import load
        from odf import teletype
        from odf import text as odftext
        doc=load(str(path))
        for i,el in enumerate(doc.getElementsByType(odftext.P),1):
            value=teletype.extractText(el)
            if value.strip():blocks.append(section('paragraph',i,value))
    elif ext=='.epub':
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup
        book=epub.read_epub(str(path))
        meta['title']=book.get_metadata('DC','title')
        for i,item in enumerate(book.get_items_of_type(ebooklib.ITEM_DOCUMENT),1):
            soup=BeautifulSoup(item.get_content(),'html.parser')
            for tag in soup(['script','style']):tag.decompose()
            blocks.append(section('chapter',i,soup.get_text(separator='\n',strip=True), id=item.get_id()))
    else:
        raise ValueError(f'Unsupported format {ext}: no extractor claimed for this type')
    return {'tool':'document-extract','metadata':meta,'sections':blocks}

def ocr_image(path):
    if path.suffix.lower() not in RASTER:raise ValueError('OCR requires PNG/JPEG/TIFF/BMP/WEBP input')
    from rapidocr_onnxruntime import RapidOCR
    engine=RapidOCR()
    result=engine(str(path))
    if not isinstance(result,(tuple,list)) or not result:raise RuntimeError('RapidOCR returned unexpected output')
    found=result[0] or []
    items=[]
    for i,entry in enumerate(found,1):
        if len(entry)<3:raise RuntimeError('RapidOCR output missing polygon/text/confidence')
        polygon=[[float(p[0]),float(p[1])] for p in entry[0]]
        xs=[p[0] for p in polygon];ys=[p[1] for p in polygon]
        items.append({'index':i,'text':str(entry[1]),'confidence':float(entry[2]),
            'polygon_px':polygon,'bbox_px':[min(xs),min(ys),max(xs),max(ys)]})
    return {'tool':'rapidocr-image',
        'metadata':{'file':str(path),'sha256':digest(path),'size_bytes':path.stat().st_size,
                    'coordinate_unit':'pixel','recognition_unit':'text_line'},
        'detections':items}

def main():
    if len(sys.argv)!=4:raise SystemExit('Usage: document_tools.py extract|ocr-image INPUT OUTPUT_DIR')
    action,input_file,outdir=sys.argv[1:]
    path=pathlib.Path(input_file).expanduser().resolve(strict=True)
    output=pathlib.Path(outdir).expanduser().resolve(strict=True)
    if not path.is_file() or not output.is_dir():raise ValueError('Input must be a file; output a pre-existing managed directory')
    if action=='extract':
        data=extract_document(path)
        content='\n\n'.join(f"[{s['kind']} {s['index']}]\n{s['text']}" for s in data['sections'])
    elif action=='ocr-image':
        data=ocr_image(path)
        content='\n'.join(x['text'] for x in data['detections'])
    else:raise ValueError('Unknown action')
    (output/'result.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (output/'extracted.txt').write_text(content+'\n',encoding='utf-8')
    print(f"DOCUMENT_TOOL_PASS action={action} input={path} entries={len(data.get('sections',data.get('detections',[])))}")
if __name__=='__main__':main()
