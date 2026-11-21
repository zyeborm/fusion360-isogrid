"""Repeated Fusion preview events should reuse the same source geometry."""
import pathlib
import sys
import types
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from test_preview_lifecycle import load_fusion_ui


class CoordCacheTests(unittest.TestCase):
    def test_same_shapes_do_not_repeat_12000_world_point_transforms(self):
        ui=load_fusion_ui()
        calls=[]
        class Graphics:
            def addLines(self,coords,indices,closed):return types.SimpleNamespace(weight=0,color=None)
            def deleteMe(self):pass
        groups=types.SimpleNamespace(add=Graphics)
        face=types.SimpleNamespace(body=types.SimpleNamespace(parentComponent=types.SimpleNamespace(customGraphicsGroups=groups)))
        frame=types.SimpleNamespace(to_world=lambda p,lift=0: self.pt(p,lift,calls))
        shapes=[types.SimpleNamespace(loops=[[(0.,0.),(1.,0.),(0.,1.)]])]
        sess=types.SimpleNamespace(graphics=None,manufacturing_report=None,
              clear_preview=lambda:None)
        # A user changing zoom or fit UI can trigger many redraws without
        # changing any of the accepted cut contours.
        core=ui.adsk.core
        fusion=ui.adsk.fusion
        app=types.SimpleNamespace(activeViewport=types.SimpleNamespace(refresh=lambda:None))
        with patch.object(ui,'APP',app), \
             patch.object(core,'Color',types.SimpleNamespace(create=lambda *args: args),create=True), \
             patch.object(fusion,'CustomGraphicsCoordinates',types.SimpleNamespace(create=lambda c:c),create=True), \
             patch.object(fusion,'CustomGraphicsSolidColorEffect',types.SimpleNamespace(create=lambda c:c),create=True):
            data=(face,None,frame,{},[],shapes)
            ui._draw_preview(sess,data)
            first=len(calls)
            self.assertEqual(first,6)
            ui._draw_preview(sess,data)
            self.assertEqual(len(calls),first)
            next_shapes=list(shapes)
            ui._draw_preview(sess,(face,None,frame,{},[],next_shapes))
            self.assertEqual(len(calls),2*first)

    @staticmethod
    def pt(p,lift,calls):
        calls.append(p)
        return types.SimpleNamespace(x=p[0],y=p[1],z=lift)

if __name__=='__main__':unittest.main()
