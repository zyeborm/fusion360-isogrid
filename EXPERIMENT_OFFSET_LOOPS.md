# Self-intersecting offset cleanup — geometry experiment

Branch: `experiment/offset-loop-cleanup`, based on `experiment/direct-offset-geometry`. Not merged. **Fusion integration is unchanged.**

## Algorithm

1. Form one signed parametric offset of the source curve.
2. Find self-intersections using adaptive chords as candidates, then refine crossings on the original parametric offset. Chords do not replace output geometry.
3. Split the offset by the intersection *parameters*.
4. On each interval, test the source-curve clearance. For a closed source, also classify the interval against the permitted side of the source face.
5. Drop the invalid offset intervals (the self-crossing lobes), joining the retained parametric intervals at the exact crossing coordinates.

`OffsetInterval` keeps the original source parameterisation. Reconstructing a new `Offset(base.section(...))` at each crossing produced finite-difference tangent endpoint drift on an open cubic spline. The shared-parameter interval reduces the measured join discrepancy to about `2.6e-12 cm`.

`clean_closed_offset` handles single smooth closed source loops (arcs, ellipses, or NURBS). The experimental `Boundary` uses it for one closed exterior loop and then clips triangles against the cleaned parametric curves. `clean_open_offset` handles self-intersecting offsets of open source curves; composite-curve boundary integration remains future work. Multi-segment regions, holes, and complex topology continue through the previous experimental shared-region implementation.

## Benchmark (Python, development container)

Geometry units are centimetres. The deliberately narrow elliptical exterior is `4 cm × 1 cm` semiaxes; the inward clearance varies. Values are medians over five trials each.

| Clearance | Self-crossings | Retained curve spans | Cleanup time | Sampled symmetric difference vs independent eroded ellipse |
|---|---:|---:|---:|---:|
| 0.1 cm | 0 | 1 | 9 ms | 0.000198 mm² |
| 0.3 cm | 2 | 2 | 10 ms | 0.002065 mm² |
| 0.6 cm | 2 | 2 | 10 ms | 0.002141 mm² |
| 0.9 cm | 2 | 2 | 14 ms | 0.001506 mm² |
| 1.0 cm | 1 (degenerate) | 0 | 14 ms | 0 mm² |

Twenty triangle clips against the clean `0.6 cm` inset take **8.3 ms**, excluding **11.4 ms** one-time boundary preparation. Their output areas agree with independent Shapely erosion-and-intersection within **0.00003 cm² per triangle** in the tested grid.

An open cubic NURBS with a `0.5 cm` offset self-intersection is simplified to **two parametric intervals in 1.8 ms**. The existing exact enclosing-rectangle clipper returned **zero loops** for the single-ellipse test even where a valid inset region exists; the new direct construction corrects that case.

The *original curved DXF spline*, offset by `0.3 cm`, has **zero self-intersections** (13 ms detection). Consequently this particular cleanup makes no performance difference to that existing 131-shape fixture: with the direct-geometry experimental branch, complete generation remains **2.44× default** and **2.24× Auto Fit** versus the original exact generation path, with the same shape counts and rejection counts.

## Validation

- Existing plus new Python tests: **177 tests, one skipped**; six new offset-loop regressions.
- New tests cover closed ellipse (no crossings, two crossings and full erosion), open cubic NURBS, direct triangle clipping of the cleaned curve, and a simple circle.
- Geometric comparisons use finely sampled parametric contours only for validation, never to author the resulting curves.
- Run: `python -m unittest discover -s tests -q` and `python benchmark_offset_cleanup.py` (Shapely required for independent benchmark comparison).

## Scope limitations

This is an exploratory constrained implementation, not a general offset-arrangement solver. The algorithm detects transverse crossings using adaptive chord isolation; kissing tangencies, touching boundaries, interacting multiple independent source loops, and composite-curve corner joins need additional geometric treatment. Ambiguous intervals raise an error rather than silently accepting invalid clearance. Production Fusion code and `main` remain untouched.
