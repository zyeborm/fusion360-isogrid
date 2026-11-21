# Changelog

## 0.8.6 — One native spline per trimmed offset section

- Export the existing tangent-matched cubic approximation of each continuous
  offset section as a single cubic NURBS with multiple knot spans, instead of
  one independent Fusion sketch spline for every cubic span.
- Preserve the exact same cubic controls, source parameter intervals and
  approximation tolerance (1e-4 cm). No geometry, clipping, layout, fillet
  or pocket-selection rules are changed.
- On the supplied curved test fixture, reduce native offset spline entities
  from 130 to 15 while preserving all 131 generated cut shapes.
- Verify the combined NURBS against the individual cubic spans at sampled
  parameters, test join derivative continuity, and check sketch-space export.
- Native Fusion and downstream CAM interpretation require an in-app test.

## 0.8.5 — Correct native boundary splines and accelerate repeated redraws

- Convert NURBS, elliptical-arc and offset-cubic control points from the
  component model frame to the sketch's local frame before passing them to
  Fusion's SketchFixedSplines API. Lines and arcs already used this transform;
  mixed coordinate systems distorted boundary-adjacent pockets and prevented
  their Fusion sketch profiles from closing.
- Cache world-space preview line coordinates against the immutable accepted
  shape list. Repeat executePreview events can recreate Fusion custom graphics
  without repeating ~12,000 vertex transforms for unchanged geometry.
- Regression-test curve exports on an offset and rotated sketch frame and
  verify repeated preview redraws reuse the generated coordinate array.
- The exact clipping/generation path and requested pocket dimensions remain
  unchanged. In-Fusion results require a live application test.

## 0.8.4 — Restore partial cuts, reject impossible fillets and correct preview advisories

- Recover missing Fusion native sketch-curve tags by matching each Fusion
  profile's interior point against the exact generated curves rather than
  polygonal preview tessellation. The source ownership remains the primary
  identity for normal profiles.
- If Fusion fails to recognise an individual source contour, cut the valid
  recognised profiles and explicitly report the missing count and contour IDs;
  avoid cancelling the entire feature because of one unrecognised loop.
- Reject clipped cut islands that cannot honour the requested corner radius
  after tangent fillet and full-radius opening attempts. These shapes are
  omitted consistently from both preview and final cut, with a warning count.
  This check applies independently of cutter diameter (0 keeps tool tests off).
- Use a 0.03 mm sampled-contour tolerance for minimum-web diagnostics to
  avoid false violation warnings caused by independently approximated spline
  boundaries. Continue to flag materially undersized webs.
- Extend regression tests for tagless Fusion profiles, impossible fillets,
  false-positive clearance warnings, and preview/cut consistency.

## 0.8.3 — Preserve all generated profiles in the extrusion cut

- Select cut profiles from the sketch curves that define each Fusion outer
  ProfileLoop. The previous selection relied on a sample point tested against
  the generated outline's tessellation, silently omitting some valid pockets.
- Tag each generated native sketch curve with its source pocket and loop. Read
  the tag back through ProfileCurve.sketchEntity; Autodesk entity token strings
  are not safe to compare directly as persistent identity keys.
- Require every expected positive pocket contour to be represented by at least
  one selectable Fusion profile. A missing/open/merged profile now reports the
  affected source-loop indexes instead of silently performing a partial cut.
- Keep negative loops (protected islands) excluded and preserve the previous
  untrimmed-mode rule for entirely exterior pockets.
- Test native profile matching, void exclusion, missing/merged contours and a
  complete simulated sketch-to-extrusion path.

## 0.8.2 — Fix Fusion preset group creation

- Keep the nested preset field-selection group expanded, as required by the Fusion API
  when it is nested without an enable checkbox. The parent Parameter presets
  group remains collapsible and initially closed.
- Add a regression test simulating the API restriction during command construction.

## 0.8.1 — Authoritative geometry dimensions, diagnostic-only cutter setting

- Retire redundant material thickness, minimum skin, minimum web and minimum
  pocket diameter inputs. Existing rib, perimeter and void clearance values
  remain independently authoritative, as does the existing minimum retained
  cell area percentage.
- Cutter diameter defaults to 0 (off); positive values report potential
  unmachinable corner radii and sampled inaccessible pockets without changing
  geometry or removing cuts. Native junction holes can be drilled separately.
