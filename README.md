# fusion360-isogrid v0.6.3

**Naming:** The Fusion add-in directory, entry script and manifest all use `fusion360-isogrid`. When upgrading from `IsogridFusion`, close Fusion and remove the old add-in entry/folder before adding this renamed directory. Internal command and attribute identifiers now follow the `fusion360-isogrid` name. Old installations should be removed before installing this renamed add-in.


## Field-level validation

The geometry-sensitive inputs now use **Fusion's native invalid-text state**:
when a rib is too wide, a vertex hole exceeds the rib width, a corner radius
cannot fit, or an input is invalid, the implicated input text becomes red. The
**Geometry warnings** text area below explains the conflict. The two Auto Fit
pitch bounds are checked in the same way. Correcting the value clears the
indicator. Both native Python and optional GEOS geometry backends are retained.

Fusion's unit-aware `ValueCommandInput` API does not expose a programmable
invalid-field indicator independently of blocking OK. To preserve **native
error colouring while keeping OK enabled**, the relevant dimension fields use
Fusion's `StringValueCommandInput.isValueError` property. User-entered units,
arithmetic expressions, and Fusion user/model parameters are evaluated through
Fusion's `UnitsManager`, using millimetres as the default unit for these
fields. Extrusion depth, X/Y offsets and angle remain native value inputs.
The advisory fields therefore use a plain text expression control rather than
the normal Fusion measurement/history dropdown.

Geometry warnings continue to be advisory: OK is not disabled by the add-in.
Fusion independently enforces its own selection and native expression rules.
Autodesk has documented a version-dependent issue where editing a string
field can briefly reset its error colour; the add-in reapplies field states
on `inputChanged` and `validateInputs`, but the actual repaint behaviour
requires an in-Fusion test.

**Validation:** 50 standalone tests, including seven new field-highlight
regressions. Actual Fusion UI colouring needs verification.

---

# Isogrid Fusion v0.6.2

## What's changed

- **Warnings without disabling OK.** The command now has a persistent Geometry warnings field. It warns about rib width relative to cell pitch, oversized vertex holes, infeasible corner radii, non-positive dimensions and geometry that retains sharp corners. Fusion's native numeric unit inputs remain available and editable. The add-in's `validateInputs` callback does not disable OK for cross-field constraints. Fusion still validates malformed numeric expressions and required selections itself.
- **Tight clipped pockets are retained.** If the selected fillet radius cannot fit at a corner introduced by a perimeter or void, the generator retains the pocket and rounds the corners that *can* accommodate the radius. It reports the count of sharp corners left for manual finishing, rather than silently discarding the whole triangle. This is a deliberately conservative fallback; these sharp corners require manual correction before machining with the specified cutter.
- **Trim to boundary / voids** (default **on**). When enabled the engine respects the face, optional sketch-profile boundary, perimeter margin and void clearance. When off, it generates full triangle/circle outlines over the selected area's bounding extent. The sketch retains the full outlines so they can be trimmed manually. Automatic extrusion is still attempted for the profiles that intersect the solid. The underlying solid naturally limits the resulting 3D cut, but raw sketch geometry may cross the face boundary and protected regions.
- **Large vertex holes** are allowed as inputs, with advisories when they approach or exceed rib width. Overlapping cut loops can be challenging for Fusion to convert into a valid extrusion; warnings leave that decision to the user. In trimmed mode, vertex holes that do not fit entirely inside the permitted region are omitted, with an explicit warning if none fit.
- **Auto Fit remains optional.** Candidate scoring always uses the trimmed footprint of the selected face, even if the user has chosen untrimmed output. Both pure Python and optional GEOS backends remain supported.

## Installation

Close Fusion, replace the existing `fusion360-isogrid` add-in directory with the one from this archive, restart Fusion, then run the add-in from Utilities -> Scripts and Add-Ins. Existing optional `vendor/` dependencies can be copied across if used.

## Validation

The unit suite exercises geometry, optional compiled clipping, asynchronous workers, simulated Fusion preview events, raw grid output, geometry advisories and invalid field handling. Run `python -m unittest discover -s tests -v` inside the add-in directory.

The actual Fusion UI and final cut, especially raw outlines intersecting geometry, require verification in Fusion. This environment has no Fusion installation.

---

# Isogrid Fusion v0.6.1

Fusion 360 Python add-in for applying an isogrid as a **finishing cut** on a planar solid face. One sketch and one multi-profile extrusion cut are created. Face holes, optional sketch boundaries, rounded pockets, optional grid-vertex holes, and manual pitch/placement remain supported.

## v0.6.1: disappearing Auto Fit preview

The asynchronous worker could finish and draw custom graphics inside the
background-result custom event. Fusion's next `executePreview` transaction
would then roll back those graphics. The session still held a reference to the
old group, so a completed candidate briefly flashed and disappeared.

