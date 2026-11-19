# Changelog

Key changes by release. [Getting started](README.md) · [Technical notes](ADVANCED.md)

## 0.6.4 — Update availability notice

- Check GitHub's published manifest when the Fusion command opens.
- Show a clickable update notice for newer versions; installation remains manual.
- Run the check asynchronously, caching results and ignoring network failures.

## 0.6.3 — Field-level warnings

- Geometry-sensitive text fields use Fusion's native invalid-input appearance.
- Advisory warnings explain excessive rib widths, vertex-hole diameters, infeasible radii and pitch-range conflicts.
- Correcting the value clears the error state; geometric warnings leave OK enabled.
- Adopted `fusion360-isogrid` naming for the add-in and project.

## 0.6.2 — Optional trimming and safer clipping

- Added **Trim to boundary / voids**, enabled by default.
- Retain pockets when a clipped corner cannot accommodate the requested radius; report unrounded corners.
- Warn about overlapping or infeasible vertex holes and other questionable dimensions.
- Keep Auto Fit independent of the trimming toggle for scoring.

## 0.6.1 — Preview lifecycle

- Rebuilt temporary preview graphics from cached geometry inside Fusion's `executePreview` event, addressing disappearing Auto Fit previews.

## 0.6.0 — Background geometry worker

- Moved preview calculations and Auto Fit off Fusion's command-event handler.
- Added working/ready/error status, fit progress and latest-request-wins cancellation.
- Cached prepared boundaries and returned results through Fusion custom events.

## 0.5.0 — Prepared pure-Python geometry

- Improved boundary preprocessing, spatial filtering and clipping performance.
- Kept both pure-Python and optional GEOS backends selectable.

## 0.4.0 — Compiled geometry backend

- Added an optional GEOS/Shapely clipping path, batch operations and a dependency installer.
- Reused prepared region geometry across Auto Fit evaluations.

## 0.3.0 — Auto Fit and placement

- Added bounded differential-evolution Auto Fit with multiple objectives and selectable candidate layouts.
- Added origin and alignment controls.
- Applied rounded corners to clipped pocket outlines.

## 0.2.0 — Robust boundaries and vertex holes

- Improved handling for cusps and collapsing boundary margins.
- Added optional holes at lattice junctions.
- Added a non-zero default pocket corner radius.

## 0.1.0 — Initial add-in

- Planar face/sketch region input, triangular pockets, manual placement, preview and one multi-profile extrusion cut.
