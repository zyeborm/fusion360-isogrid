# Advanced notes

This file covers implementation details for `fusion360-isogrid`. See the [README](README.md) for installation and normal use.

## Geometry

The add-in converts the selected planar face, voids and optional sketch boundaries into a 2D usable region. It builds and clips a triangular pocket lattice, then applies corner rounding. The final feature is a Fusion sketch plus a single extrusion cut at the user-entered depth.

With trimming disabled, the 2D grid extends across the selected region's bounding extent. Overlapping profiles may need manual correction before machining. In trimmed mode, small fragments and corners unable to accept the full rounding radius are reported as warnings; feasible pocket geometry is preserved.

## Auto Fit

An optional deterministic bounded differential-evolution search evaluates the same 2D geometry that is used for the final cut. It searches pitch within user-defined limits, lattice phase and optionally rotation. It returns candidates selected for removed area, boundary quality, symmetry and closeness to nominal pitch. The extrusion depth does not participate in this 2D search.

## Geometry backend

The add-in currently uses its dependency-free, prepared-region Python geometry engine exclusively. No additional packages are required.

An optional Shapely/GEOS implementation remains in `geometry_compiled.py`, alongside its inactive loader and backend-selector code (commented out in `geometry.py` and `fusion360-isogrid.py`). The compiled backend is **disabled**, including its import at startup, because an incompatible native library can crash Fusion. `install_backend.py` is retained for possible future development, rather than as a supported installation step.

## Background processing and update notice

2D preview and Auto Fit calculations run in a dedicated Python thread, with custom events returning results to Fusion's main thread. CAD feature creation and viewport graphics remain on the main thread. Obsolete preview calculations are superseded by newer edits.

When the user **opens the isogrid command**, a separate short-lived thread checks the version in the public GitHub `main` manifest. A newer version appears as a clickable notice in the command dialog. Results are cached for 30 minutes. Network failures are silent. No code is downloaded, replaced or executed by the updater. Version numbers must be increased in the manifest when publishing a new version.

## Tests

```sh
python -m unittest discover -s tests -v
python benchmarks.py
```

The tests run outside Fusion; the UI and CAD creation still require verification in Fusion itself.

## Source files

- `fusion360-isogrid.py`: Fusion command, preview and final feature
- `geometry.py`: pure Python geometry engine
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
