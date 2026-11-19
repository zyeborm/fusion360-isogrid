# Changelog

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
