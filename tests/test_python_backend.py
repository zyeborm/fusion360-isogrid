"""Pure Python prepared-region regressions: no optional modules required."""
import math
import random
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import geometry as g
import fitting


class PureBackendTests(unittest.TestCase):
    def setUp(self):
        outer=[(0,0),(10,0),(10,10),(0,10)]
        hole=[(5+1.5*math.cos(i*math.tau/32),
               5+1.5*math.sin(i*math.tau/32)) for i in range(32)]
        self.region=g.Region([(outer,True),(hole,False)])

    def test_prepared_python_matches_legacy_margin_boolean(self):
        regions=[self.region]
        prepared=g.PreparedGeometry(regions,.2,.25,backend='python')
        legacy_bands=g._buffer_edges(regions,.2,.25)
        rng=random.Random(61514)
        for _ in range(75):
            x=rng.uniform(-2,12)
            y=rng.uniform(-2,12)
            radius=rng.uniform(.3,4)
            angle=rng.random()*math.tau
            tri=[(x+radius*math.cos(angle+j*math.tau/3),
                  y+radius*math.sin(angle+j*math.tau/3)) for j in range(3)]
            old=g.clip_pocket(tri,regions,legacy_bands)
            new=prepared.clip(tri)
            self.assertAlmostEqual(sum(map(g.area,old)),
                                   sum(map(g.area,new)),delta=1e-6)

    def test_cusp_and_secondary_sketch_mask_match_original(self):
        arc=[(7+7*math.cos(i*math.pi/64),20-7*math.sin(i*math.pi/64))
             for i in range(65)]
        face=g.Region([([(0,0),(20,0),(25,8),(25,20)]+arc+[(0,0)],True),
             ([(10+math.cos(i*math.tau/32),5+math.sin(i*math.tau/32))
               for i in range(32)],False)])
        sketch=g.Region([([(2,2),(22,2),(22,18),(2,18)],True)])
        regs=[face,sketch]
        prepared=g.PreparedGeometry(regs,.2,.25,backend='python')
        bands=g._buffer_edges(regs,.2,.25)
        origin=g.lattice_origin(g.face_bounds(regs),2,13,.12,.07)
        cells=list(g.lattice_pockets(g.face_bounds(regs),2,.2,origin,13))
        # Compare a sample of crossing, excluded and ordinary pockets.
        for cell in cells[::7]:
            old=g.clip_pocket(cell,regs,bands)
            new=prepared.clip(cell)
            self.assertAlmostEqual(sum(map(g.area,old)),
                                   sum(map(g.area,new)),delta=1e-6)

    def test_auto_backend_selection_and_force_python(self):
        auto=g.PreparedGeometry([self.region],.2,.25)
        pure=g.PreparedGeometry([self.region],.2,.25,backend='python')
        self.assertEqual(pure.backend,'python')
        self.assertIsNone(g._CompiledArea)
        self.assertEqual(auto.backend,'python')
        with self.assertRaises(RuntimeError):
            g.PreparedGeometry([self.region],.2,.25,backend='geos')

    def test_de_search_runs_on_python_prepared_engine(self):
        settings=dict(pitch=2.,rib=.2,perimeter=.2,holeclear=.25,
                      dx=0.,dy=0.,angle=0.,corner=.15,nodehole=0.,
                      minfraction=5.,backend='python')
        progress=[]
        fits=fitting.find_fits([self.region],settings,pitch_min=1.6,
             pitch_max=2.6,evaluations=80,progress=lambda n,total:progress.append(n))
        self.assertGreaterEqual(len(fits),2)
        self.assertEqual(progress[0],0)
        self.assertEqual(progress[-1],80)
        for fit in fits:
            self.assertGreaterEqual(fit.pitch,1.6)
            self.assertLessEqual(fit.pitch,2.6)

    def test_boundary_scanline_cache_accepts_max_y(self):
        # Explicitly exercise the highest scanline in a tessellated contour.
        circle=[(5+3*math.cos(i*math.tau/64),
                 5+3*math.sin(i*math.tau/64)) for i in range(64)]
        region=g.Region([(circle,True)])
        self.assertTrue(region.contains((5.,8.),boundary=True))
        self.assertFalse(region.contains((5.,8.),boundary=False))


if __name__=='__main__':
    unittest.main()