- Non-destructive sampled material-web checks compare pockets against the
  actual specified rib, perimeter and void clearances; highlight violations.
- Preserve legacy sparse preset names/fields while discarding only the four
  retired setting keys when reading v0.8.0 saved presets.
- Retain native Fusion sketch and cut output, with no managed-edit feature.

## 0.8.0 — Optional manufacturability controls and sparse presets

- Integrate cutter diameter, minimum material web, minimum usable pocket
  diameter, assumed uniform material thickness and minimum remaining skin
  directly into the existing pattern dialog; zero disables each constraint.
- Use the effective minimum web for nominal ribs, outer margins and cutout
  clearances; use the specified milling cutter radius for pocket fillets.
- Suppress unusably small or sharp-cornered pockets when manufacturing limits
  are specified; screen final sampled contours for minimum-web violations and
  highlight offending shapes in red during the existing preview lifecycle.
- Keep vertex holes independent of pocket cutter dimensions and retain the
  same native Fusion sketch and extrusion-cut output.
- Add named sparse parameter presets, storing only explicitly included fields
  as editable expressions / choices in an atomic per-user JSON file. Apply
  selected values without touching excluded parameters or source selections.
- Add command-event, preset persistence, clearance-screening and minimum-skin
  validation tests. Retain compatibility with v0.7.x default settings.

## 0.7.8 — Fast approximate layout search (development build)

- Replace one full exact-clipping/fillet run per Auto Fit candidate with a single
  polygonal, margin-aware raster preprocessing pass and constant-time samples.
- Keep existing integer-fit quality measures, including partial-row penalties,
  and retain the maximum-removal candidate as a distinct alternative.
- Generate exact geometry only for the selected layout during preview/cut.
- Use an analytic NURBS derivative as fallback for numerically microscopic
  curve trims, preventing failed layouts with coincident secant samples.
- Show fit area as an estimate until the exact preview is available.
- Reload fast_fit module with the other geometry modules in Fusion.
- Add tests verifying 1,000 trials skip make_pockets entirely.


## 0.7.7 — Curved boundary preview reliability and performance

- Fixed the native curved-face preview's corner-repair failure by using the
  clipper's existing closure tolerance when re-wrapping numerical contours.
- Reduced repeated NURBS point evaluations by caching homogeneous control
  points, using fixed-width de Boor interpolation, projecting onto cached
  adaptive chords for nearest-point searches, and reusing minimisation values.
- Reproduced the supplied curved DXF with Fusion's actual default pattern
  settings: 137 cut shapes including 36 vertex holes.
- Added regression coverage for the complete worker-to-custom-graphics preview
  handoff (against a Fusion API shim) and for the short-offset repair contour.
- Reload all geometry modules consistently on add-in restart so installed
  updates cannot retain an old curves2d module in Fusion's Python runtime.
- Retain worker-stage timing diagnostics and avoid synchronous geometry
  recalculation when OK is pressed before the preview finishes.


## 0.7.6 — General planar curve support

- Extended the input adapter to preserve Fusion ellipses, elliptical arcs,
  NURBS/controlled splines, conics exposed as NURBS, and polylines.
- Added numerical intersections and clearance offsets for parametric curves,
  while retaining the existing analytic line/circle path.
- Generated native ellipses and rational NURBS sketch entities for general
  curves; general offsets are emitted as tangent-matched cubic splines.
- Added mixed-curve clipping and native-sketch API-mock regression tests.


## 0.7.5 — Multi-start integer-like geometric fitting

- Retained differential evolution, but repurposed three of four passes to find clean fits across different parts of the allowed pitch range; kept maximum removal as a distinct objective.
- Added per-triangle retained-area penalties and connected-run detection to discourage entire strips of truncated pockets, including on irregular boundaries.
- Normalised boundary penalties by physical perimeter/pitch to work across different part sizes without coarse/medium/fine categories.
- Made the best geometric fit the first, automatically selected result; maximum removal is selectable separately.
- Added six geometry visual comparisons against the previous optimiser and regression tests for scale invariance, partial strips and deterministic alternatives.

## 0.7.4 — Manual update check

- Added an always-visible **Check for Updates** button in the Fusion command.
- Manual checks bypass the 30-minute automatic cache and display **Checking**, **Up to date**, **Update available**, or a failure message. An in-progress automatic request is reused to avoid duplicate downloads.
- Retained the automatic check on command open and one-click **Install Update**.

