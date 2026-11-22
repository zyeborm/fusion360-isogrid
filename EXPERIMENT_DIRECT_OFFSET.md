# Geometry-only direct boundary offset experiment

Branch: `experiment/direct-offset-geometry` (not merged). Fusion sketch/export and the regular production execution path are unchanged.

## Approach

- Create the permitted offset boundary **once**, using the existing exact engine on a bounding rectangle. The curved DXF fixture yields seven outer segments and one circular void.
- Test whether the finished, *rounded* triangle already fits. This skips clipping where a boundary grazes only the sharp unrounded tip.
- Otherwise intersect three triangle lines with the shared offset boundary and retain the relevant **parametric curve intervals**. Chords are broad-phase intersection candidates only; the cut contour keeps native Offset/Arc/Line segments.
- Round directly at feasible vertices. Detect radius-infeasible convex slivers using an area/perimeter bound; where a short edge can be replaced by one tangent arc, bridge it directly. Retain the original full disk-opening Boolean for geometrically harder cases.
- If creation of the global shared boundary drops a protected void (seen with one elliptical-void fixture), fall back to the original exact clipper.

The sole change in `geometry.py` is an optional `round_pocket` argument so the alternate local corner routine can be supplied **only by an explicit benchmark/test invocation**. Fusion never selects this experimental mode.

## Full-generation benchmark

All timings are Python wall-clock seconds, on the test container, with the existing spline distance/area LRU caches cleared *for each run*. Times include shared-boundary preparation, pocket clipping, filleting, minimum area filtering and vertex-hole eligibility. Baseline and direct runs alternate. Both versions use the same source geometry, triangle count and corner radius.

| Curved fixture | Baseline run 1 / 2 | Direct run 1 / 2 | Median speedup |
|---|---:|---:|---:|
| 20 mm default pitch | 3.50 / 3.12 s | 1.42 / 1.25 s | 2.49x |
| 19.28114 mm Auto Fit | 4.23 / 3.99 s | 2.00 / 1.76 s | 2.19x |

Default: 131 accepted cut shapes, 6 infeasible pockets rejected, 110 direct offset/triangle intersections after early rounded eligibility. Auto Fit: 131 shapes, 4 rejections, 78 intersections. Results are from a *reconstructed* source DXF profile, not live Fusion.

Sampled per-pocket symmetric difference between original and experimental cut regions (summed): **0.000001087 mm²** default and **0.000000374 mm²** Auto Fit. All 131 pocket identities and output curve-loop closures match. Geometric similarity is based on sampled curves; it is not a formal Boolean proof for arbitrary input topology.

Additional test fixtures: rectangle, rectangle with circular void, and rectangle with elliptical void (the latter uses exact fallback). Existing tests plus new experiment tests: **171 run, 170 passed, 1 skipped**.

## Reproduce

```bash
python benchmark_direct_full.py
python -m unittest discover -s tests -q
```

Shapely is optional and is used only to report sampled geometric differences in the benchmark; the direct geometry engine itself uses pure Python and the add-in's own curve primitives.

## Limitations and next work

This is a geometry prototype, not a production-ready replacement for the general clipper. More cases involving intersecting voids, concave regions, curve junction tangencies, touching contours and complex elliptical boundaries need verification. Two genuinely trimmed Auto Fit pockets still use the expensive disk-opening repair and dominate much of the remaining delay. The measured end-to-end improvement is 2.2–2.5x, **not** an order of magnitude.
