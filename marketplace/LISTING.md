# Autodesk Design and Make Marketplace — listing copy

**App title:** fusion360-isogrid  
**Publisher:** VapourForge  
**Type:** Desktop add-in for Autodesk Fusion  
**Price:** Free  
**Operating systems:** Windows and macOS  
**Version:** 0.8.8 (update when releasing)  
**Language:** English  
**Support:** https://github.com/zyeborm/fusion360-isogrid/issues  
**Source and license:** https://github.com/zyeborm/fusion360-isogrid — GPL-3.0  
**Privacy:** https://github.com/zyeborm/fusion360-isogrid/blob/main/PRIVACY.md

## Short description

Create editable isogrid pockets on planar Fusion faces, with automatic pitch and placement fitting.

## Full description

fusion360-isogrid creates triangular isogrid pocket patterns directly in Autodesk Fusion. Choose a planar solid face, set rib width, pitch limits, edge clearance and cut depth, then use Auto Fit to explore candidate layouts. Preview the contours before committing to a native Fusion sketch and extrusion cut.

The add-in supports planar faces with curved boundaries and existing holes. Optional features include rounded pocket corners, vertex holes, rotation, sketch-profile boundaries, saved parameter presets, machining-access warnings and estimated material savings.

Results remain editable Fusion geometry. Calculations run locally in Fusion; the Marketplace edition includes no update checker, telemetry or external service dependency.

**Workflow:** Select a planar face → set cell pitch or Auto Fit range → Find Fits → inspect a candidate → confirm the cut.

**Limitations:** The pattern is generated on planar faces. Manufacturing and mass figures are estimates rather than structural certification. The add-in does not conduct finite-element analysis.

## Images for the listing

1. **Primary/hero:** `images/isogrid-result.png` — completed curved-panel isogrid cut.
2. `images/select-face.webp` — target-face selection and preview.
3. `images/auto-fit.webp` — fit range and candidates.
4. `images/status.png` — geometry/volume/mass status.
5. `images/launch-addin.webp` — Fusion launch menu.
6. `images/install-addin.webp` — manual installation reference.

All images are in the repository. The generated `dist/marketplace-icon-120.png` (120 × 120) and `dist/marketplace-icon-512.png` (512 × 512) are the listing icon assets.

## Support and privacy

Support and issue reports: https://github.com/zyeborm/fusion360-isogrid/issues

Privacy policy: https://github.com/zyeborm/fusion360-isogrid/blob/main/PRIVACY.md

The app runs locally and has no telemetry. User-created presets stay on the user's machine. The Autodesk Marketplace edition contains no built-in updater.
