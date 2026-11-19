# Advanced notes

This file covers implementation details for `fusion360-isogrid`. See the [README](README.md) for installation and normal use.

## Geometry

The add-in converts the selected planar face, voids and optional sketch boundaries into a 2D usable region. It builds and clips a triangular pocket lattice, then applies corner rounding. The final feature is a Fusion sketch plus a single extrusion cut at the user-entered depth.

### Analytic line and arc engine (v0.7)

Fusion line, arc and circle edges are converted to **directed, exact** 2D segments. The canonical primitives are in `curves2d.py`; intersection/arrangement clipping is in `exact_clipper.py`. Normal planar faces and sketch profiles can contain multiple exterior loops, internal voids, tangencies and circular cutouts.

The pure-Python engine intersects line/line, line/arc and arc/arc segments analytically, splits the segments at intersection parameters, tests the two sides of each fragment against the allowed region, and assembles closed contours. Edge clearances are constructed from line/arc offsets with true circular endcaps. All common contour areas and centroids use exact Green's-theorem integrals over straight segments and circular sectors.

Clipped-pocket fillets solve for a circle tangent to the neighbouring analytic curves. Where full-radius fillets compete for a short edge, a second pass performs an analytic disk opening: erode the pocket by the requested radius, then dilate the surviving centre region by the same radius. This removes narrow tips while preserving a *full-radius* fillet and avoiding intrusion into protected material. The final curves remain **lines and arcs**, including when a pocket meets an existing circular cutout. Fusion receives native sketch lines, arcs and full circles. Preview outlines are chord-tolerance samples derived from the final curves.

An unsupported input curve (ellipse, NURBS spline, conic) is currently sampled into segments at the input boundary. This maintains input acceptance while reserving exact-curve operations for the first release's lines and circular arcs. The arrangement code uses an extensible primitive interface; additional curve families can be added without redesigning lattice generation or Auto Fit.

**Geometric limitation:** Some partial pockets are too small to contain even one circle of the requested milling radius. These cannot be repaired by disk opening. The engine retains them with sharp-corner advisories for manual review rather than changing the selected radius or silently removing the pocket. The Fusion runtime integration has yet to be tested against the supplied B-Rep file in a live design.

With trimming disabled, the 2D grid extends across the selected region's bounding extent. Overlapping profiles may need manual correction before machining. In trimmed mode, small fragments and corners unable to accept the full rounding radius are reported as warnings; feasible pocket geometry is preserved.

## Vertex holes

Vertex holes default to 5 mm, with the existing manual diameter field remaining editable. **Auto Max Hole** is a one-shot command that uses the current rib width `w` and pocket fillet radius `r` to set the theoretical interior-junction limit `D = 2(w + r)` (a 7 mm hole for the default 2 mm ribs and 1.5 mm fillets). The calculation uses the same geometry rule as the advisory warnings and updates the preview immediately.

The exact limit produces tangency to ideal full-cell pocket fillets, with zero nominal clearance. A slightly smaller manual value can avoid coincident profiles in Fusion. The formula assumes the chosen radius fits inside the triangular pocket; tight clipped pockets and boundary clearance remain subject to the usual geometry checks.

## Auto Fit

An optional deterministic bounded differential-evolution search evaluates the same 2D geometry that is used for the final cut. It searches pitch within user-defined limits, lattice phase and optionally rotation. It returns candidates selected for removed area, boundary quality, symmetry and closeness to nominal pitch. The extrusion depth does not participate in this 2D search.

## Geometry backend

The add-in currently uses its dependency-free, prepared-region Python geometry engine exclusively. No additional packages are required.

An optional Shapely/GEOS implementation remains in `geometry_compiled.py`, alongside its inactive loader and backend-selector code (commented out in `geometry.py` and `fusion360-isogrid.py`). The compiled backend is **disabled**, including its import at startup, because an incompatible native library can crash Fusion. `install_backend.py` is retained for possible future development, rather than as a supported installation step.

## Background processing and update notice

2D preview and Auto Fit calculations run in a dedicated Python thread, with custom events returning results to Fusion's main thread. CAD feature creation and viewport graphics remain on the main thread. Obsolete preview calculations are superseded by newer edits.

When the user **opens the isogrid command**, a separate short-lived thread checks the version in the public GitHub `main` manifest. Results are cached for 30 minutes and network failures are silent. If a newer version exists, **Install Update** downloads the public repository archive on demand and installs it in a staged, rollback-capable operation. The loaded add-in remains unchanged until Fusion restarts. Version numbers must be increased in the manifest when publishing a new version.

## Tests

```sh
python -m unittest discover -s tests -v
python benchmarks.py
```

The tests run outside Fusion; the UI and CAD creation still require verification in Fusion itself.

## Source files

- `fusion360-isogrid.py`: Fusion command, preview and final feature
- `geometry.py`: pattern generator, region compatibility and exact clipping adapter
- `curves2d.py`: exact 2D line/arc primitives, intersections, offsets, area/centroid
- `exact_clipper.py`: pure-Python analytic region clipping and tangent fillets
- `geometry_compiled.py`: archived, disabled GEOS clipping implementation
- `fitting.py`: Auto Fit optimiser
- `async_engine.py`: preview worker and results
- `update_checker.py`: on-demand, non-blocking GitHub version notification
- `install_backend.py`: archived optional dependency installer
- `tests/`: geometry, fitting and lifecycle tests


## Update installation

The command checks the version in the public repository manifest when opened,
with a 30-minute cache. **Install Update** downloads the repository ZIP from
GitHub in a background thread. It validates the archive layout, add-in ID, and
expected version before writing files. Source files are staged on the same
volume and backed up for rollback if a write fails. Local `vendor/` and
other additional user files are left unchanged. Restart Fusion after the update;
loaded Python modules are deliberately not replaced in memory. The operation
requires write access to the add-in directory and HTTPS access to GitHub.

## Advisory fields

Geometry warnings are non-blocking. Fusion's native `isValueError` styling
can also disable the OK button, so warnings use input tooltips and the Geometry
warnings area instead. Invalid geometry can still cause a descriptive feature
generation error when OK is pressed.

For an interior lattice junction with equilateral triangles and feasible
pocket fillets, the maximum nominal vertex-hole diameter is
`2 × (rib width + corner radius)`. A hole at that limit touches the pockets
and may create coincident sketch geometry. Boundaries and neighbouring
existing holes can impose additional constraints.
