import unittest
import numpy as np
import cv2
import tempfile
import json
from pathlib import Path
from argparse import Namespace
from autotune import choose_masks, Evaluator, change_one, optimize
import random

DIR=Path(__file__).resolve().parent

class AutoTest(unittest.TestCase):
    def test_blank_rejected(self):
        with self.assertRaises(ValueError): Evaluator(np.full((150,250,3),255,np.uint8))

    def test_black_closed_step(self):
        img=cv2.imread(str(DIR/'1716312482033.jpeg'))
        ev=Evaluator(img)
        self.assertTrue(any(s.startswith('gray') for s in ev.ids))
        p={k:v[0] for k,v in ev.param_space.items()}
        p['mask_id']=next(n for n in ev.ids if n.startswith('gray'))
        p['epsilon']=.009
        r=ev.evaluate(p,full=True)
        self.assertTrue(r['valid'])
        self.assertGreaterEqual(r['score'],85)

    def test_blue_uses_color_candidate(self):
        ev=Evaluator(cv2.imread(str(DIR/'ShopAI_Front_View_mm.png')))
        self.assertTrue(any('color_' in s for s in ev.ids))

    def test_red_contour_and_internals(self):
        ev=Evaluator(cv2.imread(str(DIR/'25-1.jpg')))
        name=next(k for k in ev.ids if k.startswith('color_'))
        p={k:v[0] for k,v in ev.param_space.items()};p.update(mask_id=name,epsilon=.002)
        r=ev.evaluate(p,full=True)
        self.assertGreater(r['score'],80)
        self.assertGreaterEqual(len(r['internal_contours']),2)
        self.assertGreater(len(r['outline_vertices_px']),10)

    def test_hue_not_hardcoded(self):
        img=cv2.imread(str(DIR/'25-1.jpg'))
        hsv=cv2.cvtColor(img,cv2.COLOR_BGR2HSV)
        sat=hsv[:,:,1]>=55
        hsv[:,:,0][sat]=65
        green=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)
        ev=Evaluator(green)
        self.assertTrue(any(k.startswith('color_') for k in ev.ids))
        self.assertTrue(any('h65' in k or 'h75' in k for k in ev.ids))

    def test_single_param_mutation(self):
        ev=Evaluator(cv2.imread(str(DIR/'25-1.jpg')))
        params={k:v[0] for k,v in ev.param_space.items()};rng=random.Random(31)
        for k in ev.param_space:
            q=change_one(rng,params,k,ev.param_space)
            self.assertEqual(sum(params[x]!=q[x] for x in params),1)

    def test_registry_and_early_stop(self):
        image=DIR/'25-1.jpg'
        args=Namespace(image=image,seed=17,trials=170,
                       early_stop=True,min_trials=80,patience=45,target=95.)
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);r=optimize(cv2.imread(str(image)),args,root/'run1',root/'registry.json')
            self.assertEqual(r['geometry']['units'],'pixels')
            self.assertTrue(r['review_required'])
            self.assertTrue((root/'run1/report.html').exists())
            self.assertEqual(len(json.loads((root/'registry.json').read_text())['previous']),1)
            optimize(cv2.imread(str(image)),args,root/'run2',root/'registry.json')
            self.assertEqual(len(json.loads((root/'registry.json').read_text())['previous']),1)

if __name__=='__main__':unittest.main()
