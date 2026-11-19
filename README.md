# fusion360-isogrid

A Fusion 360 add-in that applies an **isogrid pattern** to a planar face of an existing solid. It creates rounded triangular pockets, with optional holes at the grid vertices, as one sketch and one extrusion cut.

## Features

- **Select a face** and use its perimeter and existing holes as boundaries.
- **Optional sketch boundary** to restrict the patterned area.
- **Adjustable grid:** Cell pitch, rib width, extrusion depth, corner radius, vertex holes, perimeter and hole clearances.
- **Placement:** X/Y offsets, rotation, origin point and edge alignment.
- **Optional Auto Fit:** Specify minimum/maximum pitch, find candidate layouts and choose one. Manual controls remain available.
- **Interactive preview** with working/ready status and advisory geometry warnings that leave OK enabled.
- **Trim to boundary** is on by default; turn it off to generate complete triangles and circles for manual trimming.

## Install

1. Download this repository with **Code → Download ZIP**, or clone it.
2. Ensure the add-in folder is named `fusion360-isogrid` and contains `fusion360-isogrid.py` and `fusion360-isogrid.manifest`.
3. In Fusion, open **Utilities → Scripts and Add-Ins → Add-Ins**.
4. Add the folder using **+**, select `fusion360-isogrid` and click **Run**.

The command appears in **Solid → Add-Ins → fusion360-isogrid**.

The command title displays the **currently running version** (for example, `fusion360-isogrid v0.7.0`). When a newer version is available, the command shows **Install Update**, including both the current and available versions. After installation, it reports the newly installed version and requests a Fusion restart. Reopen the command after restarting to confirm that the title has changed. Existing dependencies and other local files are preserved.

## Use

1. Start the command and select a planar solid face.
2. Optionally select a sketch region to limit the pattern.
3. Adjust pitch, ribs, depth, corner radius, margins and any vertex holes.
4. Position the grid manually or click **Find Fits** to choose a suggested layout. You can adjust that choice afterwards.
5. Inspect the preview and click **OK** to create the sketch and cut.

Every pocket uses the same extrusion depth. Existing holes are exclusion areas while boundary trimming is enabled. Tight corners that cannot accommodate the requested radius may remain sharp; the warning area reports them.

**Current scope:** Planar faces. Lines and circular arcs are processed analytically; other source curves are accepted using sampled approximations. Pure Python; no extra dependencies.

## More information

- [Advanced setup and technical notes](ADVANCED.md)
- [Release history](CHANGELOG.md)
- [Licence](LICENSE)