## 0.7.3 — Preserve rib-width web around vertex holes

- Corrected **Auto Max Hole** to reserve an edge-to-edge web equal to the rib width, rather than using the pocket-contact diameter. For feasible 60° pocket fillets, `D_auto = 2 × corner radius`.
- Distinguished insufficient-web warnings from zero-clearance tangency and actual overlapping cuts. Warnings remain advisory and leave OK enabled.
- Changed the default hole diameter to 3 mm, matching the 2 mm rib / 1.5 mm fillet defaults.
- Added regression tests for radial web thickness, diameter calculation and button behaviour.

## 0.7.2 — Vertex-hole default and Auto Max Hole

- Default vertex hole diameter is now 5 mm (previously disabled by default).
- Added a one-shot **Auto Max Hole** button immediately after the diameter field. It sets the theoretical limit `2 × (rib width + corner radius)` using the current expressions and document units.
- Manual hole diameter edits remain independent after using Auto; preview and geometric advisories update immediately.

## 0.7.1 — Full-radius fillet repair

- Added an analytic erosion/dilation repair for clipped pockets whose tangent fillets collide along short edges. Narrow tips are removed while the requested cutter radius remains unchanged.
- Reproduced and resolved all six fillet warnings on the supplied rounded-cutout DXF test shape at 20 mm pitch, 2 mm ribs, 3 mm margins and 1.5 mm radius.
- Added the original line/major-arc/circle geometry as a standard-library regression fixture, checking exact radii, tangent continuity, closed contours and full-pattern output.
- Truly infeasible pockets still report advisory warnings; they remain available for manual review.

## 0.7.0 — Exact line/arc planar geometry

- Native lines and circular arcs from Fusion face and sketch boundaries are preserved as exact 2D curves.
- Added a pure-Python arrangement clipper using analytic line/line, line/arc and arc/arc intersections, exact circular clearances, and analytic containment tests.
- Rounded clipped pockets use tangent circular arcs, including line-to-arc and arc-to-arc joins; Fusion output creates native sketch arcs and circles.
- Auto Fit uses analytical sector/line area and centroid calculations for exact-curve output; polygon samples are for preview and unsupported input types.
- Supports full-circle hole contours and offsets across collapsed inner radii.
- Complex input curves such as ellipses and splines continue to be accepted through sampling until their analytic operations are implemented.

## 0.6.8 — Native sketch arcs for pocket fillets

- Pocket fillets are represented as exact circular arcs and tangent lines, and only sampled as polygons for 2D clipping, scoring and preview.
- The generated Fusion sketch uses native SketchArc entities rather than short line segments for corner fillets.
- Source-face boundary offsets are still polygonal for clipping, so certain tight intersections beside curved cutouts can still produce unrounded junctions.

## 0.6.7
- Show the running add-in version in the Fusion command title.
- Show both running and available/installed versions in update notices, including the restart-required state.
- Compare updates against the running code version rather than a manifest that may already have been replaced on disk.

## 0.6.6
- Added one-click update installation with staged files, rollback and restart notice.
- Geometric warnings now keep OK enabled, with input tooltips and warning details.
- Vertex-hole clearance is based on rib width and pocket-corner radius.
- Prevented the disabled native backend from reloading on startup.

## 0.6.5
- Disabled the accelerated GEOS backend and removed its selector from the Fusion command to avoid native-library crashes. The optional backend implementation is retained in source for potential future use.

## 0.6.4
- Added a non-blocking update-available notice when the Fusion command opens, linking to GitHub. Installation remains manual.

## 0.6.3
- Added native invalid-field appearance and advisory geometry warnings.
- Renamed the project to `fusion360-isogrid`.

## 0.6.2
- Added optional trimming and improved pocket preservation at tight clipped corners.

## 0.6.1
- Corrected the preview graphics lifecycle after Auto Fit selection.

## 0.6.0
- Added background preview and Auto Fit processing and working/ready status.

## 0.5.0
- Introduced prepared-region pure-Python clipping and explicit backend selection.

## 0.4.0
- Added the optional compiled GEOS backend.

## 0.3.0
- Added Auto Fit, selectable fit candidates, origin and alignment controls.

## 0.2.0
- Improved cusp handling; added vertex holes and default rounded corners.

## 0.1.0
- Initial planar isogrid finishing feature.
