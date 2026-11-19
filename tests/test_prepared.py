"""Regression tests for the shared cached geometry used by Auto Fit and cut."""
import math
import random
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import geometry as g


class PreparedTests(unittest.TestCase):
    def setUp(self):
        arc=[(7+7*math.cos(t*math.pi/64),20-7*math.sin(t*math.pi/64))
             for t in range(65)]
        self.complex=g.Region([
            ([(0,0),(20,0),(25,8),(25,20)]+arc+[(0,0)],True),
            ([(10+math.cos(t*math.tau/64),5+math.sin(t*math.tau/64))
              for t in range(64)],False),
            ([(18+.8*math.cos(t*math.tau/32),11+.8*math.sin(t*math.tau/32))
              for t in range(32)],False)])

    def test_reusable_prepare_does_not_change_outputs(self):
        prep=g.PreparedGeometry([self.complex],.2,.25)
        for dx,dy,rot in ((0,0,0),(.13,.05,7),(.27,-.06,25)):
            kw=dict(corner_radius=.15,max_cells=1000,
                    vertex_hole_diameter=.18)
            cached=g.make_pockets([self.complex],2,.2,.2,.25,dx,dy,rot,
                                  prepared=prep,**kw)
            ordinary=g.make_pockets([self.complex],2,.2,.2,.25,dx,dy,rot,**kw)
            self.assertEqual(len(cached),len(ordinary))
            for a,b in zip(cached,ordinary):
                self.assertAlmostEqual(
                    sum(g.area(p) for p in a.loops),
                    sum(g.area(p) for p in b.loops),places=8)

    def test_bulk_and_individual_agree(self):
        prep=g.PreparedGeometry([self.complex],.2,.25)
        rng=random.Random(61)
        triangles=[]
        for _ in range(40):
            x=rng.uniform(-3,30);y=rng.uniform(-3,26)
            d=rng.uniform(.25,4);rot=rng.uniform(0,6)
            triangles.append([(x+d*math.cos(rot+j*math.tau/3),
                               y+d*math.sin(rot+j*math.tau/3))
                               for j in range(3)])
        for one,many in zip([prep.clip(t) for t in triangles],
                            prep.clip_many(triangles)):
            self.assertAlmostEqual(sum(map(g.area,one)),
                                   sum(map(g.area,many)),places=7)

    def test_compiled_milled_pockets_are_inside_mask(self):
        if g._CompiledArea is None:
            self.skipTest('Compiled GEOS backend unavailable')
        from shapely.geometry import Polygon
        prep=g.PreparedGeometry([self.complex],.2,.25)
        shapes=g.make_pockets([self.complex],2,.2,.2,.25,.13,.08,14,.15,
                              max_cells=1000,vertex_hole_diameter=.18,
                              prepared=prep)
        self.assertGreater(len(shapes),50)
        allowed=prep.compiled.allowed.buffer(.00001)
        for item in shapes:
            if item.circle:
                # Full circle radius, not merely its faceted display polygon.
                from shapely.geometry import Point
                c,r=item.circle
                self.assertTrue(allowed.covers(Point(c).buffer(r,quad_segs=32)))
            else:
                from shapely.ops import unary_union
                polys=[Polygon(p) for p in item.loops if g.area(p)>0]
                for poly in polys:
                    self.assertTrue(allowed.covers(poly), 'Pocket crosses margin')

if __name__=='__main__':unittest.main()
