# Autodesk Marketplace submission package

Publisher: **VapourForge**. Application: **fusion360-isogrid**. Price: **Free**.

## Files

Run `python tools/build_release.py --version 0.8.8` from the project root.

- `dist/fusion360-isogrid-v0.8.8-marketplace.zip`: Autodesk Fusion `.bundle` with `PackageContents.xml`, `Contents/`, Python sources and manifest; used as the desktop-app submission.
- `dist/fusion360-isogrid-v0.8.8-github.zip`: standalone application-only add-in ZIP; the GitHub updater downloads this exact release asset.
- `dist/marketplace-icon-120.png` and `dist/marketplace-icon-512.png`: application/listing icon.
- `dist/SHA256SUMS.txt`: checksums for integrity confirmation.
- `marketplace/LISTING.md`: submission text and screenshot references.

## Local installation check

A Marketplace bundle can be placed in the Autodesk ApplicationPlugins directory used for your account, then Fusion restarted:

- Windows: `%APPDATA%\\Autodesk\\ApplicationPlugins\\fusion360-isogrid.bundle`
- macOS: `~/Library/Application Support/Autodesk/ApplicationPlugins/fusion360-isogrid.bundle`

The bundle includes `Contents/fusion360-isogrid.py` and `Contents/fusion360-isogrid.manifest`; `PackageContents.xml` points to the manifest. The app should appear in Fusion's Scripts and Add-Ins interface.

Open a model with a planar face, run the command, select a face, preview, generate a sketch and cut, then stop/restart the add-in. Check that the Marketplace UI contains a privacy-policy link but no Check for Updates/Install Update controls.

To measure native Fusion startup use `APPLOG_FOR_PERFORMANCE=yes` before launching Fusion. Autodesk's performance log includes `ran script` timing, with a 5 ms recommended target.

## Upload / review

In Autodesk Publisher Center, create or edit the Fusion desktop add-in listing as publisher VapourForge. Enter the listing text, privacy/support URLs, screenshots and icon. Upload the Marketplace ZIP.

Autodesk reviews the submission and creates the final installer for publisher approval. Native Windows/macOS Fusion smoke tests and final Publisher Center submission/approval require an authenticated compatible environment.

## Licensing

The package includes the GPLv3 LICENSE and source files. Confirm Autodesk's applicable Publisher Agreement and any additional metadata requests in Publisher Center before final submission.
