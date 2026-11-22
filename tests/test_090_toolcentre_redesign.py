"""Analytic erosion/intersection/dilation experiment, independent of Fusion.

Validation uses an independent polygonal Minkowski construction (Shapely)
only as a test oracle; the generated output is still native parametric curves.
"""
import math
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import curves2d as c
import exact_clipper as exact
import geometry as g
import tool_center as t
from test_curved_dxf_regression import test_regions

try:
    from shapely.geometry import Polygon, Point
    from shapely.ops import unary_union
except ImportError:
    Polygon=Point=unary_union=None


def rectangle(w,h):
    pts=[(0.,0.),(w,0.),(w,h),(0.,h)]
    return [c.Line(p,q) for p,q in zip(pts,pts[1:]+pts[:1])]


def source(loops):
    return g.Region([(c.sample(loop,.0005),i==0) for i,loop in enumerate(loops)],
                    curve_loops=loops)


def shapely_loops(loops):
    positives=[Polygon(c.sample(loop,.000002)) for loop in loops if c.loop_area(loop)>0]
    negatives=[Polygon(c.sample(loop,.000002)) for loop in loops if c.loop_area(loop)<0]
    return unary_union(positives).difference(unary_union(negatives))


class FullToolCentreTests(unittest.TestCase):
    def test_triangle_erosion_is_analytic_and_inward(self):
        tri=[(0,0),(4,0),(2,2*math.sqrt(3))]
        got=t.inset_triangle(tri,.2)
        self.assertEqual(len(got),3)
        self.assertEqual(t.inset_triangle(tri,2.),[])
        if Polygon:
            expected=Polygon(tri).buffer(-.2,quad_segs=64,join_style='mitre')
            self.assertLess(Polygon(got).symmetric_difference(expected).area,1e-8)

    def test_polygon_only_region_uses_same_centre_geometry(self):
        points=[(0.,0.),(10.,0.),(10.,8.),(0.,8.)]
        polygon_region=g.Region([(points,True)])
        curve_region=source([rectangle(10,8)])
        tri=[(1.,1.),(7.,1.),(4.,6.)]
        a=t.ToolCentre([polygon_region],.2,.2,.15).pocket(tri)
        b=t.ToolCentre([curve_region],.2,.2,.15).pocket(tri)
        self.assertEqual(len(a),len(b))
        self.assertAlmostEqual(c.loop_area(a[0]),c.loop_area(b[0]),places=8)

    def test_no_legacy_fillet_or_morphological_repair(self):
        r=source([rectangle(10,8)])
        with patch.object(exact,'rounded_pocket',side_effect=AssertionError('Old rounding path called')):
            with patch.object(exact,'_round_by_opening',side_effect=AssertionError('Old repair path called')):
                e=t.ToolCentre([r],.2,.2,.15)
                curves=e.pocket([(1,1),(7,1),(4,6)])
        self.assertEqual(len(curves),1)
        self.assertTrue(c.close_loop(curves[0],2e-5))
        self.assertEqual(sum(isinstance(seg,c.Arc) for seg in curves[0]),3)

    def test_concave_join_trims_offset_lines_without_boolean(self):
        pts=[(0,0),(5,0),(5,2),(2,2),(2,5),(0,5)]
        src=[c.Line(p,q) for p,q in zip(pts,pts[1:]+pts[:1])]
        for radius in (.1,.25,.5):
            with self.subTest(radius=radius):
                out=t.expand_center_loop(src,radius)
                self.assertIsNotNone(out)
                self.assertTrue(c.close_loop(out,2e-5))
                self.assertEqual(len([s for s in out if isinstance(s,c.Arc)]),5)
                if Polygon:
                    expected=Polygon(pts).buffer(radius,quad_segs=128)
                    got=shapely_loops([out])
                    self.assertLess(expected.symmetric_difference(got).area,3e-5)

    def test_fully_enclosed_round_void_is_preserved(self):
        outer=rectangle(10,8)
        inner=[c.circle((5.,3.5),1.,False)]
        reg=source([outer,inner])
        engine=t.ToolCentre([reg],.2,.2,.2)
        tri=[(1,1),(9,1),(5,7)]
        loops=engine.pocket(tri)
        self.assertEqual(len(loops),2)
        self.assertEqual(sum(c.loop_area(loop)>0 for loop in loops),1)
        self.assertEqual(sum(c.loop_area(loop)<0 for loop in loops),1)
        self.assertAlmostEqual(-c.loop_area(loops[-1]),math.pi*1.2**2,delta=1e-5)
        if Polygon:
            expected=(Polygon(tri).buffer(-.2,quad_segs=192)
                      .difference(Point(5,3.5).buffer(1.4,quad_segs=192))
                      .buffer(.2,quad_segs=192))
            self.assertLess(expected.symmetric_difference(shapely_loops(loops)).area,6e-5)

    def test_closed_ellipse_parallel_cleanup_integrates_into_full_opening(self):
        base=[c.Ellipse((0.,0.),(4.,0.),(0.,1.))]
        r=source([base]);tri=[(-12,-10),(12,-10),(0,15)]
        for margin,radius in ((.3,.15),(.5,.2)):
            engine=t.ToolCentre([r],margin,margin,radius)
            self.assertTrue(engine.boundary.offset_cleaned)
            loops=engine.pocket(tri)
            self.assertEqual(len(loops),1)
            self.assertTrue(c.close_loop(loops[0],3e-5))
            self.assertTrue(any(isinstance(s,c.Arc) for s in loops[0]))
            if Polygon:
                src=Polygon(c.sample(base,1e-5))
                expected=src.buffer(-(margin+radius),quad_segs=192).buffer(radius,quad_segs=192)
                self.assertLess(shapely_loops(loops).symmetric_difference(expected).area,4e-5)

    def test_curved_fixture_opening_and_split_islands(self):
        regions=test_regions()
        for pitch,dx,dy in ((2.,0.,0.),(1.928114,.921259,.567284)):
            with self.subTest(pitch=pitch):
                shapes,engine=t.make_toolcentre_pockets(
                    regions,pitch,.2,.3,.3,dx,dy,0,.15,
                    vertex_hole_diameter=.3,max_cells=1600)
                self.assertEqual(len(shapes),132 if pitch==2. else 131)
                self.assertEqual(engine.nonconvex,0)
                self.assertTrue(all(c.close_loop(l,3e-5)
                                    for s in shapes for l in (s.curve_loops or [])))
                if pitch!=2.:
                    # Two feasible islands on either side of the source hole.
                    keys=[s for s in shapes if s.circle is None and
                          abs(g.polygon_centroid(s.outline)[0]-1.780832)<.0001 and
                          abs(g.polygon_centroid(s.outline)[1]-1.41495)<.0001]
                    self.assertEqual(len(keys),1)
                    self.assertEqual(len(keys[0].curve_loops),2)
                    if Polygon:
                        src=Polygon(c.sample(regions[0].curve_loops[0],1e-5),
                                    holes=[c.sample(regions[0].curve_loops[1],1e-5)])
                        triangle=Polygon(keys[0].outline)
                        truth=triangle.buffer(-.15,quad_segs=160).intersection(
                            src.buffer(-.45,quad_segs=160)).buffer(.15,quad_segs=160)
                        self.assertLess(shapely_loops(keys[0].curve_loops).symmetric_difference(truth).area,
                                        6e-5)

if __name__=='__main__':unittest.main()
