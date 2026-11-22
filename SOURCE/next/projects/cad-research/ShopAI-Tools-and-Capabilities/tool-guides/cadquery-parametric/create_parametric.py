#!/usr/bin/env python3
"""ShopAI-Next offline CAD compiler: mm plate + optional through-holes to STEP."""
import json, math, os, pathlib, sys
ROOT=pathlib.Path('/mnt/shopai-data-new/ShopAI-Next').resolve()
EXPECTED=ROOT/'projects/cad-research/environments/cadquery-2.8.0-isolated-v1'

def contained(p):
 p=p.expanduser().resolve()
 if p!=ROOT and ROOT not in p.parents: raise ValueError('Path must stay inside ShopAI-Next: '+str(p))
 return p

def positive_number(x,name):
 if type(x) not in (float,int) or not math.isfinite(x) or x<=0:
  raise ValueError(name+' must be a positive finite number')
 return float(x)

def run(src,dst):
 if pathlib.Path(sys.prefix).resolve()!=EXPECTED.resolve():
  raise RuntimeError('REFUSED: not running inside copied CadQuery environment')
 import cadquery as cq
 src=contained(pathlib.Path(src)); dst=contained(pathlib.Path(dst))
 if not src.is_file() or src.suffix.lower()!='.json':
  raise ValueError('Input must be an existing JSON file')
 if not dst.is_dir(): raise ValueError('Output directory must already exist')
 data=json.loads(src.read_text(encoding='utf-8'))
 if not isinstance(data,dict) or data.get('units')!='mm' or data.get('operation')!='plate':
  raise ValueError('Required JSON: units="mm", operation="plate"')
 a=positive_number(data.get('length_mm'),'length_mm')
 b=positive_number(data.get('width_mm'),'width_mm')
 t=positive_number(data.get('thickness_mm'),'thickness_mm')
 if max(a,b,t)>100000: raise ValueError('Dimension exceeds accepted baseline range')
 holes=data.get('through_holes',[])
 if not isinstance(holes,list) or len(holes)>200: raise ValueError('Invalid through_holes list')
 shape=cq.Workplane('XY').box(a,b,t)
 validated=[]
 for hole in holes:
  if not isinstance(hole,dict): raise ValueError('Hole must be an object')
  x,y=hole.get('x_mm'),hole.get('y_mm')
  if type(x) not in (float,int) or type(y) not in (float,int):
   raise ValueError('Hole center must have numeric x_mm, y_mm')
  x=float(x); y=float(y)
  d=positive_number(hole.get('diameter_mm'),'diameter_mm')
  if not all(map(math.isfinite,(x,y))) or abs(x)+d/2>=a/2 or abs(y)+d/2>=b/2:
   raise ValueError('Hole breaks plate boundary')
  if any(math.hypot(x-h['x_mm'],y-h['y_mm']) <= (d+h['diameter_mm'])/2 for h in validated):
   raise ValueError('Overlapping/tangent holes not supported in baseline')
  validated.append({'x_mm':x,'y_mm':y,'diameter_mm':d})
 for h in validated:
  shape=shape.faces('>Z').workplane(centerOption='CenterOfBoundBox').center(h['x_mm'],h['y_mm']).hole(h['diameter_mm'])
 solid=shape.val()
 if not solid.isValid() or solid.Volume()<=0: raise RuntimeError('CAD shape invalid')
 expected_volume=a*b*t-sum(math.pi*(h['diameter_mm']/2)**2*t for h in validated)
 if not math.isclose(solid.Volume(),expected_volume,rel_tol=0.00001,abs_tol=0.00001):
  raise RuntimeError('CAD volume does not match dimensions/holes')
 dest=dst/'parametric_plate.step'
 cq.exporters.export(shape,str(dest),exportType='STEP')
 reread=cq.importers.importStep(str(dest)).val()
 if not reread.isValid() or not math.isclose(reread.Volume(),expected_volume,rel_tol=0.0001):
  raise RuntimeError('STEP round-trip failed')
 result={'status':'PASS','units':'mm','cadquery_version':cq.__version__,
         'length_mm':a,'width_mm':b,'thickness_mm':t,'through_holes':validated,
         'volume_mm3':solid.Volume(),'expected_volume_mm3':expected_volume,
         'step_file':str(dest),'step_bytes':dest.stat().st_size,'roundtrip_valid':True}
 (dst/'result.json').write_text(json.dumps(result,indent=2)+'\n')
 print('CADQUERY_STEP_PASS',json.dumps(result,sort_keys=True),flush=True)

if __name__=='__main__':
 if len(sys.argv)!=3:
  raise SystemExit('Usage: create_parametric.py input.json existing_OUTPUT_DIR')
 run(sys.argv[1],sys.argv[2])
