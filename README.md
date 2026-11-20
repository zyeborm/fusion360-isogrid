# fusion360-isogrid

A Fusion 360 add-in that applies an **isogrid pattern** to a planar face of an existing solid. It creates rounded triangular pockets, with optional holes at the grid vertices, as one sketch and one extrusion cut.

## Features

- **Select a face** and use its perimeter and existing holes as boundaries.
- **Optional sketch boundary** to restrict the patterned area.
- **Adjustable grid:** Cell pitch, rib width, extrusion depth, corner radius, vertex holes, perimeter and hole clearances. Vertex holes default to 3 mm; **Auto Max Hole** calculates the largest nominal diameter that preserves a rib-width material web around an interior junction.
- **Placement:** X/Y offsets, rotation, origin point and edge alignment.
- **Optional Auto Fit:** Search pitch, phase and optional rotation for clean, integer-like lattice fits across irregular boundaries. The best fit is selected first; maximum material removal remains a separate candidate. Manual controls remain available. The search scores a margin-aware raster approximation rather than repeatedly constructing exact cut geometry; the selected layout uses the full native-curve clipping engine for preview and extrusion. Fit metrics are estimates until the selected preview completes.
- **Interactive preview** with working/ready status and advisory geometry warnings that leave OK enabled.
- **Optional manufacturability inputs, integrated into the main dialog:** cutter diameter, minimum material web, minimum usable pocket diameter, and an assumed uniform material thickness / minimum remaining skin. Zero disables each new constraint. Cutter diameter increases the effective corner radius. The web limit increases the effective rib width and edge clearances. Infeasible pocket islands are omitted and reported, and sampled web violations are outlined in red. Existing vertex holes remain independent drillable features.
- **Sparse named parameter presets:** expand **Parameter presets**, tick any combination of numeric expressions, switches, grid anchor, or fit effort, and save a user-defined name. Applying a preset changes only those selected values; other active settings and the selected face remain untouched. Edited parameters are preselected for saving unless manually excluded. Presets preserve expression text and are saved per user as JSON outside the installed add-in.
- **Trim to boundary** is on by default; turn it off to generate complete triangles and circles for manual trimming.

## Install

1. Download this repository with **Code → Download ZIP**, or clone it.
2. Ensure the add-in folder is named `fusion360-isogrid` and contains `fusion360-isogrid.py` and `fusion360-isogrid.manifest`.
3. In Fusion, open **Utilities → Scripts and Add-Ins → Add-Ins**.
4. Add the folder using **+**, select `fusion360-isogrid` and click **Run**.

The command appears in **Solid → Add-Ins → fusion360-isogrid**.

### Manufacturability settings

The additional dimensions are optional (default **0 mm**). They are applied
to the existing patterning workflow; there is no separate manufacturing mode.

- **Cutter diameter:** sets a floor on the *inside pocket corner radius* (half
  the cutter diameter), and omits pockets without a usable cutter-centre
  location or where corner repair could not retain that radius. Vertex holes
  are left for independent drilling.
- **Minimum material web:** establishes a lower bound for the rib width,
  perimeter margin and clearance at existing voids. The finished sampled cut
  contours are also checked against one another and the source boundary;
  violations are highlighted in red with a warning count. This sampled check
  is a manufacturing diagnostic, not a metrology certificate.
- **Minimum usable pocket diameter:** omits cut islands too small to contain
  an inscribed circle of the specified diameter (a conservative minimum
  access check, not a complete toolpath-accessibility proof).
- **Material thickness / Minimum remaining skin:** when the material thickness
  is supplied, the requested pocket depth must leave at least the specified
  skin. Thickness is assumed uniform; the add-in does not infer local stock
  thickness from complex B-reps.

The output remains a normal, manually editable Fusion sketch and extrusion
cut, without any managed-editing or replacement-feature mechanism.

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
