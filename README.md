# fusion360-isogrid

A Fusion 360 add-in that applies an **isogrid pattern** to a planar face of an existing solid. It creates rounded triangular pockets, with optional holes at the grid vertices, as one sketch and one extrusion cut.

## Features

- **Select a face** and use its perimeter and existing holes as boundaries.
- **Optional sketch boundary** to restrict the patterned area.
- **Adjustable grid:** Cell pitch, rib width, extrusion depth, corner radius, vertex holes, perimeter and hole clearances. Vertex holes default to 3 mm; **Auto Max Hole** calculates the largest nominal diameter that preserves a rib-width material web around an interior junction.
- **Placement:** X/Y offsets, rotation, origin point and edge alignment.
- **Optional Auto Fit:** Search pitch, phase and optional rotation for clean, integer-like lattice fits across irregular boundaries. The best fit is selected first; maximum material removal remains a separate candidate. Manual controls remain available. The search scores a margin-aware raster approximation rather than repeatedly constructing exact cut geometry; the selected layout uses the full native-curve clipping engine for preview and extrusion. Fit metrics are estimates until the selected preview completes.
- **Interactive preview** with working/ready status and advisory geometry warnings that leave OK enabled. Repeated Fusion redraw events reuse the completed line-coordinate buffer instead of transforming the same vertices again.
- **Cut-profile recovery:** Native sketch-curve ownership identifies Fusion profiles; exact-curve containment provides a fallback when sketch recomputation loses curve association. Missing profiles are reported while valid cut profiles can still be extruded.
- **Manufacturability diagnostics:** The existing rib width, perimeter and void clearances are checked against finished sampled contours. An optional cutter diameter (0 = off) adds tool-radius and cutter-access checks. Violations are highlighted in red, without altering or omitting pocket geometry.
- **Sparse named parameter presets:** expand **Parameter presets**, tick any combination of numeric expressions, switches, grid anchor, or fit effort, and save a user-defined name. Applying a preset changes only those selected values; other active settings and the selected face remain untouched. Edited parameters are preselected for saving unless manually excluded. Presets preserve expression text and are saved per user as JSON outside the installed add-in.
- **Trim to boundary** is on by default; turn it off to generate complete triangles and circles for manual trimming.

## Install

1. Download this repository with **Code → Download ZIP**, or clone it.
2. Ensure the add-in folder is named `fusion360-isogrid` and contains `fusion360-isogrid.py` and `fusion360-isogrid.manifest`.
3. In Fusion, open **Utilities → Scripts and Add-Ins → Add-Ins**.
4. Add the folder using **+**, select `fusion360-isogrid` and click **Run**.

The command appears in **Solid → Add-Ins → fusion360-isogrid**.

### Manufacturability diagnostics

The existing **rib width**, **perimeter margin** and **clearance at voids**
remain authoritative. A post-generation sampled-geometry check reports cuts
that violate these specified material webs, including vertex holes. The
existing minimum retained cell area (%) control discards partial pocket islands
below its area threshold during the normal geometry-generation step.

**Cutter diameter** is the only new manufacturing input, defaulting to **0 mm**:

- **0 mm:** No tool-radius or accessibility checks. Suited to printing,
  casting, and other processes where a milling cutter does not apply.
- **Greater than 0 mm:** Reports corners that could not be rounded and pocket
  regions that cannot contain a disk of the specified tool diameter. A cutter
  radius larger than the requested pocket corner radius produces an advisory.

These checks **never modify the requested rib width, corner radius or margins**
and the cutter setting **never suppresses pockets**. A separate geometry rule
omits clipped islands that cannot retain the requested corner radius even
after repair; their count appears in the dialog. Diagnostics use sampled geometry,
not a complete CNC toolpath-accessibility proof. The output remains a normal,
manually editable Fusion sketch and extrusion cut.

### Named parameter presets

Open **Parameter presets → Values to include when saving**, tick whichever
values should be included, provide a name, then click **Save selected values**.
The add-in selects fields as you edit them but preserves any explicit
inclusion/exclusion you make in that list. Selecting a saved preset applies
only its recorded values; the selected face, mask and source references stay
unchanged. Use **Delete selected preset** to remove one. Saving an existing
name replaces that named set of values.

The portable UTF-8 JSON file is saved to `%APPDATA%/fusion360-isogrid/presets.json`
on Windows, `~/Library/Application Support/fusion360-isogrid/presets.json` on
macOS, or `$XDG_CONFIG_HOME/fusion360-isogrid/presets.json` on Linux. Its
`version` field permits future migrations. Users can back up or transfer this
file themselves.

The command title displays the **currently running version** (for example, `fusion360-isogrid v0.7.6`). The command checks for updates automatically when opened and provides a **Check for Updates** button to manually query GitHub immediately, bypassing the 30-minute cache. Manual checks report **Up to date**, an available version, or a network error. When a newer version is available, **Install Update** installs it directly. After installation, restart Fusion and reopen the command to confirm the running version. Existing dependencies and other local files are preserved.

## Use

1. Start the command and select a planar solid face.
2. Optionally select a sketch region to limit the pattern.
3. Adjust pitch, ribs, depth, corner radius, margins and vertex holes. The default hole is 3 mm; click **Auto Max Hole** for the largest nominal diameter preserving the rib-width minimum web. The result remains editable.
4. Position the grid manually or click **Find Fits** to choose a suggested layout. You can adjust that choice afterwards.
5. Inspect the preview and click **OK** to create the sketch and cut.

Every pocket uses the same extrusion depth. Existing holes are exclusion areas while boundary trimming is enabled. When two fillets compete for space, the engine attempts to remove the interfering narrow tip using exact circular geometry while retaining the specified radius. If even this cannot fit, the infeasible pocket island is omitted from both preview and cut, with a count reported to the user.

**Current scope:** Planar faces. Face and sketch boundaries can use lines,
circles, circular arcs, ellipses, elliptical arcs, rational and nonrational
NURBS splines (including Fusion conics), and polylines. Lines and circles use
analytic intersections; ellipse, spline and general offset operations preserve
parametric curves and use numerical intersection/area calculations as needed.
The resulting Fusion sketch contains native lines, arcs, ellipses and splines,
not polygonal approximations of source curves. General spline/ellipse *offsets*
are approximated as smooth, multi-span cubic NURBS only when writing the final
sketch. Each continuous offset section uses a single sketch entity, preserving
the original tangent-matched cubic approximation and its error tolerance.
Pure Python; no extra dependencies. The geometry is restricted to planar faces.

## More information

- [Advanced setup and technical notes](ADVANCED.md)
- [Release history](CHANGELOG.md)
- [Licence](LICENSE)
