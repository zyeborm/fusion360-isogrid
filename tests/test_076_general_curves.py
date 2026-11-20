"""v0.7.6: general Fusion planar boundary curves, no native dependencies."""
import math
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import curves2d as c
import exact_clipper as e
import geometry as g
from test_preview_lifecycle import load_fusion_ui


def rect():
    return [c.Line((0,0),(10,0)),c.Line((10,0),(10,10)),
            c.Line((10,10),(0,10)),c.Line((0,10),(0,0))]


class GeneralCurveTests(unittest.TestCase):
    def test_full_ellipse_area_centroid_winding(self):
        ell=c.Ellipse((5,6),(3,0),(0,1.5))
        self.assertAlmostEqual(c.loop_area([ell]),4.5*math.pi,9)
        x,y=c.loop_centroid([ell]);self.assertAlmostEqual(x,5,5);self.assertAlmostEqual(y,6,5)
        self.assertTrue(c.loop_contains([ell],(5,6)))
        self.assertFalse(c.loop_contains([ell],(8.5,6)))
        self.assertAlmostEqual(c.loop_area([ell.reverse()]),-4.5*math.pi,9)
        self.assertEqual(c.bounds(ell),(2.,4.5,8.,7.5))

    def test_ellipse_line_exact_intersections_and_clipped_sweep(self):
        ell=c.Ellipse((0,0),(3,0),(0,2),0,math.pi)
        crossings=c.intersections(ell,c.Line((-4,0),(4,0)))
        self.assertEqual(len(crossings),2)
        self.assertTrue(any(c.near(q,(-3,0)) for q in crossings))
        section=ell.section(.25,.75)
        crossings=c.intersections(section,c.Line((-4,0),(4,0)))
        self.assertEqual(crossings,[])
        self.assertTrue(c.near(section.reverse().end,section.start))

    def test_exact_rational_quadratic_export_of_ellipse(self):
        ellipse=c.Ellipse((1,2),(5,0),(0,2),.3,4.8)
        items=c.ellipse_quadratics(ellipse)
        self.assertGreaterEqual(len(items),3)
        for i,(ctrl,weights) in enumerate(items):
            spline=c.Nurbs(ctrl,2,(0,0,0,1,1,1),weights,0,1)
            self.assertTrue(c.near(spline.start,ellipse.point(i/len(items))))
            for t in (.1,.25,.5,.75,.9):
                p=spline.point(t)
                self.assertIsNotNone(c.parameter(ellipse,p,1e-9))
                self.assertLess(c.length(c.sub(p,ellipse.point(c.parameter(ellipse,p,1e-9)))),1e-10)
            self.assertLess(c.length(c.sub(spline.point(.5),ellipse.point((i+.5)/len(items)))),1e-12)

    def test_rational_nurbs_trim_preserves_original(self):
        source=c.Nurbs(((0.,0.),(2.,4.),(4.,1.),(6.,3.),(8.,0.)),3,
                       (0,0,0,0,.5,1,1,1,1),(1,1.4,1,2,1),.13,.87)
        trimmed=c.trimmed_nurbs(source)
        self.assertEqual(trimmed.degree,source.degree)
        self.assertEqual(trimmed.knots[:4],(.13,)*4)
        self.assertEqual(trimmed.knots[-4:],(.87,)*4)
        for t in (0,.05,.1,.3,.5,.7,.9,.95,1):
            self.assertLess(c.length(c.sub(source.point(t),trimmed.point(t))),1e-11)
        backward=c.trimmed_nurbs(source.reverse())
        # The exact clamped NURBS uses ascending knots; sketch edges are
        # topologically unoriented and may be traversed in either direction.
        self.assertLess(c.length(c.sub(backward.start,source.start)),1e-11)
        self.assertLess(c.length(c.sub(backward.end,source.end)),1e-11)

    def test_nurbs_line_intersections_numeric_refinement(self):
        spline=c.Nurbs(((0.,0.),(2.,4.),(4.,0.)),2,
                       (0,0,0,1,1,1),(1.,1.,1.),0,1)
        hits=c.intersections(spline,c.Line((0,1),(4,1)))
        self.assertEqual(len(hits),2)
        self.assertAlmostEqual(hits[0][1],1,places=6)
        self.assertTrue(any(abs(p[0]-(2-math.sqrt(2)))<1e-6 for p in hits))
        self.assertTrue(any(abs(p[0]-(2+math.sqrt(2)))<1e-6 for p in hits))

    def test_exact_elliptical_clearance_and_clipped_contours(self):
        ell=c.Ellipse((5,5),(3,0),(0,2),0,-math.tau)
        reg=e.CurveRegion([(rect(),True),([ell],False)])
        prep=e.PreparedCurves([reg],.2,.3)
        self.assertFalse(prep.circle_fits((2,5),.1))
        self.assertTrue(prep.circle_fits((1,1),.1))
        triangle=[(2.1732050807568877,3.367949192431123),
                  (3.8267949192431123,3.367949192431123),(3.,4.8)]
        fragments=prep.clip(triangle)
        self.assertEqual(len(fragments),1)
        self.assertTrue(c.close_loop(fragments[0],2e-5))
        self.assertTrue(any(isinstance(seg,c.Offset) for seg in fragments[0]))
        self.assertGreater(c.loop_area(fragments[0]),.03)

    def test_full_pattern_with_elliptical_hole_remains_native(self):
        ell=c.Ellipse((5,5),(3,0),(0,2),0,-math.tau)
        paths=[(rect(),True),([ell],False)]
        region=g.Region([(c.sample(path,.002),outer) for path,outer in paths],
                        curve_loops=[path for path,_ in paths])
        prepared=g.PreparedGeometry([region],.2,.3)
        shapes=g.make_pockets([region],2,.2,.2,.3,0,0,0,.15,
                              max_cells=1000,prepared=prepared)
        self.assertGreater(len(shapes),40)
        offsets=[seg for shape in shapes for loop in shape.curve_loops or []
                 for seg in loop if isinstance(seg,c.Offset)]
        self.assertGreater(len(offsets),5)
        for shape in shapes:
            for loop in shape.curve_loops or []:
                self.assertTrue(c.close_loop(loop,2e-5))

    def test_offset_cubic_splines_are_continuous(self):
        ellipse=c.Ellipse((0,0),(3,0),(0,2))
        off=c.Offset(ellipse,.2)
        spans=c.approximate_cubic_beziers(off,1e-4)
        self.assertGreaterEqual(len(spans),4)
        self.assertLessEqual(len(spans),64)
        for i,pts in enumerate(spans):
            next_pts=spans[(i+1)%len(spans)]
            self.assertTrue(c.near(pts[-1],next_pts[0],2e-8))

    def test_curved_spline_exterior_with_margin(self):
        # This remains a B-spline throughout geometry clipping, including
        # its non-circular clearance offset near the arched top of the part.
        roof=c.Nurbs(((10.,10.),(5.,13.),(0.,10.)),2,
                     (0.,0.,0.,1.,1.,1.),(1.,1.,1.),0.,1.)
        boundary=[c.Line((0.,0.),(10.,0.)),
                  c.Line((10.,0.),(10.,10.)),roof,
                  c.Line((0.,10.),(0.,0.))]
        region=e.CurveRegion([(boundary,True)])
        self.assertTrue(region.contains((5.,10.5)))
        self.assertFalse(region.contains((5.,12.)))
        clipped=e.PreparedCurves([region],.2,.2).clip(
            [(4.2,9.1),(6.2,9.1),(5.2,12.0)])
        self.assertEqual(len(clipped),1)
        self.assertTrue(c.close_loop(clipped[0],2e-5))
        self.assertGreater(c.loop_area(clipped[0]),.1)
        self.assertTrue(any(isinstance(s,c.Offset) for s in clipped[0]))


