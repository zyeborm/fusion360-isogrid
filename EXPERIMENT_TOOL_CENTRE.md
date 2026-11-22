# Direct tool-centre construction — geometry experiment

Branch: experiment/tool-centre-geometry, based on experiment/offset-loop-cleanup. Experimental only: Fusion sketch/export and production make_pockets() are unchanged.

## Algorithm

Let B be the source plate, T one sharp lattice triangle, p the perimeter clearance and r the specified corner radius.

    C = (T eroded by disk(r)) intersect (B eroded by disk(p+r))
    Final pocket = C dilated by disk(r)

Different outer and hole clearances are applied independently. The construction uses one shared offset boundary, analytically inset triangle edges, direct line/curve intersections, preserved parametric curve intervals, and an outward sweep generating native lines, circles and offset curves. Convex joins become radius-r circular arcs; concave joins are trimmed at local offset-support intersections. The previous secondary filleting and disk-opening Boolean repair are absent from this path.

Small numerical spline-area integrals are replaced with bounded chord-area estimates **for orientation and minimum-area filtering only**. The geometry output itself remains parametric. Composite input containing ordinary polygon loops is supported by converting those edges to exact lines once.

## Benchmark

Whole-pattern Python timing, medians of two alternating runs per method, clearing spline area/distance/flatten caches. Includes shared boundary preparation, all clipping, corner construction, filtering, outline sampling and circular vertex holes.

| Curved fixture | Existing | Tool-centre | Speedup |
|---|---:|---:|---:|
| 20 mm default pitch | 3.877 s | 0.526 s | **7.37x** |
| 19.28114 mm Auto Fit | 4.981 s | 0.475 s | **10.49x** |

Baseline 449,501 NURBS de Boor evaluations on the default fixture; direct construction 48,795.

Default: 131 baseline shapes, 132 with the new algorithm. The extra cut has a valid tool-centre region and was rejected by the previous corner-repair heuristic. All common shapes agree within 0.000015 mm² sampled difference.

Auto Fit: 131 shapes from both generators. One near a protected hole changes from 0.3813 cm² (previous) to 0.2715 cm² (new). Independent erosion/intersection/dilation predicts approximately 0.2716 cm². Its centre region separates into two feasible islands; the experimental output preserves both.

## Validation and scope

Python suite: 184 tests, one skipped. New regressions cover analytic triangle erosion, concave joins, circular voids, ellipse self-intersection cleanup, polygons without native curves, two-island pockets and non-use of old corner-repair functions. Run python benchmark_tool_center.py; run python -m unittest discover -s tests -q. Shapely is used only for independent geometric validation.

**Remaining topology work:** expanded tool-centre islands can overlap and need local parametric union; certain coincident tangencies and deeply concave spline/spline joins need more coverage. The experiment counts unsupported cases rather than silently reducing the radius or running the old repair Boolean. No live Fusion measurements have been made.
