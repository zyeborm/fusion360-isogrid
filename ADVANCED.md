# Advanced notes

Technical details, optional dependencies, diagnostics and development information for `fusion360-isogrid`. For installation and ordinary use, see the [README](README.md).

## Geometry and final features

The add-in extracts planar boundary loops (including interior holes) from Fusion, then uses a 2D pattern generator to build and clip triangular pockets. The same generator is used for manual previews, Auto Fit scoring and final output.

Boundary preparation caches the permitted area with perimeter margins and hole clearances. Completely interior pockets are accepted directly; boundary-adjacent pockets are clipped against the prepared region. Rounded corners are applied to the clipped results.

At completion, the add-in creates a Fusion sketch with the pocket outlines and one multi-profile cut extrusion, using the selected depth. The result is an ordinary Fusion timeline feature.

With **Trim to boundary / voids** enabled (default), pockets respect the face, optional sketch boundary and clearances. Disabling trimming retains full triangle and circle outlines extending across the selected region's bounding extent; this is intended for manual trimming. The final cut is still attempted, and overlapping profiles or protected regions may require manual cleanup.

When a clipped corner cannot fit the specified radius, available corners are rounded and the pocket is retained. Any remaining sharp corners are reported in the UI. Those corners may require manual adjustment before machining with a cutter of the specified radius. Vertex holes approaching or exceeding rib width can similarly create overlapping or unusable cut profiles.

## Auto Fit

Auto Fit is optional and writes selected results back into the usual pitch and placement controls. It searches cell pitch between user-defined bounds, X/Y lattice phase, and optionally rotation.

A deterministic, bounded differential-evolution search evaluates the *actual 2D pocket generator* for each candidate. Independent searches target:

- Maximum removed area
- Cleaner perimeter termination
- Symmetry
- Closeness to nominal pitch

The command offers 120, 320 or 1,000 evaluation budgets and returns distinct candidate layouts. Extrusion depth is excluded from the search, as this is a 2D layout problem.

## Geometry backend

The add-in currently uses the dependency-free, prepared-region Python geometry engine exclusively. No additional packages are required.

The Shapely/GEOS implementation remains in `geometry_compiled.py`. Its import and Fusion UI selector are commented out in `geometry.py` and `fusion360-isogrid.py`, respectively. The native backend is deliberately disabled because incompatible compiled packages may crash Fusion during import. `install_backend.py` is retained for potential future development, rather than as a supported installation step.

## Asynchronous preview

The add-in runs 2D pattern and Auto Fit work on a dedicated Python background thread. Rapid parameter edits supersede pending previews; completed results are transferred to Fusion's main thread through a custom event. Fusion sketch construction, preview graphics and extrusion creation remain on the main thread.

The indicator reports idle, working, ready or error, and Auto Fit progress. This thread-based design improves UI responsiveness; it is not the same as process-based multicore parallelism for Python work.

## Update availability check

When the user opens the command, a short-lived background thread reads the version from the public GitHub `main` manifest. Results are cached for 30 minutes, and network failures leave the command unaffected. A newer version appears as a hyperlink in the dialog. No files are downloaded or installed automatically.

Increment the `version` in `fusion360-isogrid.manifest` when publishing a new version. The check requires no GitHub API token and makes no periodic network requests.

## Development and tests

Source layout:

| File | Responsibility |
| --- | --- |
| `fusion360-isogrid.py` | Fusion UI, preview and final sketch/cut |
| `async_engine.py` | Background work, cancellation and result delivery |
| `geometry.py` | Shared 2D geometry and pure-Python clipping |
| `geometry_compiled.py` | Optional Shapely/GEOS operations |
| `fitting.py` | Auto Fit optimiser and objectives |
| `install_backend.py` | Optional dependency installer |
| `benchmarks.py` | Comparable layout-performance benchmarks |
| `tests/` | Geometry, optimisation, lifecycle and validation regressions |

From the repository directory:

```sh
python -m unittest discover -s tests -v
python benchmarks.py
```

The 0.6.3 standalone suite has 50 tests. These cover polygon clipping, irregular boundaries, rounded corners, hole exclusions, Auto Fit, asynchronous cancellation and simulated preview lifecycle. Fusion-specific UI and final CAD operations need in-application validation.

### Reference benchmark

Matched 20-layout workload measured outside Fusion during the v0.5 geometry refactor:

| Geometry | Python per layout | GEOS per layout |
| --- | ---: | ---: |
| 100 × 100 mm rectangle | 6.1 ms | 4.4 ms |
| Rectangle with a circular void | 14.8 ms | 5.7 ms |
| Curved perimeter with three voids | 38.5 ms | 17.5 ms |

These figures exclude one-time preparation. They describe that development environment, rather than guaranteed Fusion performance.

For historical changes, see the [changelog](CHANGELOG.md).
