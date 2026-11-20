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

Vertex holes default to 3 mm, with the existing manual diameter field remaining editable. **Auto Max Hole** is a one-shot command that reserves a **minimum radial web equal to the specified rib width** between the hole and the nearest rounded pocket.

For equilateral pockets with feasible fillets, the *contact* diameter is `D_contact = 2(w + r)`, where `w` is rib width and `r` is pocket corner radius. A minimum web `w` is required on **both sides of the hole's diameter**, so the web-preserving maximum is `D_auto = max(0, D_contact - 2w) = 2r`. Thus 2 mm ribs and 1.5 mm fillets give a 7 mm *contact* diameter but a 3 mm Auto Max Hole diameter, leaving 2 mm of material to the nearest pocket. Subtracting the rib width only once would leave half the intended web thickness.

The calculation is nominal for ideal interior junctions. Tight or clipped pocket corners can alter actual clearance; boundary restrictions and neighbouring holes are handled separately. The button updates the preview immediately and leaves the result manually editable. Diameter values above the web-preserving limit produce non-blocking warnings; at the contact limit the warning identifies tangency, and beyond it overlapping cuts.

## Auto Fit

An optional deterministic bounded multi-start differential-evolution search evaluates the same finished 2D pockets used for the final cut. It searches pitch, lattice phase and optionally rotation. Three independent geometry-fit searches cover logarithmically spaced sections of the *user-selected* pitch range, while one separate pass maximises material removal. The best geometric fit is offered first in the command; maximum removal remains an explicit alternative. Extrusion depth does not participate in this 2D search.

**Integer-like fit metric:** For each source triangle, measure the retained finished-pocket area relative to an untrimmed, rounded reference pocket; sum pieces split from the same source triangle before scoring. Partial-cell penalties include a fixed component and a `4f(1-f)` term, where `f` is the fraction retained. A spatial graph connects nearby partial triangle centroids. Long, nearly straight runs with similar retained fractions receive an additional penalty, targeting the systematic half-triangle strips seen when grid phase or pitch mismatches a boundary. The penalty is normalised by the input boundary length divided by pitch, keeping it dimensionless across 40 mm and metre-scale parts. Small tie-breakers consider relative removed area and closeness to the nominal pitch; the score is geometric only, not a strength estimate.

The optimiser retains distinct pitches and phases so the user can compare alternatives. The first choice is the best geometry-fit result; the last is **Maximum removal**. The other candidates can be applied or manually adjusted. Results display pitch, partial-cell count, longest connected partial run, and fit score. The study at `studies/FINDINGS.md` compares the new method with manual nominal placement and the previous Clean Edges objective across six synthetic parts. The visual-study script needs optional Matplotlib/Pillow *only when generating plots*; the add-in itself has no additional dependencies.

## Geometry backend

The add-in currently uses its dependency-free, prepared-region Python geometry engine exclusively. No additional packages are required.

An optional Shapely/GEOS implementation remains in `geometry_compiled.py`, alongside its inactive loader and backend-selector code (commented out in `geometry.py` and `fusion360-isogrid.py`). The compiled backend is **disabled**, including its import at startup, because an incompatible native library can crash Fusion. `install_backend.py` is retained for possible future development, rather than as a supported installation step.

## Background processing and update notice

2D preview and Auto Fit calculations run in a dedicated Python thread, with custom events returning results to Fusion's main thread. CAD feature creation and viewport graphics remain on the main thread. Obsolete preview calculations are superseded by newer edits.

When the user **opens the isogrid command**, a separate short-lived thread checks the version in the public GitHub `main` manifest. Automatic results are cached for 30 minutes and network failures are silent. The **Check for Updates** button bypasses the cache, reusing a request already in progress if necessary. Manual checks explicitly display checking, up-to-date, available-update, or network-error status in the command. If a newer version exists, **Install Update** downloads the public repository archive on demand and installs it in a staged, rollback-capable operation. The loaded add-in remains unchanged until Fusion restarts. Version numbers must be increased in the manifest when publishing a new version.

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
pocket fillets, the contact diameter is `2 × (rib width + corner radius)`.
**Auto Max Hole** subtracts twice the rib width from this diameter to retain
the specified minimum material web on both radial sides. Boundaries and
neighbouring existing holes can impose additional constraints.
