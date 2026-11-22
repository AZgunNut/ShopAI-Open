import tempfile
import json
import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import legacy_lab as L
import blind_test as B


class FakePipe:
    def __init__(self): self.calls = 0
    def predict(self, image, **kwargs):
        self.calls += 1
        h, w = image.shape[:2]
        return [{'res': {'rec_texts': ['R15', '20°'],
                         'rec_boxes': [[2, 2, min(w-1, 60), min(h-1, 20)],
                                       [min(w-30,70), 30, min(w-1,100), 45]],
                         'rec_scores': [.96, .78]}}]


class BlindTests(unittest.TestCase):
    def test_profile_config_readonly(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)
            db=sqlite3.connect(base/'lab.sqlite3')
            db.execute('CREATE TABLE trials(trial_index INTEGER, config_json TEXT, status TEXT)')
            for i in B.PROFILES:
                db.execute('INSERT INTO trials VALUES(?,?,?)', (i,json.dumps(L.trial_config(i)),'done'))
            db.commit();db.close()
            before=L.file_sha(base/'lab.sqlite3')
            configs=B.profile_configs(base)
            self.assertEqual(set(configs),set(B.PROFILES))
            self.assertEqual(before,L.file_sha(base/'lab.sqlite3'))

    def test_full_workflow_resume_and_blind_report(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)
            src=base/'original';src.mkdir()
            db=sqlite3.connect(src/'lab.sqlite3')
            db.execute('CREATE TABLE trials(trial_index INTEGER, config_json TEXT, status TEXT)')
            for i in B.PROFILES:
                db.execute('INSERT INTO trials VALUES(?,?,?)', (i,json.dumps(L.trial_config(i)),'done'))
            db.commit();db.close()
            original_hash=L.file_sha(src/'lab.sqlite3')
            model=base/'model'/'models'/'paddle'
            for n in ['PP-OCRv5_server_det','PP-OCRv5_server_rec']:
                (model/n).mkdir(parents=True)
                (model/n/'mock_marker').write_text(n)
            args=SimpleNamespace(workdir=base/'out',image=Path(__file__).parent/'new_drawing.jpeg',
                source_workdir=src,models_root=base/'model',tiles=False)
            pipe=FakePipe()
            B.run(args, lambda *a: (pipe,0.01))
            self.assertEqual(pipe.calls,2)
            self.assertTrue((args.workdir/'blind_report.html').is_file())
            self.assertTrue((args.workdir/'selector'/'selector_v2_results.json').is_file())
            output=json.loads((args.workdir/'selector'/'selector_v2_results.json').read_text())
            self.assertEqual(len(output['rows']),3)
            self.assertNotIn('provisional_test',output['rows'][0])
            self.assertIn('No human-certified reference', (args.workdir/'blind_report.html').read_text())
            self.assertEqual(original_hash,L.file_sha(src/'lab.sqlite3'))
            def no_model(*a):raise RuntimeError('Should use cached outputs, not reload')
            B.run(args,no_model)
            self.assertEqual(pipe.calls,2)
            args.tiles=True
            B.run(args,lambda *a:(pipe,0.01))
            self.assertEqual(pipe.calls,58)
            result=json.loads((args.workdir/'selector'/'selector_v2_results.json').read_text())
            self.assertEqual(len(result['rows']),21)
            self.assertEqual(original_hash,L.file_sha(src/'lab.sqlite3'))

    def test_tile_stitching_preserves_coordinates(self):
        from tile_study import overlap_tiles
        ts=overlap_tiles(447,447,4)
        self.assertEqual(len(ts),4)
        self.assertLess(ts[1]['rect'][0],ts[0]['rect'][2])
        d={'text':'R15','bbox_original_px':[2,3,10,9]}
        g=B.T.globalize([d],ts[1],1060)[0]
        self.assertEqual(g['bbox_original_px'][0],ts[1]['rect'][0]+2)
        self.assertEqual(g['profile'],1060)

    def test_distinct_cache_keys_per_profile(self):
        tile={'level':0,'index':0,'rect':[0,0,447,447]}
        cfg=L.trial_config(1060)
        self.assertNotEqual(B.prediction_key('a','b',1060,cfg,tile),
                            B.prediction_key('a','b',1947,cfg,tile))


if __name__=='__main__':unittest.main()
