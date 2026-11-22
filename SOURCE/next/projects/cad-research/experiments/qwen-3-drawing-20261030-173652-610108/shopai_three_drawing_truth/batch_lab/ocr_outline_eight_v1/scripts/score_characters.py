#!/usr/bin/env python3
"""Score image OCR against visual DRAFT annotations. Independent of OCR model.
Never certifies full coverage until human audited. No CAD/geometry evaluation.
"""
import collections,datetime,difflib,json,pathlib,sys,unicodedata
truth_path=pathlib.Path(sys.argv[1]); predictions_path=pathlib.Path(sys.argv[2]);out_path=pathlib.Path(sys.argv[3]);
truth=json.loads(truth_path.read_text()); predictions=json.loads(predictions_path.read_text())
readings=truth['visible_readings']; observed=predictions['readings']
# Case and symbol distinctions are important. Remove only whitespace for OCR token grouping.
def norm(x): return ''.join(c for c in unicodedata.normalize('NFC',str(x)) if not c.isspace())
def inventory(a):return collections.Counter(ch for x in a for ch in norm(x))
expected=[r['text'] for r in readings];found=[r['text'] for r in observed];a=inventory(expected);b=inventory(found)
A=collections.Counter(norm(x) for x in expected);B=collections.Counter(norm(x) for x in found)
missing=a-b;extra=b-a
# Repeated annotations matched one-to-one by exact string; location is diagnostic until reviewed.
used=set(); matches=[]; unmatched=[]
for row in readings:
    candidates=[(i,p) for i,p in enumerate(observed) if i not in used and norm(row['text'])==norm(p['text'])]
    def spatial_pair(item):
        i,p=item;bb=p.get('bbox_px') or p.get('bbox')
        if not isinstance(bb,(list,tuple)) or len(bb)<4:return (1e9,i)
        x,y=row['anchor_px'];cx=(bb[0]+bb[2])/2;cy=(bb[1]+bb[3])/2
        return ((cx-x)**2+(cy-y)**2,i)
    if candidates:
        ix,item=min(candidates,key=spatial_pair);used.add(ix)
        dist_sq,_=spatial_pair((ix,item))
        matches.append({'truth_id':row['id'],'text':row['text'],'observation_index':ix,
                        'anchor_distance_px':round(dist_sq**0.5,1) if dist_sq<1e9 else None})
    else:unmatched.append({'truth_id':row['id'],'expected_text':row['text'],'anchor_px':row['anchor_px']})
extra_groups=[dict(p,index=i) for i,p in enumerate(observed) if i not in used]
expected_count=sum(a.values());overlap=sum((a&b).values())
summary={'truth_file':str(truth_path),'prediction_file':str(predictions_path),
   'truth_coverage_certified':truth['coverage_certified'],
   'certified_100_percent':False,
   'truth_gap_count':len(truth.get('unresolved_coverage',[])),
   'ground_truth_pending_review':sum(r['transcription_status']!='independently_verified' for r in readings),
   'expected_provisional_character_instances':expected_count,'observed_character_instances':sum(b.values()),
   'character_inventory_overlap_provisional':overlap,
   'character_inventory_pct_provisional':round(100*overlap/max(1,expected_count),2),
   'missing_characters':dict(sorted(missing.items())),
   'extra_characters':dict(sorted(extra.items())),
   'provisional_annotation_matches':len(matches),'provisional_annotation_total':len(readings),
   'missing_annotations':unmatched,'extra_or_fragmented_groups':extra_groups,
   'matching_instances_diagnostic':matches,
   'note':'Inventory counts and annotation matches are PROVISIONAL. No per-glyph spatial truth exists and truth coverage is not independently verified. Counts may cancel swapped or misplaced glyphs.'}
out_path.parent.mkdir(parents=True,exist_ok=True)
out_path.write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
print(f"CANDIDATE CHARACTER INVENTORY {overlap}/{expected_count} ({summary['character_inventory_pct_provisional']}%) | annotation strings {len(matches)}/{len(readings)} | gaps {summary['truth_gap_count']} | NOT CERTIFIED")
print('MISSING',dict(missing),'EXTRA',dict(extra))
