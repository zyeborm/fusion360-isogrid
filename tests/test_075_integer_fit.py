"""Regression tests for scale-free boundary quality and multi-start selection."""
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fit_quality as q
import geometry as g
import fitting


class QualityTests(unittest.TestCase):
    def test_scale_invariance(self):
        cells=[((i*.6,0.),.55) for i in range(8)]
        a=q.evaluate(cells,1.,13.)
        for scale in (.04,100.):
            b=q.evaluate([((x*scale,y*scale),f) for (x,y),f in cells],
                         scale,13*scale)
            self.assertAlmostEqual(a.score,b.score,places=12)
            self.assertEqual(a.longest_run,b.longest_run)
            self.assertAlmostEqual(a.strip_damage,b.strip_damage,places=12)

    def test_partial_strip_penalised_beyond_partial_cell_count(self):
        step=1/math.sqrt(3)
        straight=[((i*step,0.),.5) for i in range(8)]
        scattered=[((i*2.5,0.),.5) for i in range(8)]
        a=q.evaluate(straight,1.,24.)
        b=q.evaluate(scattered,1.,24.)
        self.assertEqual(a.partial_count,b.partial_count)
        self.assertGreaterEqual(a.longest_run,7)
        self.assertEqual(b.longest_run,1)
        self.assertLess(a.score,b.score)

    def test_full_cells_are_unpenalised(self):
        cells=[((i*.6,0.),1.) for i in range(15)]
        quality=q.evaluate(cells,1.,12.)
        self.assertEqual(quality.score,1.)
        self.assertEqual(quality.partial_count,0)


class OptimiserTests(unittest.TestCase):
    def setUp(self):
        self.region=g.Region([([(0,0),(12,0),(12,4),(0,4)],True)])
        self.s=dict(pitch=5.,rib=.18,perimeter=.13,holeclear=.13,
                    dx=0.,dy=0.,corner=.11,nodehole=0.,
                    minfraction=5.,angle=0.,backend='python')

    def test_nominal_bad_partial_row_is_improved(self):
        b=g.face_bounds([self.region]);s=self.s
        raw=g.make_pockets([self.region],s['pitch'],s['rib'],s['perimeter'],
            s['holeclear'],0,0,0,s['corner'],s['minfraction']/100)
        boundary=2*(12+4)
        baseline=fitting._metrics(raw,5.,s['rib'],s['corner'],b,48.,5.,2.3,6.5,boundary)
        fits=fitting.find_fits([self.region],s,pitch_min=2.3,pitch_max=6.5,
                               evaluations=160,seed=73021)
        quality=fits[0]
        self.assertIn(quality.label,('Integer fit','Alternative fit'))
        self.assertEqual(fits[-1].label,'Maximum removal')
        self.assertLess(quality.partials,baseline[3])
        self.assertGreater(quality.fit_quality,baseline[-1].score)
        self.assertGreater(abs(quality.pitch-s['pitch']),.3)

    def test_pitch_diversity_and_determinism(self):
        a=fitting.find_fits([self.region],self.s,pitch_min=2.3,
                            pitch_max=6.5,evaluations=120,seed=73021)
        b=fitting.find_fits([self.region],self.s,pitch_min=2.3,
                            pitch_max=6.5,evaluations=120,seed=73021)
        self.assertEqual([(f.label,f.pitch,f.dx,f.dy,f.rotation) for f in a],
                         [(f.label,f.pitch,f.dx,f.dy,f.rotation) for f in b])
        distinct=[f for f in a if f.label=='Integer fit']
        self.assertGreaterEqual(len(distinct),2)
        for x,y in zip(distinct,distinct[1:]):
            self.assertGreater(abs(x.pitch-y.pitch)/max(y.pitch,1e-9),.075)

if __name__=='__main__':unittest.main()
