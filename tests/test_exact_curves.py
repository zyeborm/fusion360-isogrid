"""Analytic line/arc regression tests (only standard library required)."""
import math
import random
import sys
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import curves2d as c
import exact_clipper as e
import geometry as g
from test_preview_lifecycle import load_fusion_ui


def loop_square(size=10):
    return [c.Line((0,0),(size,0)),c.Line((size,0),(size,size)),
            c.Line((size,size),(0,size)),c.Line((0,size),(0,0))]


def curved_panel():
    # A concave circular arc cuts into an otherwise rectangular solid; the
    # interior circle is the second protected opening.
    exterior=[c.Line((0,0),(20,0)),c.Line((20,0),(20,12)),
              c.Line((20,12),(14,12)),
              c.Arc((10,12),(14,12),(6,12),-math.pi),
              c.Line((6,12),(0,12)),c.Line((0,12),(0,0))]
    void=[c.circle((12,4),1.1,False)]
    return e.CurveRegion([(exterior,True),(void,False)])


class CurvePrimitiveTests(unittest.TestCase):
    def test_line_arc_intersections_are_exact(self):
        line=c.Line((-3,0),(3,0));arc=c.Arc((0,0),(2,0),(-2,0),math.pi)
        self.assertEqual(len(c.intersections(line,arc)),2)
        self.assertTrue(any(c.near(p,(2,0)) for p in c.intersections(line,arc)))
        self.assertTrue(any(c.near(p,(-2,0)) for p in c.intersections(line,arc)))

    def test_arc_arc_intersection(self):
        a=c.circle((0,0),2)
        b=c.circle((2,0),2)
        p=c.intersections(a,b)
        self.assertEqual(len(p),2)
        self.assertAlmostEqual(p[0][1]**2,3,places=8)

    def test_area_and_centroid_analytic(self):
        x,y=(5,3)
        loop=[c.circle((x,y),2)]
        self.assertAlmostEqual(c.loop_area(loop),4*math.pi,places=10)
        self.assertAlmostEqual(c.loop_centroid(loop)[0],x,places=10)
        self.assertAlmostEqual(c.loop_centroid(loop)[1],y,places=10)
        self.assertAlmostEqual(c.loop_area(c.reverse_loop(loop)),-4*math.pi,places=10)

    def test_curve_containment_cw_hole(self):
        region=curved_panel()
        self.assertTrue(region.contains((3,3)))
        self.assertFalse(region.contains((12,4)))
        self.assertFalse(region.contains((10,10)))  # inside concave cutout
        self.assertTrue(region.contains((10,5)))

    def test_full_circle_clearance(self):
        prep=e.PreparedCurves([curved_panel()],.2,.3)
        self.assertFalse(prep.circle_fits((12,4),.2))
        self.assertFalse(prep.circle_fits((12,5.6),.3))
        self.assertTrue(prep.circle_fits((3,3),.3))

    def test_exact_arc_fillets_on_square(self):
        path=e.fillet_loop(loop_square(5),.25)
        self.assertEqual(len([s for s in path if isinstance(s,c.Arc)]),4)
        self.assertTrue(c.close_loop(path))
        self.assertAlmostEqual(c.loop_area(path),25-(4-math.pi)*.25**2,places=8)
        for seg in path:
            if isinstance(seg,c.Arc):
                self.assertAlmostEqual(seg.radius,.25,places=8)
                self.assertAlmostEqual(seg.sweep,math.pi/2,places=8)

    def test_line_arc_fillets_are_tangent(self):
        # First clip a triangular pocket around the true circular void.
        prep=e.PreparedCurves([e.CurveRegion([(loop_square(),True),
                        ([c.circle((5,5),1.2,False)],False)])],.3,.4)
        contours=prep.clip([(4,4),(7,4),(5,8)])
        self.assertTrue(any(isinstance(seg,c.Arc) for loop in contours for seg in loop))
        for loop in contours:
            warnings=[];filleted=e.fillet_loop(loop,.15,warnings)
            self.assertFalse(warnings)
            self.assertTrue(c.close_loop(filleted))
            for i,seg in enumerate(filleted):
                nxt=filleted[(i+1)%len(filleted)]
                self.assertGreater(c.dot(seg.tangent(1),nxt.tangent(0)),.99999)

    def test_fragment_areas_against_exact_circle(self):
        p=e.PreparedCurves([e.CurveRegion([(loop_square(),True),
            ([c.circle((5,5),1.2,False)],False)])],0,0)
        # A covering polygon contains a complete circular hole.  The result
        # has one CCW exterior and one CW *analytic* circle boundary.
        outlines=p.clip([(-1,-1),(11,-1),(11,11),(-1,11)])
        self.assertEqual(len(outlines),2)
        self.assertAlmostEqual(sum(c.loop_area(x) for x in outlines),100-1.2**2*math.pi,places=8)
        self.assertEqual(sum(isinstance(seg,c.Arc) for loop in outlines for seg in loop),1)

    def test_random_triangles_with_round_hole(self):
        try:from shapely.geometry import Point,Polygon,box
        except ImportError:self.skipTest('Shapely installed only for the independent test oracle')
        rng=random.Random(3192)
        prep=e.PreparedCurves([e.CurveRegion([(loop_square(),True),
            ([c.circle((5,5),1.25,False)],False)])],.3,.4)
        oracle=box(.3,.3,9.7,9.7).difference(Point(5,5).buffer(1.65,quad_segs=1024))
        for _ in range(250):
            x=rng.uniform(-1,10);y=rng.uniform(-1,10);side=rng.uniform(.4,3)
            tri=[(x,y),(x+side,y),(x+side/2,y+math.sqrt(3)/2*side)]
            output=prep.clip(tri)
            got=sum(c.loop_area(loop) for loop in output)
            expected=Polygon(tri).intersection(oracle).area
            self.assertLess(abs(got-expected),.00002,(tri,got,expected))
            for loop in output:self.assertTrue(c.close_loop(loop))

    def test_full_pattern_arc_output_matches_generated_preview(self):
        region=curved_panel()
        source=g.Region([(c.sample(path,.001),outer) for path,outer in region.loops],
                        curve_loops=[path for path,_ in region.loops])
        prepared=g.PreparedGeometry([source],.3,.3)
        self.assertEqual(prepared.backend,'exact')
        shapes=g.make_pockets([source],2.2,.2,.3,.3,0,0,0,.13,
                              max_cells=1000,prepared=prepared)
        self.assertGreater(len(shapes),25)
        arcs=[s for shape in shapes for loop in shape.curve_loops or []
              for s in loop if isinstance(s,c.Arc)]
        self.assertGreater(len(arcs),len(shapes))
        for shape in shapes:
            for path in shape.curve_loops or []:self.assertTrue(c.close_loop(path,2e-5))
        self.assertTrue(any(abs(s.radius-(4+.3))<1e-5 for s in arcs),
                        'Original rounded perimeter should remain an exact offset arc')

    def test_fusion_curve_extraction_with_mock_evaluator(self):
        ui=load_fusion_ui()
        class V:
            def __init__(self,x,y):self.x=x;self.y=y;self.z=0
        frame=SimpleNamespace(to_xy=lambda pt:(pt.x,pt.y))
        class E:
            def getEndPoints(self):return True,V(2,0),V(-2,0)
            def getParameterExtents(self):return True,0,1
            def getPointAtParameter(self,t):return True,V(2*math.cos(t*math.pi),2*math.sin(t*math.pi))
        class Class:
            @staticmethod
            def classType():return 'arc'
        kind=SimpleNamespace(Arc3D=Class,
                             Circle3D=SimpleNamespace(classType=lambda:'circle'),
                             Line3D=SimpleNamespace(classType=lambda:'line'))
        with patch.object(ui.adsk.core,'Arc3D',kind.Arc3D,create=True),\
             patch.object(ui.adsk.core,'Circle3D',kind.Circle3D,create=True),\
             patch.object(ui.adsk.core,'Line3D',kind.Line3D,create=True):
            path=ui._analytic_curve(SimpleNamespace(objectType='arc',center=V(0,0)),E(),frame,.001)
        self.assertEqual(len(path),1)
        self.assertIsInstance(path[0],c.Arc)
        self.assertAlmostEqual(path[0].sweep,math.pi,places=8)

if __name__=='__main__':unittest.main()
