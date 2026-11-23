"""Native-Fusion handoff integration for the direct tool-centre geometry.

The Autodesk sketch is mocked, but the actual geometry worker, tool-centre
construction and Fusion curve exporter are used.
"""
import pathlib
import sys
import types
import threading
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import geometry as g
import curves2d as c
import tool_center
import async_engine
import offset_cleanup
from test_preview_lifecycle import load_fusion_ui
from test_090_toolcentre_redesign import source, rectangle
from test_curved_dxf_regression import test_regions


class NativeFusionToolCentreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui=load_fusion_ui()

    def test_curved_worker_and_fusion_output_accept_exact_same_shapes(self):
        worker=async_engine.LatestWorker(lambda:None)
        regions=test_regions()
        settings=dict(pitch=2.,rib=.2,perimeter=.3,holeclear=.3,dx=0.,dy=0.,
                      corner=.15,minfraction=5.,nodehole=.3,backend='python',
                      trim_boundary=True)
        payload=dict(regions=regions,settings=settings,origin=None,rotation=0.,
                     anchor='vertex',prep_key=('curve',.3,.3,'python'))
        try:
            prep=worker._prepare(payload)
            self.assertIsInstance(prep,tool_center.ToolCentre)
            outlines=worker._preview(payload,threading.Event())
            self.assertEqual(len(outlines),132)
            self.assertEqual(sum(s.circle is not None for s in outlines),36)
            self.assertEqual(worker._last_manufacturing_report.rejected_corner_pockets,0)
            self.assertTrue(all(c.close_loop(loop,3e-5) for shape in outlines
                                for loop in (shape.curve_loops or [])))
            self.assertIs(worker._prepare(payload),prep)
            payload['settings']['dx']=.2
            self.assertIs(worker._prepare(payload),prep)
            payload['settings']['corner']=.2
            self.assertIsNot(worker._prepare(payload),prep)
        finally:worker.close()

    def test_trim_disabled_and_zero_radius_keep_original_engine(self):
        worker=async_engine.LatestWorker(lambda:None)
        payload=dict(regions=[g.Region([([(0.,0.),(10.,0.),(10.,8.),(0.,8.)],True)])],
                     settings=dict(pitch=2.,rib=.2,perimeter=.2,holeclear=.2,
                                   dx=0.,dy=0.,corner=0.,minfraction=5.,
                                   nodehole=0.,backend='python',trim_boundary=True),
                     rotation=0.,anchor='vertex',origin=None,
                     prep_key=('test',.2,.2,'python'))
        try:
            self.assertIsInstance(worker._prepare(payload),g.PreparedGeometry)
            payload['settings']['corner']=.15
            payload['settings']['trim_boundary']=False
            self.assertIsNone(worker._prepare(payload))
        finally:worker.close()

    def test_export_trimmed_parametric_ellipse_offset_as_single_native_spline(self):
        base=c.Ellipse((0.,0.),(4.,0.),(0.,1.))
        loops=offset_cleanup.clean_closed_offset(base,.6,True)
        self.assertEqual(len(loops),1)
        segment=loops[0][0]
        self.assertIsInstance(segment,offset_cleanup.OffsetInterval)
        calls=[]
        class N3D:
            @staticmethod
            def createNonRational(points,degree,knots,periodic):
                calls.append((points,degree,knots,periodic))
                return 'spline'
        saved=[]
        sketch=types.SimpleNamespace(
            modelToSketchSpace=lambda p:(2*p[0]+1,3*p[1]-2),
            sketchCurves=types.SimpleNamespace(sketchFixedSplines=types.SimpleNamespace(
                addByNurbsCurve=lambda x:saved.append(x) or 'entity')))
        frame=types.SimpleNamespace(to_world=lambda p:(p[0]+10,p[1]+20))
        with patch.object(self.ui.adsk.core,'NurbsCurve3D',N3D,create=True):
            self.assertEqual(self.ui._write_sketch_segment(sketch,frame,segment),
                             ['entity'])
        self.assertEqual(saved,['spline'])
        self.assertEqual(len(calls),1)
        pts,degree,knots,periodic=calls[0]
        self.assertEqual(degree,3)
        self.assertEqual(len(knots),len(pts)+4)
        self.assertGreater(len(pts),4)
        self.assertFalse(periodic)
        for output,actual in ((pts[0],segment.start),(pts[-1],segment.end)):
            self.assertLess(abs(output[0]-(actual[0]+10)*2-1),1e-10)
            self.assertLess(abs(output[1]-(actual[1]+20)*3+2),1e-10)

    def test_tool_centre_boundary_offsets_of_arcs_remain_native_circular_arcs(self):
        circle=c.circle((0.,0.),2.)
        segment=c.Offset(circle,.3)
        saved=[]
        curves=types.SimpleNamespace(sketchCircles=types.SimpleNamespace(
            addByCenterRadius=lambda ctr,r:saved.append(('circle',ctr,r)) or 'circle'))
        sketch=types.SimpleNamespace(modelToSketchSpace=lambda p:p,sketchCurves=curves)
        frame=types.SimpleNamespace(to_world=lambda p:p)
        self.assertEqual(self.ui._write_sketch_segment(sketch,frame,segment),['circle'])
        self.assertEqual(saved[0][0],'circle')
        self.assertAlmostEqual(saved[0][2],1.7)


if __name__=='__main__':unittest.main()