Completed geometry now triggers `Command.doExecutePreview()` on Fusion's main
thread. **Only `executePreview` creates the outline custom graphics**, after
Fusion has rolled back the previous preview transaction. Every subsequent
`executePreview` call rebuilds the lightweight graphics from cached outlines,
so older rolled-back groups are never treated as current. Auto Fit, manual
parameters, and final sketch/extrude generation are unchanged.

Three standalone event-order tests cover repeated transaction rollback, the
worker-result-to-preview handoff, and hiding the preview. All 36 standalone
tests pass. Actual Fusion UI execution remains to be validated.

## v0.6: background geometry and responsive preview

The manual workflow, two geometry backends, and optional Auto Fit remain in place.
Geometry runs in **one dedicated Python background thread per command**, rather
than inside Fusion's `inputChanged`/`executePreview` handlers. This also covers
small manual parameter edits, not only Auto Fit.

- **Geometry worker indicator** in the command: grey Idle, amber Working,
  green Ready, or red Error. Auto Fit shows completed/total evaluations in the
  same small status field. There is no modal progress dialog.
- **Latest request wins:** editing parameters during a calculation cancels an
  ongoing Auto Fit at its next progress checkpoint or supersedes a preview.
  Pending obsolete previews are coalesced; their completed results are discarded.
- Fusion `executePreview` collects user inputs, submits computation if needed,
  and draws cached outlines. It does not run the polygon engine, and does not
  use `adsk.doEvents()`.
- Face and sketch boundary sampling are cached on the **Fusion main thread**
  until the selection/tessellation tolerance changes. The worker separately
  caches the prepared 2D margin geometry across pitch, rotation and offset edits.
- Extrusion-depth changes reuse the current 2D pocket geometry. Depth is
  applied to the final Fusion cut, as before.
- Results return to Fusion using Autodesk's `Application.fireCustomEvent`; the
  event handler updates the cache, status and dropdown choices on the main
  Fusion thread, then requests `executePreview` to draw temporary graphics.
  Neither the 2D solver nor its worker touches Fusion B-Rep, sketch,
  command-input, or graphics APIs.
- The final sketch/extrusion remains a main-thread Fusion modelling operation.
  If OK is clicked before a background preview is ready, the operation falls
  back to a synchronous computation to preserve correctness.

### Threading and CPU use

A thread primarily addresses **UI responsiveness**. It does not promise
multi-core acceleration for the pure-Python geometry backend because of
Python's GIL. The optional GEOS backend may spend more work in compiled code.
A future process-based worker can be introduced after actual Fusion testing,
but v0.6 deliberately avoids the deployment complexity and child-process
lifecycle problems of embedded Python multiprocessing.

### Installation and validation

Replace the existing `fusion360-isogrid` folder while Fusion is closed and restart
Fusion. As in v0.5, Shapely/GEOS is optional and can be installed with
`python install_backend.py` before starting Fusion.

Standalone verification:

```shell
python -m unittest discover -s tests -v
```

36 tests pass locally: 27 geometry/optimisation tests, 6 background-worker
tests for preview parity, coalescing, cancellation, progress/fit execution,
error reporting and prepared-region caching, and 3 preview-event lifecycle
tests using a simulated Fusion event sequence.

**Fusion-specific UI/event delivery has not been run in Fusion locally.** The
status is expected to refresh when the main Fusion event loop is available;
short UI pauses can still occur during source-face sampling, custom-graphics
construction and final feature creation. Native in-Fusion integration is the
next validation step.

## Upgrade and installation

1. Close Fusion and replace the contents of the previously installed `fusion360-isogrid` add-in folder with the contents of this release's `fusion360-isogrid/` folder. Restarting Fusion clears any old Python modules/event handlers from memory.
2. In Fusion, open **Utilities → Scripts and Add-Ins → Add-Ins**, select `fusion360-isogrid`, and click **Run**.
3. Open **Solid → Add-Ins → Isogrid finishing pattern** (the command may be in a toolbar overflow menu).

This release has **no mandatory third-party Python packages**. The newly prepared pure-Python backend is functional on its own.

### Optional compiled GEOS backend

The Shapely/NumPy implementation from v0.4 remains available. For optional installation, while Fusion is closed, run `python install_backend.py` from the extracted add-in folder with a system Python installation having `pip`. The installer downloads binary wheels matching Fusion's embedded Python runtime to the add-in-local `vendor/` directory. The installer does not modify Fusion's Python installation.

An add-in setting, **Geometry backend**, now offers:

- **Automatic** (default): GEOS when installed successfully; prepared pure Python otherwise.
- **Pure Python**: always run the dependency-free geometry backend, even with GEOS installed.
- **GEOS accelerated**: explicitly require GEOS; display an error if dependencies are unavailable.

The selected backend applies consistently to manual preview, Auto Fit scoring and final sketch creation. All of those call the same `geometry.make_pockets()` implementation; only the allowed-region preprocessing and clipping backend changes.

## Manual workflow

