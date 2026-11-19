# Changelog

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
