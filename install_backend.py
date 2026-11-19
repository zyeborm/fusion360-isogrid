"""Install the optional compiled geometry backend into this add-in's vendor/.

Run using a regular Python 3 with pip from a terminal *outside* Fusion:

    python install_backend.py

This fetches CPython 3.14 wheels for Fusion's embedded interpreter rather
than for the Python interpreter used to run this script. It changes no system
packages or Fusion installation files; only fusion360-isogrid/vendor/ is written.
An Internet connection and a functioning pip installation are required.
"""
from __future__ import annotations
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
VENDOR=ROOT/'vendor'
FUSION_PYTHON='314'  # Fusion's January 2026 Python 3.14 upgrade.


def target_platform():
    system=platform.system()
    arch=platform.machine().lower()
    if system=='Windows' and arch in ('amd64','x86_64'):
        return 'win_amd64'
    if system=='Darwin':
        # Ask pip for wheels compatible with this host OS version, rather
        # than arbitrarily limiting it to macOS 11. Newer NumPy builds may
        # specify a higher minimum deployment target.
        major=int(platform.mac_ver()[0].split('.')[0])
        if arch=='arm64':return f'macosx_{max(11,major)}_0_arm64'
        if arch=='x86_64':return f'macosx_{max(11,major)}_0_x86_64'
    raise SystemExit('Unsupported system/architecture: '+system+' '+arch+
                     '. Install matching CPython 3.14 Shapely and NumPy wheels manually.')


def main():
    plat=target_platform()
    print('Target:',plat,'CPython 3.14')
    with tempfile.TemporaryDirectory(prefix='isogrid_wheels_') as temp:
        command=[sys.executable,'-m','pip','download',
                 '--only-binary=:all:','--platform',plat,
                 '--python-version',FUSION_PYTHON,'--implementation','cp',
                 '--abi','cp314','--dest',temp,
                 'shapely==2.2.0','numpy>=2.3,<3']
        print('Downloading compatible compiled packages...')
        subprocess.check_call(command)
        wheels=sorted(Path(temp).glob('*.whl'))
        if len(wheels)<2:
            raise RuntimeError('Expected wheels for both Shapely and NumPy.')
        # Build in a temporary directory, then replace vendor atomically enough
        # to avoid leaving a partially installed backend after a failed download.
        temp_vendor=ROOT/'vendor_staging'
        if temp_vendor.exists():shutil.rmtree(temp_vendor)
        temp_vendor.mkdir()
        try:
            for wheel in wheels:
                print('Unpacking:',wheel.name)
                with zipfile.ZipFile(wheel) as archive:
                    archive.extractall(temp_vendor)
            for data in temp_vendor.glob('*.data'):
                for location in ('purelib','platlib'):
                    directory=data/location
                    if directory.is_dir():
                        for child in directory.iterdir():
                            dest=temp_vendor/child.name
                            if dest.exists():
                                if dest.is_dir():shutil.rmtree(dest)
                                else:dest.unlink()
                            shutil.move(str(child),dest)
                shutil.rmtree(data)
            if not (temp_vendor/'shapely').exists() or not (temp_vendor/'numpy').exists():
                raise RuntimeError('The wheels did not contain the expected packages.')
            if VENDOR.exists():shutil.rmtree(VENDOR)
            temp_vendor.rename(VENDOR)
        finally:
            if temp_vendor.exists():shutil.rmtree(temp_vendor)
    print('Compiled geometry backend installed into:',VENDOR)
    print('Restart Fusion. The Isogrid preview status should show Geometry: GEOS (accelerated).')

if __name__=='__main__':main()