class P:
    def __init__(self,x,y,z=0):self.x=x;self.y=y;self.z=z
    def copy(self):return P(self.x,self.y,self.z)
    def translateBy(self,v):self.x+=v.x;self.y+=v.y;self.z+=v.z


class V(P):
    def copy(self):return V(self.x,self.y,self.z)
    def normalize(self):
        n=math.sqrt(self.x*self.x+self.y*self.y+self.z*self.z)
        self.x/=n;self.y/=n;self.z/=n
    def scaleBy(self,k):self.x*=k;self.y*=k;self.z*=k
    def crossProduct(self,b):return V(self.y*b.z-self.z*b.y,self.z*b.x-self.x*b.z,self.x*b.y-self.y*b.x)


class Eval:
    def __init__(self,f,u0=0,u1=1):self.f=f;self.u0=u0;self.u1=u1
    def getParameterExtents(self):return True,self.u0,self.u1
    def getPointAtParameter(self,u):
        p=self.f((u-self.u0)/(self.u1-self.u0))
        return True,P(p[0],p[1])


class FusionExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.ui=load_fusion_ui()

    def test_ellipse_and_reversed_elliptical_arc(self):
        ellipse=c.Ellipse((2,3),(4,0),(0,2),1.2,-math.pi*1.4)
        item=SimpleNamespace(objectType='EllipticalArc3D',center=P(2,3),
                             majorAxis=V(1,0),normal=V(0,0,1),majorRadius=4.,minorRadius=2.)
        frame=SimpleNamespace(to_xy=lambda p:(p.x,p.y))
        kind=SimpleNamespace(classType=lambda:'EllipticalArc3D')
        with patch.object(self.ui.adsk.core,'EllipticalArc3D',kind,create=True):
            got=self.ui._analytic_curve(item,Eval(ellipse.point),frame,.001)
        self.assertEqual(len(got),1)
        self.assertIsInstance(got[0],c.Ellipse)
        self.assertAlmostEqual(got[0].sweep,ellipse.sweep,places=6)
        for t in (0,.15,.5,.85,1):self.assertLess(c.length(c.sub(got[0].point(t),ellipse.point(t))),1e-8)

    def test_nurbs_and_polyline_extraction(self):
        spline=c.Nurbs(((0,0),(2,4),(4,0)),2,(0,0,0,1,1,1),(1,1,1),.2,.8)
        nurbs=SimpleNamespace(objectType='NurbsCurve3D',getData=lambda:(True,[P(*pt) for pt in spline.controls],2,
                                              [0,0,0,1,1,1],False,[],False))
        frame=SimpleNamespace(to_xy=lambda p:(p.x,p.y))
        kind=SimpleNamespace(classType=lambda:'NurbsCurve3D')
        poly_kind=SimpleNamespace(classType=lambda:'Polyline3D')
        with patch.object(self.ui.adsk.core,'NurbsCurve3D',kind,create=True),\
             patch.object(self.ui.adsk.core,'Polyline3D',poly_kind,create=True):
            got=self.ui._analytic_curve(nurbs,Eval(spline.point,.2,.8),frame,.001)
            poly=self.ui._analytic_curve(SimpleNamespace(objectType='Polyline3D',
                       points=[P(0,0),P(1,0),P(1,1)]),None,frame,.001)
        self.assertIsInstance(got[0],c.Nurbs)
        self.assertEqual(len(poly),2)
        self.assertTrue(all(isinstance(x,c.Line) for x in poly))
        for t in (0,.2,.5,.8,1):self.assertLess(c.length(c.sub(got[0].point(t),spline.point(t))),1e-9)


class NativeSketchOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.ui=load_fusion_ui()

    def test_lines_arcs_ellipses_nurbs_and_offsets_emit_native_entities(self):
        seen=[]
        def maker(name):
            return SimpleNamespace(
                addByCenterRadius=lambda *a:(seen.append((name,'circle',a)) or object()),
                addByThreePoints=lambda *a:(seen.append((name,'arc',a)) or object()),
                addByTwoPoints=lambda *a:(seen.append((name,'line',a)) or object()),
                add=lambda *a:(seen.append((name,'ellipse',a)) or object()),
                addByNurbsCurve=lambda *a:(seen.append((name,'spline',a)) or object()))
        sketch=SimpleNamespace(
            modelToSketchSpace=lambda p:p,
            sketchCurves=SimpleNamespace(
                sketchLines=maker('line'),sketchArcs=maker('arc'),
                sketchCircles=maker('circle'),sketchEllipses=maker('ellipse'),
                sketchFixedSplines=maker('spline')))
        frame=SimpleNamespace(to_world=lambda xy:P(*xy))
        def rational(ctrl,degree,knots,weights,periodic):
            seen.append(('nurbs','rational',(ctrl,degree,knots,weights,periodic)))
            return object()
        def nonrational(ctrl,degree,knots,periodic):
            seen.append(('nurbs','cubic',(ctrl,degree,knots,periodic)))
            return object()
        shim=SimpleNamespace(createRational=rational,createNonRational=nonrational)
        segments=[
            c.Line((0,0),(1,0)),
            c.Arc((1,1),(1,0),(2,1),math.pi/2),
            c.Ellipse((0,0),(3,0),(0,2)),
            c.Ellipse((0,0),(3,0),(0,2),.1,1.2),
            c.Nurbs(((0,0),(1,2),(2,0)),2,(0,0,0,1,1,1),
                    (1.,.8,1.),.2,.8),
            c.Offset(c.Ellipse((0,0),(3,0),(0,2),0,1.5),.2),
        ]
        with patch.object(self.ui.adsk.core,'NurbsCurve3D',shim,create=True):
            for segment in segments:
                self.ui._write_sketch_segment(sketch,frame,segment)
        self.assertEqual(sum(item[1]=='line' for item in seen),1)
        self.assertEqual(sum(item[1]=='arc' for item in seen),1)
        self.assertEqual(sum(item[1]=='ellipse' for item in seen),1)
        rational_calls=[item[2] for item in seen if item[1]=='rational']
        self.assertGreaterEqual(len(rational_calls),2)
        self.assertTrue(all(len(call[0])==len(call[3]) for call in rational_calls))
        self.assertTrue(any(item[1]=='cubic' for item in seen))
        self.assertEqual(sum(item[1]=='spline' for item in seen),
                         len(rational_calls)+sum(item[1]=='cubic' for item in seen))


if __name__=='__main__':unittest.main()
