"""Threading tests that run without Autodesk Fusion or external libraries."""
import sys
import pathlib
import threading
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import async_engine
import geometry
import tool_center


class AsyncEngineTests(unittest.TestCase):
    def setUp(self):
        self.notified = threading.Event()
        self.worker = async_engine.LatestWorker(self.notified.set)

    def tearDown(self):
        self.worker.close()

    def receive(self, revision, kind, timeout=4.0):
        deadline=time.monotonic()+timeout
        results=[]
        while time.monotonic()<deadline:
            self.notified.wait(.05)
            self.notified.clear()
            results.extend(self.worker.drain())
            if any(m['revision']==revision and m['kind']==kind for m in results):
                return results
        self.fail(f'Expected {kind}, revision {revision}, received {results!r}')

    def payload(self, offset=0):
        region=geometry.Region([([(0,0),(10,0),(10,10),(0,10)],True)])
        s={'pitch':2,'rib':.2,'depth':.2,'perimeter':.2,
           'holeclear':.2,'dx':offset,'dy':0,'corner':.15,
           'minfraction':5,'nodehole':0,'backend':'python'}
        return dict(regions=[region],settings=s,origin=None,rotation=0,
                    anchor='vertex',prep_key=('square',.2,.2,'python'))

    def test_worker_preview_matches_direct_generator(self):
        payload=self.payload()
        revision=self.worker.submit('preview',payload)
        result=self.receive(revision,'preview')[-1]['value']
        direct,_=tool_center.make_toolcentre_pockets(
            payload['regions'],2,.2,.2,.2,0,0,0,.15,.05,
            vertex_hole_diameter=0,max_cells=1600)
        self.assertEqual(result,direct)

    def test_latest_result_wins_and_pending_is_coalesced(self):
        entered=threading.Event()
        release=threading.Event()
        def slow_preview(payload,cancel):
            if payload['settings']['dx']==1:
                entered.set()
                release.wait(2)
            return [payload['settings']['dx']]
        with patch.object(self.worker,'_preview',side_effect=slow_preview):
            first=self.worker.submit('preview',self.payload(1))
            self.assertTrue(entered.wait(2))
            second=self.worker.submit('preview',self.payload(2))
            third=self.worker.submit('preview',self.payload(3))
            release.set()
            messages=self.receive(third,'preview')
        self.assertTrue(all(m['revision']==third for m in messages))
        self.assertEqual(messages[-1]['value'],[3])
        self.assertFalse(self.worker.current(second))
        self.assertFalse(self.worker.current(first))

    def test_cancel_suppresses_obsolete_result(self):
        entered=threading.Event()
        release=threading.Event()
        def slow_preview(payload,cancel):
            entered.set()
            release.wait(2)
            if cancel.is_set():raise async_engine.Cancelled()
            return [1]
        with patch.object(self.worker,'_preview',side_effect=slow_preview):
            self.worker.submit('preview',self.payload())
            self.assertTrue(entered.wait(2))
            self.worker.cancel()
            release.set()
            time.sleep(.05)
            self.assertEqual(self.worker.drain(),[])

    def test_fitting_can_reuse_prepared_geometry(self):
        payload=self.payload()
        payload.update(low=1.7,high=2.4,evaluations=80,allow_rotation=False)
        revision=self.worker.submit('fit',payload)
        messages=self.receive(revision,'fit',timeout=15)
        results=[m for m in messages if m['kind']=='fit']
        self.assertTrue(results)
        self.assertTrue(results[-1]['value'])
        self.assertTrue(any(m['kind']=='progress' for m in messages))
        self.assertLessEqual(sum(m['kind']=='progress' for m in messages),12)

    def test_backend_failure_reports_error(self):
        payload=self.payload()
        payload['settings']['backend']='geos'
        # Force a known invalid input independent of optional GEOS presence.
        payload['settings']['pitch']=0
        revision=self.worker.submit('preview',payload)
        messages=self.receive(revision,'error')
        self.assertEqual(messages[-1]['source'],'preview')

    def test_prepared_boundary_is_reused_for_subsequent_edits(self):
        first=self.payload(0)
        second=self.payload(.3)
        a=self.worker._prepare(first)
        b=self.worker._prepare(second)
        self.assertIs(a,b)
        second['prep_key']=('different-face',.2,.2,'python')
        c=self.worker._prepare(second)
        self.assertIsNot(b,c)


if __name__=='__main__':unittest.main()
