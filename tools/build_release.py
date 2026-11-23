"""Build and verify the GitHub and Autodesk Fusion Marketplace distributions.

Run: python tools/build_release.py --version 0.8.8
Only Python's standard library is required. No Autodesk installation needed.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import re
import struct
import zlib
import zipfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
NAME = "fusion360-isogrid"
PUBLISHER = "VapourForge"
BUNDLE = NAME + ".bundle"
MODULES = (
    "fusion360-isogrid.py",
    "async_engine.py", "curves2d.py", "exact_clipper.py",
    "fast_fit.py", "fit_quality.py", "fitting.py", "geometry.py",
    "manufacturability.py", "offset_cleanup.py", "presets.py",
    "preview_timing.py", "saved_mass.py", "shared_boundary.py",
    "tool_center.py",
)
DOCUMENTS = ("README.md", "ADVANCED.md", "CHANGELOG.md", "PRIVACY.md", "LICENSE")
GITHUB_ONLY = ("update_checker.py",)
ZIP_DATE = (2020, 1, 1, 0, 0, 0)


def validate_version(version):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(version))
    if not match:
        raise ValueError("Expected version x.y.z (for example 0.8.8)")
    return ".".join(match.groups())


def package_source(version, marketplace):
    """Produce exact allowlisted files; never zip unrelated repo/test files."""
    version = validate_version(version)
    manifest = json.loads((ROOT / (NAME + ".manifest")).read_text(encoding="utf-8"))
    if manifest["version"] != version or manifest["author"] != PUBLISHER:
        raise ValueError("Version or publisher differs from the committed manifest")
    source = (ROOT / (NAME + ".py")).read_text(encoding="utf-8")
    expected_version = "RUNNING_VERSION = " + repr(version)
    if source.count(expected_version) != 1:
        raise ValueError("Running code version differs from the release version")
    switch = "ENABLE_UPDATES = True"
    if source.count(switch) != 1:
        raise ValueError("Build selector missing or already transformed")
    if marketplace:
        source = source.replace(switch, "ENABLE_UPDATES = False")
    files = {}
    for name in MODULES + DOCUMENTS + (() if marketplace else GITHUB_ONLY):
        path = ROOT / name
        if not path.is_file():
            raise FileNotFoundError(path)
        files[name] = path.read_bytes()
    files[NAME + ".manifest"] = (ROOT / (NAME + ".manifest")).read_bytes()
    files[NAME + ".py"] = source.encode("utf-8")
    return files


def package_xml(version):
    """Autodesk Fusion add-in bundle; ComponentEntry resolves its .manifest."""
    root = ElementTree.Element("ApplicationPackage", {
        "AutodeskProduct": "Fusion360",
        "SchemaVersion": "1.0",
        "Name": NAME,
        "Description": "Generate editable isogrid sketches and pocket cuts",
        "AppVersion": version,
        "Author": PUBLISHER,
    })
    ElementTree.SubElement(root, "Components")
    ElementTree.SubElement(root.find("Components"), "ComponentEntry", {
        "ModuleName": "./Contents/" + NAME + ".manifest",
        "AppName": NAME,
        "Version": version,
    })
    ElementTree.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ElementTree.tostring(root, encoding="utf-8") + b"\n"


def make_icon(size):
    """Original dark-background triangular isogrid mark, PNG via stdlib."""
    def segment_distance(x,y,x0,y0,x1,y1):
        dx=x1-x0;dy=y1-y0
        u=max(0,min(1,((x-x0)*dx+(y-y0)*dy)/(dx*dx+dy*dy)))
        return math.hypot(x-x0-u*dx,y-y0-u*dy)

    rows=[]
    for iy in range(size):
        row=bytearray([0])
        for ix in range(size):
            x=(ix+.5)/size;y=(iy+.5)/size
            r=int(17+12*y);g=int(28+17*y);b=int(42+20*y)
            # Raised, triangular grid panel in the centre.
            # Upper/lower diagonals form the same 60-degree lattice as Isogrid.
            x0=.16; x1=.84; y0=.17; y1=.82
            if x0<x<x1 and y0<y<y1:
                step=.22
                d=min(abs((y-y0)/step-round((y-y0)/step))*step,
                      abs(((y-y0)-math.sqrt(3)*(x-x0)) / (math.sqrt(3)+1) / step
                          - round(((y-y0)-math.sqrt(3)*(x-x0))/(math.sqrt(3)+1)/step))*step,
                      abs(((y-y0)+math.sqrt(3)*(x-x0)) / (math.sqrt(3)+1) / step
                          - round(((y-y0)+math.sqrt(3)*(x-x0))/(math.sqrt(3)+1)/step))*step)
                if d<.017:
                    r,g,b=67,190,188
                elif d<.029:
                    r,g,b=35,105,124
                else:
                    r,g,b=23,52,69
            # Symmetric outer frame.
            border=min(x,1-x,y,1-y)
            if .075<border<.102:
                r,g,b=218,151,75
            if .105<border<.122:
                r,g,b=64,83,97
            # Square-out sharp corners for legibility at 120 px.
            row.extend((r,g,b))
        rows.append(bytes(row))
    raw=b"".join(rows)
    def chunk(typ,data):
        return struct.pack(">I",len(data))+typ+data+struct.pack(">I",zlib.crc32(typ+data)&0xffffffff)
    return (b"\x89PNG\r\n\x1a\n"
            +chunk(b"IHDR",struct.pack(">IIBBBBB",size,size,8,2,0,0,0))
            +chunk(b"IDAT",zlib.compress(raw,9))
            +chunk(b"IEND",b""))


def write_zip(path, members):
    with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as output:
        for name,data in sorted(members.items()):
            info=zipfile.ZipInfo(name, ZIP_DATE)
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o644 << 16
            output.writestr(info,data)


def verify_package(path,version,marketplace):
    version=validate_version(version)
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)):
            raise ValueError("Duplicate archive paths")
        prefix=BUNDLE + "/Contents/" if marketplace else NAME + "/"
        source_name=prefix+NAME+".py"
        manifest_name=prefix+NAME+".manifest"
        for required in (source_name,manifest_name,prefix+"geometry.py",prefix+"PRIVACY.md"):
            if required not in names:
                raise ValueError("Missing "+required)
        source=archive.read(source_name).decode("utf-8")
        ast.parse(source)
        manifest=json.loads(archive.read(manifest_name))
        if manifest["version"] != version or manifest["author"]!=PUBLISHER:
            raise ValueError("Invalid package manifest metadata")
        if marketplace:
            if prefix+"update_checker.py" in names or "ENABLE_UPDATES = False" not in source:
                raise ValueError("Marketplace build still includes the updater")
            if not any(x.startswith(BUNDLE+"/") for x in names):
                raise ValueError("Bundle root missing")
            xml=ElementTree.fromstring(archive.read(BUNDLE+"/PackageContents.xml"))
            entry=xml.find("Components/ComponentEntry")
            if xml.get("AutodeskProduct")!="Fusion360" or entry is None:
                raise ValueError("Invalid Fusion package declaration")
            if entry.get("ModuleName")!="./Contents/"+NAME+".manifest":
                raise ValueError("Package component does not point to the manifest")
            if prefix+"icon.png" not in names:
                raise ValueError("Marketplace icon missing")
        else:
            if prefix+"update_checker.py" not in names or "ENABLE_UPDATES = True" not in source:
                raise ValueError("GitHub updater missing")
        if any("/tests/" in x or "/__pycache__/" in x or "/studies/" in x for x in names):
            raise ValueError("Repository-only files inside distribution")


def build(version, destination):
    version=validate_version(version)
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    github=destination/f"{NAME}-v{version}-github.zip"
    marketplace=destination/f"{NAME}-v{version}-marketplace.zip"
    icon=make_icon(120)
    (destination/"marketplace-icon-120.png").write_bytes(icon)
    (destination/"marketplace-icon-512.png").write_bytes(make_icon(512))
    write_zip(github,{NAME+"/"+name:data
                      for name,data in package_source(version,False).items()})
    bundle_members={BUNDLE+"/Contents/"+name:data
                    for name,data in package_source(version,True).items()}
    bundle_members[BUNDLE+"/PackageContents.xml"]=package_xml(version)
    bundle_members[BUNDLE+"/Contents/icon.png"]=icon
    write_zip(marketplace,bundle_members)
    verify_package(github,version,False)
    verify_package(marketplace,version,True)
    files=(github,marketplace,destination/"marketplace-icon-120.png",
           destination/"marketplace-icon-512.png")
    checksums="".join(hashlib.sha256(f.read_bytes()).hexdigest()+"  "+f.name+"\n"
                      for f in files)
    (destination/"SHA256SUMS.txt").write_text(checksums,encoding="ascii")
    for f in files:
        print(f.name, f.stat().st_size, "bytes")
    print("Validated both packages and wrote SHA256SUMS.txt")
    return files


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--version",required=True)
    parser.add_argument("--out",default="dist")
    args=parser.parse_args()
    build(args.version, ROOT / args.out)
