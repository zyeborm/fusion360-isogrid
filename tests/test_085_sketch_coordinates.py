"""Fusion native NURBS exports must use sketch-local control points.

Most prior API shims use the XY origin as the sketch plane. That masked a
coordinate-space mismatch that can displace boundary-offset spline pieces.
"""
import pathlib
import sys
import types
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import curves2d as c
from test_preview_lifecycle import load_fusion_ui


class NativeNurbsSpaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.ui=load_fusion_ui()

    def test_control_points_are_in_sketch_space_for_nurbs_offset_and_ellipse(self):
        ui=self.ui
        # Nontrivial frame transformation: part has been translated/rotated
        # relative to the local sketch axes. A model-space spline appears
        # wildly displaced, even while line and arc creation succeeds.
        frame=types.SimpleNamespace(to_world=lambda pt:(pt[0]+10.,pt[1]-5.))
        sketch_transform=lambda pt:(2.*pt[1]+3., -pt[0]-7.)
        saved=[]
        class Nurbs3D:
            @staticmethod
            def createNonRational(points,degree,knots,periodic):
                saved.append(('nonrational',points));return ('nurbs',points)
            @staticmethod
            def createRational(points,degree,knots,weights,periodic):
                saved.append(('rational',points));return ('nurbs',points)
        class Sketch:
            def __init__(self):
                self.sketchCurves=types.SimpleNamespace(
                    sketchFixedSplines=types.SimpleNamespace(
                        addByNurbsCurve=lambda curve:types.SimpleNamespace()))
            def modelToSketchSpace(self,point):return sketch_transform(point)
        sketch=Sketch()
        with patch.object(ui.adsk.core,'NurbsCurve3D',Nurbs3D,create=True):
            # A four-control cubic, exported as exact native NURBS.
            controls=((0.,0.),(1.,1.),(2.,1.),(3.,0.))
            spline=c.Nurbs(controls,3,(0.,)*4+(1.,)*4,(1.,)*4,0.,1.)
            ui._write_sketch_segment(sketch,frame,spline)
            assert saved[-1][0]=='rational'
            self.assertEqual(saved[-1][1][0],sketch_transform(frame.to_world(controls[0])))
            self.assertEqual(saved[-1][1][-1],sketch_transform(frame.to_world(controls[-1])))
            # A general NURBS offset exports multiple tangent-matched cubic
            # splines, all using the same modelToSketchSpace transform.
            offset=c.Offset(spline,.2)
            ui._write_sketch_segment(sketch,frame,offset)
            assert saved[-1][0]=='nonrational'
            expected=sketch_transform(frame.to_world(offset.end))
            self.assertAlmostEqual(saved[-1][1][-1][0],expected[0],places=9)
            self.assertAlmostEqual(saved[-1][1][-1][1],expected[1],places=9)
            # A partial elliptical arc is emitted as rational quadratics.
            ellipse=c.Ellipse((0.,0.),(2.,0.),(0.,1.),0.,1.)
            ui._write_sketch_segment(sketch,frame,ellipse)
            assert saved[-1][0]=='rational'
            expected=sketch_transform(frame.to_world(ellipse.end))
            self.assertAlmostEqual(saved[-1][1][-1][0],expected[0],places=9)
            self.assertAlmostEqual(saved[-1][1][-1][1],expected[1],places=9)


if __name__=='__main__':unittest.main()
