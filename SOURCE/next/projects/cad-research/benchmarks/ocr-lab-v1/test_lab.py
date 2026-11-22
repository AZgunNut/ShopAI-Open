#!/usr/bin/env python3
"""Offline tests: genuine image transforms, resume, SQLite and compressed reuse.
No PaddleOCR weights are available in the packaging environment, so predict()
is mocked for integration tests. Actual inference must be verified on the Dell.
"""
import gzip
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import cv2
import numpy as np
import lab


class FakeResult:
    def __init__(self):
        self.json = {'res': {'rec_texts': ['0.75 DIA'],
                             'rec_polys': [[[10,10],[40,10],[40,25],[10,25]]],
                             'rec_scores': [0.95]}}


class FakePipe:
    def predict(self, image, **kwargs):
        assert isinstance(image,np.ndarray)
        assert len(image.shape)==3
        assert kwargs['text_det_limit_side_len'] > 0
        return [FakeResult()]


def fake_factory(det,rec):
    return FakePipe(),0.01


class OCRLabTests(unittest.TestCase):
    def test_2000_configs_unique(self):
        keys = [lab.stable_json(lab.trial_config(i)) for i in range(2000)]
        self.assertEqual(len(set(keys)),2000)
        self.assertGreater(lab.SEARCH_SPACE,100000)

    def test_configs_real_paddle_fields(self):
        c = lab.trial_config(100)
        self.assertEqual(set(c['paddle']),set(lab.PADDLE_KEYS))

    def test_preprocess_shapes_and_color(self):
        im = cv2.imread(str(Path(__file__).parent/'25-1.jpg'))
        self.assertIsNotNone(im)
        for mode in ['original','gray','otsu','adaptive','black_ink']:
            cfg=dict(mode=mode,scale=2.0,clahe=True,sharpen=True,
                     denoise=True,contrast=1.2)
            out=lab.preprocess(im,cfg)
            self.assertEqual(out.shape[:2],tuple(2*n for n in im.shape[:2]))
            self.assertEqual(out.dtype,np.uint8)

    def test_extract_normalized_coords(self):
        detections,raw=lab.collect_predictions([FakeResult()],2.0)
        self.assertEqual(detections[0]['text'],'0.75 DIA')
        self.assertEqual(detections[0]['bbox_original_px'],[5.0,5.0,20.0,12.5])
        self.assertEqual(len(raw),1)

    def test_campaign_resume_and_export(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            models=p/'models'
            for s in ('det','rec'):
                f=models/f'PP-OCRv5_server_{s}'
                f.mkdir(parents=True)
                (f/'local.file').write_text('fake')
            pic=Path(__file__).parent/'25-1.jpg'
            def opts(n):
                return SimpleNamespace(image=pic,workdir=p/'work',
                     models_root=models,variant='server',trials=n,
                     max_hours=0.01,seed=lab.SEED_DEFAULT,retry_errors=False,
                     mem_floor_gb=0,heartbeat_seconds=.05,
                     report_seconds=.2,backup_seconds=.3)
            lab.campaign(opts(2),fake_factory)
            lab.campaign(opts(5),fake_factory)
            db=p/'work/lab.sqlite3'
            con=sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM trials WHERE status='done'").fetchone()[0],5)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM runs').fetchone()[0],1)
            records=con.execute('SELECT config_json,output_path FROM trials ORDER BY trial_index').fetchall()
            self.assertEqual(len(set(r[0] for r in records)),5)
            semantic_count = con.execute('SELECT COUNT(DISTINCT semantic_sha256) FROM trials').fetchone()[0]
            self.assertTrue(1 <= semantic_count <= 5)  # signature stored for grouping
            for _,rel in records:
                with gzip.open(p/'work'/rel,'rt',encoding='utf-8') as fh:
                    data=json.load(fh)
                self.assertEqual(data['detections'][0]['text'],'0.75 DIA')
            self.assertGreater(len(list((p/'work/backups').glob('*.sqlite3'))),0)
            con.close()
            lab.export_cmd(SimpleNamespace(workdir=p/'work',output=None))
            self.assertEqual(len((p/'work/trials.csv').read_text().splitlines()),6)
            self.assertEqual(lab.status_cmd(SimpleNamespace(workdir=p/'work')),0)

    def test_heartbeat_and_timed_backup(self):
        with tempfile.TemporaryDirectory() as td:
            work=Path(td)
            db=work/'lab.sqlite3'
            con=lab.init_db(db)
            con.close()
            monitor=lab.Monitor(work,db,{'target':2000,'done':17,'state':'running'},
                                heartbeat_interval=.05,report_interval=.05,
                                backup_interval=.05)
            monitor.start()
            time.sleep(1.2)
            monitor.close()
            self.assertTrue((work/'heartbeat.json').is_file())
            self.assertIn('ALIVE done=17/2000',(work/'progress.log').read_text())
            self.assertTrue(list((work/'backups').glob('*.sqlite3')))

    def test_sqlite_durable_wal_and_failure(self):
        with tempfile.TemporaryDirectory() as td:
            con=lab.init_db(Path(td)/'test.sqlite3')
            self.assertEqual(con.execute('PRAGMA journal_mode').fetchone()[0],'wal')
            self.assertEqual(con.execute('PRAGMA synchronous').fetchone()[0],2)
            con.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
