"""Minimal thread-safe diagnostic log for preview timing.

Lines are flushed immediately to survive a UI or worker stall. The logger
never calls Fusion APIs and is safe to use from either thread.
"""
from datetime import datetime, timezone
from pathlib import Path
import os
import tempfile
import threading
import time

PATH = Path(tempfile.gettempdir()) / 'fusion360-isogrid-preview.log'
_LOCK = threading.Lock()


def log(event, **fields):
    try:
        stamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
        pairs = ' '.join(f'{k}={str(v).replace(chr(10), " ")[:160]}'
                         for k, v in fields.items())
        line = f'{stamp} mono={time.perf_counter():.6f} thread={threading.current_thread().name} {event} {pairs}\n'
        with _LOCK:
            with PATH.open('a', encoding='utf-8') as f:
                f.write(line)
                f.flush()
    except OSError:
        pass
