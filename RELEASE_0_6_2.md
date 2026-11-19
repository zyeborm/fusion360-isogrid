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
