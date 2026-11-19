"""On-demand GitHub version check for the Fusion command.

All network activity runs in a daemon thread.  Fusion UI interaction is limited
 to the notify callback (fireCustomEvent) and the main-thread reader.
"""
from __future__ import annotations

import json
import re
import threading
import time
from urllib.request import Request, urlopen

REPOSITORY_URL = 'https://github.com/zyeborm/fusion360-isogrid'
MANIFEST_URL = (
    'https://raw.githubusercontent.com/zyeborm/fusion360-isogrid/'
    'main/fusion360-isogrid.manifest'
)
CHECK_INTERVAL_SECONDS = 30 * 60


def version_tuple(version):
    """Return a stable three-part version or None for unexpected version text."""
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', str(version).strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def newer_version(local_version, remote_version):
    local, remote = version_tuple(local_version), version_tuple(remote_version)
    return local is not None and remote is not None and remote > local


def fetch_remote_version():
    """Get the version from the public main-branch manifest; no token needed."""
    request = Request(MANIFEST_URL, headers={
        'User-Agent': 'fusion360-isogrid-update-check',
        'Accept': 'application/json',
    })
    with urlopen(request, timeout=4) as response:
        # Manifest is a tiny JSON file. Bound size in case of unexpected server data.
        payload = response.read(16_385)
    if len(payload) > 16_384:
        raise ValueError('Remote manifest exceeds size limit')
    manifest = json.loads(payload.decode('utf-8'))
    if not isinstance(manifest, dict):
        raise ValueError('Invalid remote manifest')
    version = manifest.get('version')
    if version_tuple(version) is None:
        raise ValueError('Invalid version in remote manifest')
    return str(version)


class UpdateChecker:
    """Check on command open, cache the result and notify on completion."""

    def __init__(self, local_version, notify, fetch=fetch_remote_version,
                 clock=time.monotonic, interval=CHECK_INTERVAL_SECONDS):
        self.local_version = local_version
        self._notify = notify
        self._fetch = fetch
        self._clock = clock
        self._interval = interval
        self._lock = threading.Lock()
        self._last_check = None
        self._checking = False
        self._closed = False
        self._available = None

    def available(self):
        with self._lock:
            return self._available

    def check_on_open(self):
        """Returns cached update information immediately; may start one worker."""
        with self._lock:
            if self._closed:
                return None
            cached = self._available
            now = self._clock()
            if self._checking or (self._last_check is not None and
                                  now - self._last_check < self._interval):
                return cached
            self._checking = True
            self._last_check = now
        worker = threading.Thread(target=self._check, daemon=True,
                                  name='IsogridUpdateCheck')
        worker.start()
        return cached

    def _check(self):
        try:
            version = self._fetch()
            found = version if newer_version(self.local_version, version) else None
        except Exception:
            # Offline, captive portals, or an unavailable upstream should never
            # interrupt designing a part. Retry when the cache expires.
            found = None
        with self._lock:
            if self._closed:
                return
            self._available = found
            self._checking = False
        try:
            self._notify()
        except Exception:
            # The command may have closed during the HTTP request.
            pass

    def close(self):
        with self._lock:
            self._closed = True
            self._available = None