1. Select a planar solid face. Existing face voids and holes are exclusion regions.
2. Optionally select a coplanar sketch profile to restrict the pattern.
3. Adjust cell pitch, rib width, extrusion depth, perimeter margin, void clearance, corner radius, vertex-hole diameter, minimum partial-pocket area, X/Y offsets and rotation.
4. Optionally choose a grid origin point (vertex or triangle centre) and align the grid to a straight edge.
5. Inspect the cyan outline preview. Accept to create one sketch and one cut extrusion, using the entered depth for every pocket.

The default pocket corner radius remains **1.5 mm**, applied after boundary clipping, including to newly created corners.

## Optional Auto Fit

- Specify minimum/maximum pitch, 120/320/1,000 evaluation effort, and whether to search rotation.
- Click **Find Fits**; the independent differential-evolution searches target maximum removed area, clean edges, symmetry and closeness to nominal pitch.
- Select one of the resulting distinct candidate layouts. It writes its pitch, X/Y offsets and rotation into the existing manual controls. Manual use remains available throughout.
- All scoring uses full 2-D pocket geometry; extrusion depth does not affect the optimiser.

## v0.5 geometry changes

The v0.4 pure-Python fallback rebuilt overlapping perimeter and hole capsules and performed general polygon clipping for **each** boundary-adjacent triangle. This caused redundant calculations across an Auto Fit search.

The v0.5 Python backend now:

1. Samples source boundaries and converts perimeter/void margins into conservative polygonal buffers **once** per search.
2. Computes the resulting permitted planar area through the existing Python polygon Boolean routine **once**.
3. Builds spatial indices for prepared mask segments and scanline indices for containment tests.
4. Rejects excluded triangles or accepts whole triangles through fast classification.
5. Runs local polygon clipping and the **same final-corner rounding** only for triangles intersecting the prepared mask.

The GEOS backend continues to prepare the permitted area and run batched compiled predicates/intersections. Both backends use shared lattice generation, final corner rounding, vertex-hole logic and Fit scoring. The pure-Python backend uses conservative polygonal capsule margins; GEOS uses round buffered margins, so near marginal partial-cell/fillet thresholds, results may differ.

### Matched-workload benchmark (outside Fusion)

20 *identical* candidate layouts for each backend, with 20 mm pitch, 2 mm rib, 2 mm perimeter margin, 2.5 mm void clearance and 1.5 mm fillet. Average **full-layout** time and separate **one-time** preprocessing cost, measured on the local development runtime:

| Test geometry | Python setup | Python per layout | GEOS setup | GEOS per layout |
| --- | ---: | ---: | ---: | ---: |
| 100 × 100 mm rectangle | 4 ms | **6.1 ms** | 1 ms | 4.4 ms |
| Rectangle with a circular void | 167 ms | **14.8 ms** | 1 ms | 5.7 ms |
| Curved/cusp perimeter with 3 voids | 417 ms | **38.5 ms** | 2 ms | 17.5 ms |

For comparison, v0.4's pure-Python fallback was approximately 35.6 ms, 632.9 ms and 3,142 ms per layout on those same *categories* of geometry, but those original benchmark runs used a different, shorter set of candidate offsets and rotations. This is an architectural rather than a controlled single-variable comparison. `benchmarks.py` in **this release** evaluates identical positions for both current backends.

The two current backends agree closely on usual pocket layouts, but their final cut areas may differ more near the minimum-pocket/fillet feasibility thresholds: a pocket may be omitted entirely in one backend when a marginally different buffer makes its requested fillet impossible. In this benchmark the maximum candidate-area deviation was 4.7%; geometric equivalence is **not** claimed. For stable results, keep the same backend when iterating and generating a final feature.

Preparation is reused through an entire Auto Fit search; the resulting CPU-time reduction grows with evaluation count. Fusion's UI/event-loop responsiveness and its current synchronous progress-dialog implementation have **not** been tested or corrected in this release.

## Tests

Run:

```sh
python -m unittest discover -s tests -v
python benchmarks.py
```

27 regression tests pass on the development runtime. These include curved cusp boundaries, sketch masks, buffered voids, clipped-corner fillets, fit optimisation, and equivalence between the prepared Python output and the previous Python clipping routine on matching polygons.

The Fusion UI, actual extrusion generation, and the optional CPython wheel installer still require testing inside Fusion. Current geometry is **planar only**. The sketch/cut output is a finishing feature rather than a live custom-feature type in the timeline. The known UI repaint issue during progress-dialog updates remains outside this geometry refactor.

## Source files

- `fusion360-isogrid.py`: Fusion command UI, preview, and final single cut; backend dropdown.
- `geometry.py`: shared full pocket generator and dependency-free prepared-region clipping.
- `geometry_compiled.py`: optional compiled Shapely/GEOS clipping.
- `fitting.py`: bounded deterministic differential evolution, four objectives.
- `install_backend.py`: optional wheel downloader.
- `benchmarks.py`: matched-workload backend benchmark.
- `tests/`: geometry and optimisation regression tests.
