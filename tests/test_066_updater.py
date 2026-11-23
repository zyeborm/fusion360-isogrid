"""Real ZIP staging and updater callback tests, independent of Autodesk Fusion."""
import io
import json
import os
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from update_checker import (install_archive, UpdateInstaller, fetch_remote_version,
                            release_asset_name, release_archive_url, _download_archive)

ID = '9b70f5e1-4653-4c46-a2d8-fd0ee68e23a1'
FILES = {
    'fusion360-isogrid.py': b'# entrypoint\n',
    'fusion360-isogrid.manifest': json.dumps({'id': ID, 'type': 'addin', 'version': '0.6.6'}).encode(),
    'geometry.py': b'# geometry new\n',
    'curves2d.py': b'# exact curve primitives\n',
    'exact_clipper.py': b'# exact curve booleans\n',
    'fitting.py': b'# fitter new\n',
    'async_engine.py': b'# worker new\n',
    'update_checker.py': b'# updater new\n',
    'tests/test_geometry.py': b'# test new\n',
}


def build_zip(files=FILES):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr('fusion360-isogrid/' + name, content)
    return stream.getvalue()


class UpdateInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addin = Path(self.temp.name) / 'fusion360-isogrid'
        self.addin.mkdir()
        self.previous = json.dumps({'id': ID, 'type': 'addin', 'version': '0.6.5'}).encode()
        (self.addin/'fusion360-isogrid.manifest').write_bytes(self.previous)
        (self.addin/'geometry.py').write_bytes(b'# geometry old\n')
        (self.addin/'vendor').mkdir()
        (self.addin/'vendor'/'my-dependency.dll').write_bytes(b'local')

    def tearDown(self):
        self.temp.cleanup()

    def test_replaces_source_and_preserves_local_files(self):
        installed = install_archive(self.addin, '0.6.6', build_zip())
        self.assertEqual(installed, '0.6.6')
        self.assertEqual((self.addin/'geometry.py').read_bytes(), b'# geometry new\n')
        self.assertEqual((self.addin/'vendor'/'my-dependency.dll').read_bytes(), b'local')
        self.assertEqual(json.loads((self.addin/'fusion360-isogrid.manifest').read_text())['version'],'0.6.6')

    def test_source_archive_with_studies_is_installable(self):
        files = dict(FILES)
        files['studies/visual_fit_study.py'] = b'# research only\n'
        files['studies/fit_study_metrics.csv'] = b'pitch,score\n'
        files['studies/notes/experiment.py'] = b'# nested research\n'
        installed = install_archive(self.addin, '0.6.6', build_zip(files))
        self.assertEqual(installed, '0.6.6')
        self.assertFalse((self.addin/'studies').exists())
        self.assertEqual((self.addin/'geometry.py').read_bytes(), b'# geometry new\n')

    def test_github_workflow_directory_is_not_installed(self):
        files=dict(FILES)
        files['.github/workflows/geometry-tests.yml']=b'name: tests\\n'
        installed=install_archive(self.addin, '0.6.6', build_zip(files))
        self.assertEqual(installed,'0.6.6')
        self.assertFalse((self.addin/'.github').exists())

    def test_source_archive_with_screenshots_is_installable(self):
        files = dict(FILES)
        files['images/isogrid-result.png'] = b'png-bytes'
        installed = install_archive(self.addin, '0.6.6', build_zip(files))
        self.assertEqual(installed, '0.6.6')
        self.assertFalse((self.addin/'images').exists())

    def test_latest_release_requires_uploaded_matching_asset(self):
        from unittest.mock import MagicMock
        tag = 'v0.6.6'
        asset = {
            'name': release_asset_name('0.6.6'),
            'state': 'uploaded',
            'browser_download_url': release_archive_url('0.6.6'),
        }
        release = dict(tag_name=tag, draft=False, prerelease=False, assets=[asset])
        def fetch(data):
            response=MagicMock()
            response.__enter__.return_value.read.return_value=json.dumps(data).encode()
            return response
        with patch('update_checker.urlopen', return_value=fetch(release)) as call:
            self.assertEqual(fetch_remote_version(), '0.6.6')
            self.assertIn('releases/latest',call.call_args.args[0].full_url)
        for bad in [
            dict(release, prerelease=True),
            dict(release, draft=True),
            dict(release, assets=[]),
            dict(release, assets=[dict(asset, state='starter')]),
            dict(release, assets=[dict(asset, browser_download_url='https://example.net/bad.zip')]),
        ]:
            with patch('update_checker.urlopen',return_value=fetch(bad)):
                with self.assertRaises(ValueError):
                    fetch_remote_version()

    def test_installer_downloads_exact_versioned_release_asset(self):
        from unittest.mock import MagicMock
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'zip contents'
        with patch('update_checker.urlopen',return_value=response) as call:
            self.assertEqual(_download_archive('0.6.6'), b'zip contents')
            self.assertEqual(call.call_args.args[0].full_url,
                             release_archive_url('0.6.6'))
        with self.assertRaises(ValueError):
            release_archive_url('main')

    def test_manifest_mismatch_rejected_without_changes(self):
        with self.assertRaisesRegex(ValueError, 'version changed'):
            install_archive(self.addin, '0.6.7', build_zip())
        self.assertEqual((self.addin/'fusion360-isogrid.manifest').read_bytes(),self.previous)

    def test_zip_slip_rejected(self):
        files = dict(FILES)
        files['../outside.py'] = b'unsafe'
        with self.assertRaisesRegex(ValueError,'Unsafe'):
            install_archive(self.addin,'0.6.6',build_zip(files))
        self.assertFalse((Path(self.temp.name)/'outside.py').exists())

    def test_backslash_path_rejected(self):
        files = dict(FILES)
        files[r'tests\..\escape.py'] = b'unsafe'
        with self.assertRaisesRegex(ValueError,'Unsafe'):
            install_archive(self.addin,'0.6.6',build_zip(files))

    def test_incomplete_archive_rejected(self):
        files = dict(FILES)
        del files['geometry.py']
        with self.assertRaisesRegex(ValueError,'missing required'):
            install_archive(self.addin,'0.6.6',build_zip(files))

    def test_wrong_addin_rejected(self):
        files = dict(FILES)
        files['fusion360-isogrid.manifest'] = json.dumps({'id':'different', 'version':'0.6.6','type':'addin'}).encode()
        with self.assertRaisesRegex(ValueError,'different add-in'):
            install_archive(self.addin,'0.6.6',build_zip(files))

    def test_restore_after_mid_install_failure(self):
        import update_checker
        actual = os.replace
        calls = []
        def fail_midway(a,b):
            # Fail when committing a staged source file (not when restoring backup).
            if '/new/' in str(a).replace('\\','/') and len(calls) == 2:
                raise OSError('disk full')
            if '/new/' in str(a).replace('\\','/'):
                calls.append(str(b))
            return actual(a,b)
        with patch.object(os,'replace',side_effect=fail_midway):
            with self.assertRaisesRegex(OSError,'disk full'):
                install_archive(self.addin,'0.6.6',build_zip())
        self.assertEqual((self.addin/'fusion360-isogrid.manifest').read_bytes(),self.previous)
        self.assertEqual((self.addin/'geometry.py').read_bytes(),b'# geometry old\n')
        self.assertFalse((self.addin/'async_engine.py').exists())

    def test_one_click_worker_delivers_success_and_refuses_duplicate(self):
        ready = threading.Event()
        unblock = threading.Event()
        def fetch(version):
            self.assertEqual(version,'0.6.6')
            unblock.wait(2)
            return build_zip()
        installer = UpdateInstaller(self.addin, ready.set, fetch=fetch)
        try:
            self.assertTrue(installer.start('0.6.6'))
            self.assertFalse(installer.start('0.6.6'))
            self.assertEqual(installer.state()[0], 'working')
            unblock.set()
            self.assertTrue(ready.wait(2))
            self.assertEqual(installer.state(),('installed','0.6.6',None))
        finally:
            installer.close()


if __name__ == '__main__':
    unittest.main()
