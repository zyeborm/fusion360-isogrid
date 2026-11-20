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
        # Only explicit manual checks produce an up-to-date/error notice.
        # Automatic checks remain silent when there is no available update.
        self._manual_status = ('idle', None)

    def available(self):
        with self._lock:
            return self._available

    def manual_status(self):
        """(state, detail): idle, checking, current, available, or error."""
        with self._lock:
            return self._manual_status

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

    def check_now(self):
        """Force a network request, ignoring the 30-minute automatic cache.

        When an automatic request is already running, reuse that fresh request
        and make its result visible as a manual check. Never issue duplicates.
        """
        with self._lock:
            if self._closed:
                return False
            self._manual_status = ('checking', None)
            if self._checking:
                # The in-flight request is already retrieving the latest data.
                return True
            self._checking = True
            self._last_check = self._clock()
        threading.Thread(target=self._check, daemon=True,
                         name='IsogridManualUpdateCheck').start()
        return True

    def _check(self):
        try:
            version = self._fetch()
            found = version if newer_version(self.local_version, version) else None
            error = None
        except Exception as exc:
            # Automatic failures remain silent; manual requests receive the
            # failure reason, so "up to date" cannot mask a network error.
            found = None
            error = str(exc) or type(exc).__name__
        with self._lock:
            if self._closed:
                return
            self._available = found
            self._checking = False
            if self._manual_status[0] == 'checking':
                self._manual_status = (('error', error) if error else
                                       ('available', version) if found else
                                       ('current', version))
        try:
            self._notify()
        except Exception:
            # The command may have closed during the HTTP request.
            pass

    def close(self):
        with self._lock:
            self._closed = True
            self._available = None
            self._manual_status = ('idle', None)


# The update archive is downloaded only when the user clicks Install Update.
# Installation is staged and rolled back on failure. Imported Python modules
# remain active until Fusion is restarted; we never attempt an in-process reload.
ARCHIVE_URL = (
    'https://github.com/zyeborm/fusion360-isogrid/archive/refs/heads/main.zip'
)
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_EXTRACTED_BYTES = 16 * 1024 * 1024


def _download_archive():
    request = Request(ARCHIVE_URL, headers={'User-Agent': 'fusion360-isogrid-updater'})
    with urlopen(request, timeout=20) as response:
        data = response.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError('Update archive is unexpectedly large')
    return data


