# fusion360-isogrid

A Fusion 360 add-in that applies an **isogrid pattern** to a planar face of an existing solid. It creates rounded triangular pockets, with optional holes at the grid vertices, as one sketch and one extrusion cut.

## Features

- **Select a face** and use its perimeter and existing holes as boundaries.
- **Optional sketch boundary** to restrict the patterned area.
- **Adjustable grid:** Cell pitch, rib width, extrusion depth, corner radius, vertex holes, perimeter and hole clearances. Vertex holes default to 3 mm; **Auto Max Hole** calculates the largest nominal diameter that preserves a rib-width material web around an interior junction.
- **Placement:** X/Y offsets, rotation, origin point and edge alignment.
- **Optional Auto Fit:** Search pitch, phase and optional rotation for clean, integer-like lattice fits across irregular boundaries. The best fit is selected first; maximum material removal remains a separate candidate. Manual controls remain available.
- **Interactive preview** with working/ready status and advisory geometry warnings that leave OK enabled.
- **Trim to boundary** is on by default; turn it off to generate complete triangles and circles for manual trimming.

## Install

1. Download this repository with **Code → Download ZIP**, or clone it.
2. Ensure the add-in folder is named `fusion360-isogrid` and contains `fusion360-isogrid.py` and `fusion360-isogrid.manifest`.
3. In Fusion, open **Utilities → Scripts and Add-Ins → Add-Ins**.
4. Add the folder using **+**, select `fusion360-isogrid` and click **Run**.

The command appears in **Solid → Add-Ins → fusion360-isogrid**.

The command title displays the **currently running version** (for example, `fusion360-isogrid v0.7.6`). The command checks for updates automatically when opened and provides a **Check for Updates** button to manually query GitHub immediately, bypassing the 30-minute cache. Manual checks report **Up to date**, an available version, or a network error. When a newer version is available, **Install Update** installs it directly. After installation, restart Fusion and reopen the command to confirm the running version. Existing dependencies and other local files are preserved.

## Use

1. Start the command and select a planar solid face.
2. Optionally select a sketch region to limit the pattern.
3. Adjust pitch, ribs, depth, corner radius, margins and vertex holes. The default hole is 3 mm; click **Auto Max Hole** for the largest nominal diameter preserving the rib-width minimum web. The result remains editable.
4. Position the grid manually or click **Find Fits** to choose a suggested layout. You can adjust that choice afterwards.
5. Inspect the preview and click **OK** to create the sketch and cut.

Every pocket uses the same extrusion depth. Existing holes are exclusion areas while boundary trimming is enabled. When two fillets compete for space, the engine removes the interfering narrow tip using exact circular geometry and retains the specified radius. If even this cannot fit, the original pocket is retained with an advisory warning for manual review.

**Current scope:** Planar faces. Face and sketch boundaries can use lines,
circles, circular arcs, ellipses, elliptical arcs, rational and nonrational
NURBS splines (including Fusion conics), and polylines. Lines and circles use
analytic intersections; ellipse, spline and general offset operations preserve
parametric curves and use numerical intersection/area calculations as needed.
The resulting Fusion sketch contains native lines, arcs, ellipses and splines,
not polygonal approximations of source curves. General spline/ellipse *offsets*
are approximated as smooth cubic splines only when writing the final sketch.
Pure Python; no extra dependencies. The geometry is restricted to planar faces.

## More information

- [Advanced setup and technical notes](ADVANCED.md)
- [Release history](CHANGELOG.md)
- [Licence](LICENSE)
