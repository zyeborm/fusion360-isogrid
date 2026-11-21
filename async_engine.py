"""Fusion-independent, latest-request-wins geometry worker.

Only the caller's notify() callback is permitted to signal Fusion (via
Application.fireCustomEvent). All jobs/results contain plain Python objects.
Fusion API access, including UI updates, stays on Fusion's main thread.
"""
import threading
import traceback
import time
import preview_timing
import manufacturability

import fitting
import geometry


class Cancelled(Exception):
    """An obsolete worker request, cancelled cooperatively."""


class LatestWorker:
    def __init__(self, notify):
        self._notify = notify
        self._cv = threading.Condition()
        self._queued = None
        self._active_cancel = None
        self._closed = False
        self._sequence = 0
        self._results = []
        self._notification_pending = False
        self._prepared_key = None
        self._prepared = None
        self._last_manufacturing_report = manufacturability.Report()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name='IsogridGeometryWorker')
        self._thread.start()

    def submit(self, kind, payload):
        """Replace pending work, abort obsolete fit and give back a revision."""
        with self._cv:
            if self._closed:
                return None
            self._sequence += 1
            revision = self._sequence
            if self._active_cancel:
                self._active_cancel.set()
            self._queued = (revision, kind, payload)
            self._cv.notify()
            return revision

    def current(self, revision):
        with self._cv:
            return not self._closed and revision == self._sequence

    def cancel(self):
        with self._cv:
            self._sequence += 1
            self._queued = None
            if self._active_cancel:
                self._active_cancel.set()

    def close(self):
        with self._cv:
            self._closed = True
            self._queued = None
            if self._active_cancel:
                self._active_cancel.set()
            self._results.clear()
            self._cv.notify()
        # Daemon thread exits after its current short geometry operation.
        # Never join from the UI thread.

    def drain(self):
        """Call only on the receiving Fusion main thread."""
        with self._cv:
            batch = self._results
            self._results = []
            self._notification_pending = False
            return batch

    def _publish(self, message):
        with self._cv:
            if self._closed or message['revision'] != self._sequence:
                return
            self._results.append(message)
            if self._notification_pending:
                return
            self._notification_pending = True
        try:
            self._notify()
        except Exception:
            # An add-in may be stopping as the worker finishes; ensure a later
            # update can retry signalling if this one could not be delivered.
            with self._cv:
                self._notification_pending = False

    def _prepare(self, payload):
        started=time.perf_counter()
        if not payload['settings'].get('trim_boundary',True):
            return None
        key = payload['prep_key']
        if key != self._prepared_key:
            s = payload['settings']
            self._prepared = geometry.PreparedGeometry(
                payload['regions'],s['perimeter'],s['holeclear'],s['backend'])
            self._prepared_key = key
            preview_timing.log('worker.prepare_complete', elapsed=time.perf_counter()-started, backend=self._prepared.backend)
        else:
            preview_timing.log('worker.prepare_cache_hit', elapsed=time.perf_counter()-started)
        return self._prepared

    def _preview(self, payload, cancel):
        started=time.perf_counter()
        preview_timing.log('worker.preview_begin')
        prepared = self._prepare(payload)
        preview_timing.log('worker.pockets_begin', elapsed=time.perf_counter()-started)
        if cancel.is_set():
            raise Cancelled()
        s = payload['settings']
        shapes = geometry.make_pockets(
            payload['regions'], s['pitch'],s['rib'],s['perimeter'],
            s['holeclear'], s['dx'], s['dy'], payload['rotation'],
            s['corner'], s['minfraction']/100, max_cells=1600,
            vertex_hole_diameter=s['nodehole'],
            base_origin=payload['origin'], anchor=payload['anchor'],
            prepared=prepared,trim_boundary=s.get('trim_boundary',True))
        preview_timing.log('worker.pockets_complete', elapsed=time.perf_counter()-started, shapes=len(shapes))
        if cancel.is_set():
            raise Cancelled()
        shapes,report=manufacturability.screen(shapes,payload['regions'],s)
        self._last_manufacturing_report=report
        if not shapes:
            raise ValueError('No pockets fit this region. Reduce margins or cell pitch.')
        return shapes

    def _fit(self, revision, payload, cancel):
        # Fit candidates use a precomputed scoring mask. Exact geometry
        # preparation belongs to the final selected preview, not the search.
        prepared = None
        if cancel.is_set():
            raise Cancelled()
        last_bucket = [-1]
        def progress(done, total):
            if cancel.is_set():
                raise Cancelled()
            # At most about 11 UI notifications, independently of trials.
            bucket = (done * 10 // max(total, 1))
            if bucket != last_bucket[0]:
                last_bucket[0] = bucket
                self._publish(dict(kind='progress', revision=revision,
                                   done=done, total=total))
        s = payload['settings']
        return fitting.find_fits(
            payload['regions'], s, payload['origin'], payload['anchor'],
            payload['rotation'], pitch_min=payload['low'],
            pitch_max=payload['high'],
            allow_rotation=payload['allow_rotation'],
            evaluations=payload['evaluations'],
            max_cells=1600, progress=progress, prepared=prepared)

    def _run(self):
        while True:
            with self._cv:
                while self._queued is None and not self._closed:
                    self._cv.wait()
                if self._closed:
                    return
                revision, kind, payload = self._queued
                preview_timing.log('worker.job_start', revision=revision, kind=kind)
                self._queued = None
                cancel = threading.Event()
                self._active_cancel = cancel
            try:
                result = (self._fit(revision, payload, cancel) if kind == 'fit'
                          else self._preview(payload, cancel))
                if not cancel.is_set():
                    message=dict(kind=kind, revision=revision,value=result)
                    if kind=='preview':
                        message['manufacturing_report']=self._last_manufacturing_report
                    self._publish(message)
            except Cancelled:
                pass
            except Exception as exc:
                preview_timing.log('worker.job_error', error=repr(exc))
                for frame in traceback.extract_tb(exc.__traceback__):
                    preview_timing.log('worker.error_frame', file=frame.filename.rsplit('/',1)[-1].rsplit('\\',1)[-1], line=frame.lineno, func=frame.name)
                if not cancel.is_set():
                    self._publish(dict(kind='error', source=kind,
                                       revision=revision, message=str(exc),
                                       traceback=traceback.format_exc()))
            finally:
                with self._cv:
                    if self._active_cancel is cancel:
                        self._active_cancel = None
