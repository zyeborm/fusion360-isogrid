"""End-to-end worker -> Fusion preview drawing against a lightweight API shim.

The real worker, Session.consume, executePreview handler and _draw_preview are
used; only the proprietary Fusion interfaces are replaced with test doubles.
"""
import pathlib
import sys
import threading
import types
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import async_engine
from test_curved_dxf_regression import test_regions
from test_preview_lifecycle import load_fusion_ui, Inputs


class FullPreviewHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.ui=load_fusion_ui()

    def test_fusion_defaults_worker_result_draws_actual_outlines(self):
        settings={'pitch':2.,'rib':.2,'depth':.2,'depth_expression':'2 mm',
                  'perimeter':.3,'holeclear':.3,'dx':0.,'dy':0.,'corner':.15,
                  'minfraction':5.,'nodehole':.3,'backend':'auto',
                  'trim_boundary':True}
        regions=test_regions()
        payload=dict(regions=regions,settings=settings,origin=None,
                     rotation=0.,anchor='vertex',prep_key=('curved-dxf',.3,.3,'auto'))
        signalled=threading.Event()
        worker=async_engine.LatestWorker(signalled.set)
        drawn=[]
        class Group:
            def addLines(self,coords,indices,is_closed):
                result=types.SimpleNamespace(weight=None,color=None)
                drawn.append((coords,result))
                return result
            def deleteMe(self):pass
        face=types.SimpleNamespace(body=types.SimpleNamespace(
             parentComponent=types.SimpleNamespace(customGraphicsGroups=
             types.SimpleNamespace(add=lambda:Group()))))
        frame=types.SimpleNamespace(to_world=lambda xy,lift=0.:
            types.SimpleNamespace(x=xy[0],y=xy[1],z=lift))
        session=self.ui.Session.__new__(self.ui.Session)
        session.worker=worker
        session.alive=True
        session.updating=False
        session.fit_running=False
        session.busy=True
        session.pending_kind='preview'
        session.failed_signature=None
        session.last_signature='test-signature'
        session.cache=None
        session.cache_signature=None
        session.graphics=None
        session.inputs=Inputs()
        session.snapshot=(session.last_signature,
                          (face,None,frame,dict(settings),regions),payload)
        session._activity=lambda *args:None
        session._preview_text=lambda inputs,data:None
        session.request_preview=lambda inputs:None
        args=types.SimpleNamespace(command=types.SimpleNamespace(
            commandInputs=session.inputs))
        events=[]
        def do_execute_preview():
            events.append('executePreview')
            session.preview(args)
            return True
        session.command=types.SimpleNamespace(doExecutePreview=do_execute_preview)
        app=types.SimpleNamespace(
            activeViewport=types.SimpleNamespace(refresh=lambda:
                                                  events.append('viewport.refresh')),
            log=lambda message:self.fail('Unexpected Fusion API error: '+message))
        core=self.ui.adsk.core
        fusion=self.ui.adsk.fusion
        try:
            with patch.object(self.ui,'APP',app), \
                 patch.object(self.ui,'_inputs_to_settings',return_value=settings), \
                 patch.object(core,'Color',types.SimpleNamespace(create=lambda *a:a),create=True), \
                 patch.object(fusion,'CustomGraphicsCoordinates',
                              types.SimpleNamespace(create=lambda p:p),create=True), \
                 patch.object(fusion,'CustomGraphicsSolidColorEffect',
                              types.SimpleNamespace(create=lambda color:color),create=True):
                session.revision=worker.submit('preview',payload)
                self.assertTrue(signalled.wait(20),'No worker completion event')
                session.consume()
                self.assertIsNone(session.pending_kind)
                self.assertEqual(len(session.cache[-1]),131)
                self.assertEqual(sum(s.circle is not None for s in session.cache[-1]),36)
                self.assertEqual(session.manufacturing_report.rejected_corner_pockets,6)
                self.assertEqual(events,['executePreview','viewport.refresh'])
                # Blue shape contours plus optional red web diagnostics.
                self.assertIn(len(drawn),(1,2))
                self.assertGreater(len(drawn[0][0]),1000)
                self.assertEqual(len(drawn[0][0])%6,0)
                self.assertEqual(drawn[0][1].weight,2)
                self.assertEqual(session.cache_signature,session.last_signature)
        finally:
            worker.close()


if __name__=='__main__':unittest.main()
