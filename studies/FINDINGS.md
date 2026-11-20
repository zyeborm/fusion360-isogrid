# Integer-like geometry-fit study (v0.7.5)

The objective is to avoid systematic rows of truncated triangular pockets while preserving user choice of pitch/scale, including on irregular or curved planar faces. All numbers here are **geometric**; no strength or stability claims are made.

## Method

- Six synthetic planar models with dimensions from 40 mm to 1,000 mm.
- 160 deterministic layout evaluations per algorithm, same pitch limits and fixed rotation (orientation may be enabled by the user in Fusion).
- Four comparisons per model: nominal/manual pitch, previous v0.7.4 **Clean edges** search, v0.7.5 **Maximum removal**, and v0.7.5 highest-ranked **Integer fit** candidate.
- Use the actual rounded, clipped pocket outlines (line/arc analytic area), with holes and perimeter clearance. Partial cells are identified against the full rounded pocket area.
- Teal = complete pocket; orange = partial pocket. See generated `isogrid_integer_fit_comparison.png` and `isogrid_integer_fit_metrics.csv` in the study output directory.

## Results (partial pockets)

| Geometry | Manual pitch | New integer fit | Previous Clean edges | Maximum removal |
|---|---:|---:|---:|---:|
| 120 × 40 mm strip | 10 | 2 | 2 | 5 |
| 40 × 22 mm plate | 10 | 4 | 4 | 8 |
| 1,000 × 450 mm plate | 14 | 6 | 8 | 12 |
| L-plate 160 × 110 mm | 21 | 8 | 8 | 14 |
| Tapered plate 180 × 100 mm | 21 | 7 | 10 | 10 |
| Arc-notch plate with circular hole | 31 | 10 | 32 | 21 |

The count is a useful visual diagnostic but **not** the exact optimisation objective: the quality score also incorporates retained partial area, long straight runs and relative scale. Note that different pitches can change the total cell count substantially.

## Visual assessment and limitations

- The 120 × 40 mm strip demonstrates the motivating failure. The 50 mm nominal layout leaves systematic truncated rows; a roughly 43 mm fit produces two edge partials.
- The tapered and arc-notch cases particularly benefit from searching pitch/phase jointly. The latter drops from 31 partials at nominal pitch to 10 at approximately 44.7 mm.
- The 40 mm and L-shaped examples are **as good as**, rather than decisively better than, the previous Clean Edges search. The previous algorithm remains a useful comparison baseline.
- The 1 m example selects a different pattern scale from the previous algorithm. The new result has fewer partials, but the prior solution scores slightly higher under the new scale-normalised metric. The result selector intentionally exposes multiple alternatives so the user can judge that trade-off.
- The score is a *heuristic*. Irregular shapes may retain unavoidable partial cells, and omitted tiny pockets can affect apparent quality. More test data from real Fusion designs will be valuable.
- Scoring is performed in pure Python on exact line/arc geometry where available. The Fusion UI and final CAD feature still require in-application verification.

## Reproducing

Run from the repository root with Matplotlib and Pillow available:

```sh
python studies/run_case_study.py /tmp/isogrid-fit-study 160
```

Individual cases run in isolated processes to avoid Matplotlib/native-extension state affecting unrelated runs. The add-in has no Matplotlib/Pillow dependency.
