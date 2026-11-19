import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import geometry as g
import fitting


class FittingTests(unittest.TestCase):
    def setUp(self):
        self.region=g.Region([([(0,0),(10,0),(10,10),(0,10)],True)])
        self.s=dict(pitch=2,rib=.2,perimeter=.3,holeclear=.3,dx=0,dy=0,
                    corner=.15,nodehole=.2,minfraction=5,angle=0)

    def test_multiobjective_bounds_and_manual_immutability(self):
        settings=dict(self.s)
        steps=[]
        fits=fitting.find_fits([self.region],settings,pitch_min=1.7,
                 pitch_max=2.5,evaluations=80,
                 progress=lambda done,total:steps.append((done,total)))
        self.assertEqual(settings,self.s)
        self.assertEqual(steps[0],(0,80))
        self.assertEqual(steps[-1],(80,80))
        self.assertTrue(all(done<=total for done,total in steps))
        self.assertGreaterEqual(len(fits),4)
        self.assertLessEqual(len(fits),8)
        self.assertTrue(all(1.7<=fit.pitch<=2.5 for fit in fits))
        self.assertTrue(all(fit.area>0 for fit in fits))
        self.assertEqual([fit.label for fit in fits[:4]],
                         ['Maximum removal','Clean edges','Best symmetry',
                          'Closest to nominal'])

    def test_rotation_selected_anchor_is_deterministic(self):
        args=dict(base_origin=(3,4),anchor='triangle',rotation=33,
                  pitch_min=1.8,pitch_max=2.2,evaluations=80,
                  allow_rotation=True)
        a=fitting.find_fits([self.region],self.s,**args)
        b=fitting.find_fits([self.region],self.s,**args)
        self.assertEqual([(f.label,f.pitch,f.dx,f.dy,f.rotation) for f in a],
                         [(f.label,f.pitch,f.dx,f.dy,f.rotation) for f in b])
        self.assertTrue(all(3<=f.rotation<=63 for f in a))

    def test_infeasible_interval_rejected(self):
        with self.assertRaisesRegex(ValueError,'incompatible'):
            fitting.find_fits([self.region],self.s,pitch_min=.2,
                pitch_max=.5,evaluations=80)
        with self.assertRaisesRegex(ValueError,'minimum pitch'):
            fitting.find_fits([self.region],self.s,pitch_min=2,
                pitch_max=2,evaluations=80)

    def test_progress_cancellation_propagates(self):
        def cancel(done,total):
            if done>=20:raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            fitting.find_fits([self.region],self.s,pitch_min=1.8,
                pitch_max=2.2,evaluations=80,progress=cancel)


if __name__=='__main__':unittest.main()
