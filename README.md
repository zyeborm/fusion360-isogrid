# fusion360-isogrid

A Fusion 360 add-in that creates an **isogrid pattern** on a planar face of an existing solid. It generates rounded triangular pockets, with optional holes at grid junctions, as a sketch and a single extrusion cut.

## Features

- **Face selection:** Fill a planar face while respecting its outside edge and existing holes.
- **Optional sketch boundary:** Limit the pattern to a selected sketch region.
- **Adjustable pattern:** Cell pitch, rib width, pocket depth, corner radius, vertex-hole diameter, perimeter and hole clearances.
- **Placement:** X/Y offsets, rotation, selectable origin and edge alignment.
- **Auto Fit (optional):** Search a minimum/maximum pitch range and choose from several suggested layouts. The normal manual controls remain available.
- **Live preview:** Pattern outlines update as settings change, with a working/ready indicator and warnings for questionable geometry.
- **Trim to boundary:** On by default. Turn it off to generate full cells for manual sketch trimming.

## Install

1. Download the repository using **Code → Download ZIP** (or clone it).
2. Ensure the extracted add-in folder is named **`fusion360-isogrid`** and contains `fusion360-isogrid.py` and `fusion360-isogrid.manifest`.
3. In Fusion, open **Utilities → Scripts and Add-Ins → Add-Ins**.
4. Add the folder using **+**, select **fusion360-isogrid**, and click **Run**.

The command appears under **Solid → Add-Ins → fusion360-isogrid**.

When you open the command, it checks GitHub for a newer version and shows a link if an update is available. To update, close Fusion, replace the add-in files, and restart Fusion.

## Use

1. Start the command and select a **planar face**.
2. Optionally select a sketch region to limit the pattern.
3. Set pitch, ribs, depth, margins, corner radius and any vertex holes.
4. Position the grid manually, or click **Find Fits** and pick a suggested layout. You can adjust that layout afterwards.
5. Inspect the preview and click **OK** to create the sketch and cut.

The depth is shared by all pockets. Existing face holes are treated as exclusions when boundary trimming is enabled. Some tight clipped corners may remain sharp if the requested radius cannot fit; the add-in reports these in **Geometry warnings**.

**Current scope:** Planar faces.

## More information

- [Advanced setup and technical notes](ADVANCED.md)
- [Release history](CHANGELOG.md)
- [Licence](LICENSE)
