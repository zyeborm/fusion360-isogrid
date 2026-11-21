"""Preserve the existing curve approximation while exporting one spline per offset.

A single multi-span NURBS replaces the prior independent cubic Bezier sketch
entities. It must trace the same curve, with the same parametric C1 continuity
and the same boundary endpoints, so the existing cut profiles remain closed.
"""
import math
import pathlib
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import curves2d as c
import geometry as g
from test_curved_dxf_regression import test_regions
from test_preview_lifecycle import load_fusion_ui


def cubic(control,t):
    u=1-t
    return c.add(c.add(c.mul(control[0],u*u*u),c.mul(control[1],3*u*u*t)),
                 c.add(c.mul(control[2],3*u*t*t),c.mul(control[3],t*t*t)))


class MultispanOffsetTests(unittest.TestCase):
    def test_multispan_equals_original_cubic_spans(self):
        base=c.Nurbs(((0.,0.),(.3,1.1),(1.8,-.2),(3.,1.)),3,
                     (0.,)*4+(1.,)*4,(1.,)*4,0.,1.)
        for offset in (.12,.3,-.3):
            segment=c.Offset(base,offset)
            spans=c._approximate_cubic_bezier_spans(segment,1e-4)
            points,knots=c.approximate_cubic_nurbs(segment,1e-4)
            self.assertGreater(len(spans),1)
            self.assertEqual(len(points),3*len(spans)+1)
            self.assertEqual(len(knots),len(points)+4)
            self.assertEqual(tuple(knots[:4]),(0.,)*4)
            self.assertEqual(tuple(knots[-4:]),(1.,)*4)
            self.assertTrue(all(x<=y for x,y in zip(knots,knots[1:])))
            homogeneous=tuple((x,y,1.) for x,y in points)
            for a,b,ctrl in spans:
                for j in range(9):
                    t=j/8
                    u=a+(b-a)*t
                    x,y,w=c._de_boor(homogeneous,3,knots,u)
                    self.assertLess(c.length(c.sub((x/w,y/w),cubic(ctrl,t))),1e-8)
            # Each adjacent cubic span has the same source derivative.
            for (a,b,left),(q,d,right) in zip(spans,spans[1:]):
                self.assertEqual(b,q)
                dl=c.mul(c.sub(left[3],left[2]),3/(b-a))
                dr=c.mul(c.sub(right[1],right[0]),3/(d-q))
                self.assertLess(c.length(c.sub(dl,dr)),1e-7)
            self.assertLess(c.length(c.sub(points[0],segment.start)),1e-10)
            self.assertLess(c.length(c.sub(points[-1],segment.end)),1e-10)

    def test_export_one_fusion_fixed_spline_for_many_bezier_spans(self):
        ui=load_fusion_ui()
        base=c.Nurbs(((0.,0.),(1.,2.),(2.,2.),(3.,0.)),3,
                     (0.,)*4+(1.,)*4,(1.,)*4,0.,1.)
        segment=c.Offset(base,.22)
        calls=[]
        class N3D:
            @staticmethod
            def createNonRational(points,degree,knots,periodic):
                calls.append((points,degree,knots,periodic))
                return 'nurbs'
        entities=[]
        sketch=SimpleNamespace(
            modelToSketchSpace=lambda p: (p[0]*2+7,p[1]*3-4),
            sketchCurves=SimpleNamespace(sketchFixedSplines=SimpleNamespace(
                addByNurbsCurve=lambda n:entities.append(n) or 'entity')))
        frame=SimpleNamespace(to_world=lambda p:(p[0]+10,p[1]+20))
        with patch.object(ui.adsk.core,'NurbsCurve3D',N3D,create=True):
            result=ui._write_sketch_segment(sketch,frame,segment)
        self.assertEqual(result,['entity'])
        self.assertEqual(len(entities),1)
        self.assertEqual(len(calls),1)
        pts,degree,knots,periodic=calls[0]
        self.assertEqual(degree,3)
        self.assertFalse(periodic)
        self.assertEqual(len(knots),len(pts)+degree+1)
        self.assertGreater(len(pts),4)
        p0=segment.start
        self.assertEqual(pts[0],((p0[0]+10)*2+7,(p0[1]+20)*3-4))

    def test_curved_fixture_offset_entities_reduce_without_changing_shapes(self):
        shapes=g.make_pockets(test_regions(),2.,.2,.3,.3,0.,0.,0.,.15,
                              min_area_fraction=.05,max_cells=1600,
                              vertex_hole_diameter=.3)
        self.assertEqual(len(shapes),131)
        offsets=[seg for sh in shapes for loop in (sh.curve_loops or [])
                 for seg in loop if isinstance(seg,c.Offset)]
        old_entities=sum(len(c.approximate_cubic_beziers(seg)) for seg in offsets)
        self.assertEqual(len(offsets),15)
        self.assertEqual(old_entities,130)
        for seg in offsets:
            controls,knots=c.approximate_cubic_nurbs(seg)
            self.assertEqual(len(knots),len(controls)+4)
            self.assertLess(c.length(c.sub(controls[0],seg.start)),1e-8)
            self.assertLess(c.length(c.sub(controls[-1],seg.end)),1e-8)
        print('Curved fixture: %d offset sketch splines instead of %d'%(len(offsets),old_entities))


if __name__=='__main__': unittest.main()
