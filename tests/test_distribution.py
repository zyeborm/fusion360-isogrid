"""Distribution invariants for tagged GitHub Releases and Autodesk Marketplace."""
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('isogrid_release_builder',
                                             ROOT/'tools'/'build_release.py')
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.version=json.loads((ROOT/'fusion360-isogrid.manifest').read_text())['version']

    def test_packages_share_sources_but_not_updater(self):
        with tempfile.TemporaryDirectory() as out:
            github,market,_,_=builder.build(self.version,out)
            with zipfile.ZipFile(github) as gh, zipfile.ZipFile(market) as mk:
                gp=builder.NAME+'/'
                mp=builder.BUNDLE+'/Contents/'
                shared=builder.MODULES+builder.DOCUMENTS+(builder.NAME+'.manifest',)
                for name in shared:
                    if name==builder.NAME+'.py':
                        continue
                    self.assertEqual(gh.read(gp+name),mk.read(mp+name),name)
                self.assertIn(gp+'update_checker.py',gh.namelist())
                self.assertNotIn(mp+'update_checker.py',mk.namelist())
                self.assertIn(b'ENABLE_UPDATES = True',gh.read(gp+builder.NAME+'.py'))
                self.assertIn(b'ENABLE_UPDATES = False',mk.read(mp+builder.NAME+'.py'))
                self.assertIn(b'Privacy policy (VapourForge)',mk.read(mp+builder.NAME+'.py'))
                self.assertNotIn('tests/',str(mk.namelist()))

    def test_source_versions_must_agree(self):
        with self.assertRaisesRegex(ValueError,'[Vv]ersion'):
            builder.package_source('99.0.0',False)

    def test_marketplace_icon_is_png(self):
        data=builder.make_icon(120)
        self.assertEqual(data[:8],b'\x89PNG\r\n\x1a\n')
        self.assertEqual(int.from_bytes(data[16:20],'big'),120)

    def test_release_zip_is_reproducible(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for pa,pb in zip(builder.build(self.version,a)[:2],
                             builder.build(self.version,b)[:2]):
                self.assertEqual(pa.read_bytes(),pb.read_bytes())

if __name__=='__main__':
    unittest.main()