def install_archive(addin_directory, expected_version, archive_bytes):
    """Replace add-in source from a validated GitHub ZIP, preserving local files.

    Called on a background thread. Does not touch any Fusion APIs.
    Uses a same-volume staging directory and restores original files if a write
    fails. Third-party vendor files and user additions are never deleted.
    """
    import io
    import os
    import stat
    import tempfile
    import zipfile
    from pathlib import Path, PurePosixPath

    root = Path(addin_directory).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('The add-in directory does not exist')
    expected = version_tuple(expected_version)
    if expected is None:
        raise ValueError('Invalid requested update version')
    source = {}
    total_size = 0
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        members = archive.infolist()
        if len(members) > 250:
            raise ValueError('Update archive contains too many files')
        for member in members:
            if member.is_dir():
                continue
            if '\\' in member.filename or ':' in member.filename:
                raise ValueError('Unsafe platform-specific archive path')
            path = PurePosixPath(member.filename)
            if (len(path.parts) < 2 or path.parts[0] != 'fusion360-isogrid-main'
                    or any(part in ('', '.', '..') for part in path.parts)):
                raise ValueError('Unsafe update archive path')
            relative = path.relative_to('fusion360-isogrid-main')
            # Research/visualisation fixtures ship in GitHub's source ZIP,
            # but are not part of the installed add-in. Check paths and link
            # types before excluding them.
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError('Symbolic links are not accepted in an update')
            if relative.parts[0] == 'studies':
                continue
            if (relative.is_absolute() or len(relative.parts) > 2
                    or (len(relative.parts) == 2 and relative.parts[0] != 'tests')):
                raise ValueError('Unexpected update archive layout')
            if relative.parts[0].startswith('.') and str(relative) != '.gitignore':
                continue
            if any(part in ('vendor', '__pycache__', '.git') for part in relative.parts):
                continue
            if (relative.suffix not in ('.py', '.md', '.manifest')
                    and str(relative) not in ('.gitignore', 'LICENSE')):
                raise ValueError('Unexpected file type in update archive')
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError('Symbolic links are not accepted in an update')
            total_size += member.file_size
            if total_size > MAX_EXTRACTED_BYTES:
                raise ValueError('Unpacked update exceeds size limit')
            if str(relative) in source:
                raise ValueError('Duplicate path in update archive')
            source[str(relative)] = archive.read(member)

    required = ('fusion360-isogrid.py', 'fusion360-isogrid.manifest',
                'geometry.py', 'fitting.py', 'async_engine.py',
                'update_checker.py', 'curves2d.py', 'exact_clipper.py')
    if not all(name in source for name in required):
        raise ValueError('Update archive is missing required add-in files')
    try:
        manifest = json.loads(source['fusion360-isogrid.manifest'].decode('utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Invalid update manifest') from exc
    if version_tuple(manifest.get('version')) != expected:
        raise ValueError('Update version changed during download; try again')
    current_path = root / 'fusion360-isogrid.manifest'
    with current_path.open(encoding='utf-8') as file:
        current = json.load(file)
    if not newer_version(current.get('version'), manifest['version']):
        raise ValueError('Update is already installed or older than current version')
    if manifest.get('id') != current.get('id') or manifest.get('type') != 'addin':
        raise ValueError('Update is for a different add-in')

    # Install only regular files inside the add-in tree. Never overwrite user
    # symlinks to files outside this directory.
    for relative in source:
        destination = root / relative
        if destination.is_symlink() or destination.parent.is_symlink():
            raise ValueError('Update destination contains a symbolic link')
        if destination.exists() and not destination.is_file():
            raise ValueError('Update destination is not an ordinary file')

    with tempfile.TemporaryDirectory(prefix='.isogrid-update-', dir=root) as temp:
        staging = Path(temp)
        staged = staging / 'new'
        backup = staging / 'backup'
        installed = []
        for relative, contents in source.items():
            destination = staged / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents)
            prior = root / relative
            if prior.exists():
                prior_copy = backup / relative
                prior_copy.parent.mkdir(parents=True, exist_ok=True)
                prior_copy.write_bytes(prior.read_bytes())
        try:
            # Replace the manifest last: it describes the installed version.
            for relative in sorted(source, key=lambda p: p == 'fusion360-isogrid.manifest'):
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged / relative, destination)
                installed.append(relative)
        except BaseException:
            for relative in reversed(installed):
                destination = root / relative
                old = backup / relative
                if old.exists():
                    os.replace(old, destination)
                else:
                    destination.unlink(missing_ok=True)
            raise
    return manifest['version']


class UpdateInstaller:
    """One user-initiated installation at a time, with main-thread notification."""

    def __init__(self, directory, notify, fetch=_download_archive,
                 installer=install_archive):
        self.directory = directory
        self._notify = notify
        self._fetch = fetch
        self._installer = installer
        self._lock = threading.Lock()
        self._state = ('idle', None, None)
        self._closed = False

    def state(self):
        with self._lock:
            return self._state

    def start(self, version):
        if version_tuple(version) is None:
            return False
        with self._lock:
            if self._closed or self._state[0] in ('working', 'installed'):
                return False
            self._state = ('working', version, None)
        threading.Thread(target=self._run, args=(version,), daemon=True,
                         name='IsogridUpdateInstaller').start()
        return True

    def _run(self, version):
        try:
            archive = self._fetch()
            installed = self._installer(self.directory, version, archive)
            result = ('installed', installed, None)
        except Exception as exc:
            result = ('error', version, str(exc))
        with self._lock:
            self._state = result
            if self._closed:
                return
        try:
            self._notify()
        except Exception:
            pass

    def close(self):
        # A running file replacement is allowed to finish; no new UI callback
        # is dispatched once the add-in has closed.
        with self._lock:
            self._closed = True
