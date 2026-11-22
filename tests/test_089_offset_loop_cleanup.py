"""Geometry-only regression: remove self-intersecting offset lobes once.

The production Fusion add-in and its default clipping path remain untouched.
"""
import math
import pathlib
import sys
import unittest

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import curves2d as c
import geometry as g
from offset_cleanup import (OffsetInterval,clean_closed_offset,clean_open_offset,
                            self_crossings)
from shared_boundary import Boundary

try:
    from shapely.geometry import Polygon
except ImportError:
    Polygon=None


class OffsetLoopCleanupTests(unittest.TestCase):
    def setUp(self):
        self.ellipse=c.Ellipse((0.,0.),(4.,0.),(0.,1.))

    def test_closed_inset_removes_only_invalid_lobes(self):
        for margin in (.3,.6,.9):
            with self.subTest(margin=margin):
                off=c.Offset(self.ellipse,margin)
                self.assertEqual(len(self_crossings(off)),2)
                loops=clean_closed_offset(self.ellipse,margin,True)
                self.assertEqual(len(loops),1)
                self.assertEqual(len(loops[0]),2)
                self.assertTrue(c.close_loop(loops[0],1e-8))
                self.assertTrue(all(isinstance(seg,OffsetInterval)
                                    and seg.source.base is self.ellipse
                                    for seg in loops[0]))
                self.assertGreater(c.loop_area(loops[0]),0.)
                for seg in loops[0]:
                    for j in range(1,20):
                        p=seg.point(j/20)
                        self.assertGreaterEqual(c.point_distance(self.ellipse,p),margin-2e-5)

    def test_inset_matches_independent_polygon_erosion(self):
        if Polygon is None:self.skipTest('Shapely used for independent reference')
        source=Polygon(c.sample([self.ellipse],1e-5))
        for margin in (.1,.3,.6,.9):
            with self.subTest(margin=margin):
                loops=clean_closed_offset(self.ellipse,margin,True)
                self.assertEqual(len(loops),1)
                result=Polygon(c.sample(loops[0],1e-5))
                expected=source.buffer(-margin,quad_segs=96)
                self.assertLess(result.symmetric_difference(expected).area,5e-5)

    def test_offset_larger_than_minor_radius_removes_region(self):
        self.assertEqual(clean_closed_offset(self.ellipse,1.,True),[])
        self.assertEqual(clean_closed_offset(self.ellipse,1.2,True),[])

    def test_open_cubic_spline_loop_removal_preserves_curve_parameters(self):
        spline=c.Nurbs(((0.,0.),(1.,2.),(2.,-2.),(3.,0.)),3,
                       (0.,)*4+(1.,)*4,(1.,)*4,0.,1.)
        off=c.Offset(spline,.5)
        self.assertEqual(len(self_crossings(off)),1)
        pieces=clean_open_offset(spline,.5)
        self.assertEqual(len(pieces),2)
        self.assertLess(c.length(c.sub(pieces[0].end,pieces[1].start)),1e-8)
        self.assertTrue(all(isinstance(seg,OffsetInterval)
                            and seg.source.base is spline for seg in pieces))
        self.assertLess(c.length(c.sub(pieces[0].start,off.start)),1e-10)
        self.assertLess(c.length(c.sub(pieces[-1].end,off.end)),1e-10)
        for seg in pieces:
            for j in range(1,20):
                self.assertGreaterEqual(c.point_distance(spline,seg.point(j/20)),.5-2e-5)

    def test_direct_clipping_uses_cleaned_parametric_boundaries(self):
        if Polygon is None:self.skipTest('Shapely used for independent reference')
        region=g.Region([(c.sample([self.ellipse],.0005),True)],curve_loops=[[self.ellipse]])
        cleaned=Boundary([region],.6,.6)
        self.assertTrue(cleaned.offset_cleaned)
        self.assertEqual([len(loop) for loop in cleaned.loops],[2])
        allowed=Polygon(c.sample([self.ellipse],1e-5)).buffer(-.6,quad_segs=96)
        # Mix triangles entirely inside, entirely outside and crossing the
        # two different retained offset intervals.
        triangles=[[(x-.5,y-.25),(x+.5,y-.25),(x,y+.5)]
                   for x in (-3.5,-2.,0.,2.,3.5) for y in (-.6,-.15,.3,.75)]
        for tri in triangles:
            clipped=cleaned.clip(tri)
            shapes=[Polygon(c.sample(loop,2e-5)) for loop in clipped]
            ours=sum(p.area for p in shapes)
            reference=allowed.intersection(Polygon(tri)).area
            self.assertAlmostEqual(ours,reference,delta=3e-5)
            for loop in clipped:
                self.assertTrue(c.close_loop(loop,2e-5))

    def test_simple_circle_retains_closed_offset(self):
        circle=c.circle((2.,2.),2.)
        loops=clean_closed_offset(circle,.5,True)
        self.assertEqual(len(loops),1)
        self.assertEqual(len(loops[0]),1)
        self.assertAlmostEqual(c.loop_area(loops[0]),math.pi*1.5**2,delta=.0001)


if __name__=='__main__':unittest.main()
