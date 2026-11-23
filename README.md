# fusion360-isogrid

A Fusion 360 add-in that cuts an isogrid pattern into a planar face. It previews the result before creating an editable sketch and extrusion cut.

## Quick start

Select a planar face (optionally a sketch profile), set the **Auto Fit** pitch limits, click **Find Fits**, inspect the result, then click **OK**.

## Install

1. Download the ZIP (**Code → Download ZIP**), extract it somewhere permanent, and rename the extracted folder to `fusion360-isogrid`.
2. In Fusion, open **Utilities → Scripts and Add-Ins → Add-Ins**.
3. Choose **+ → Script or add-in from device**, select the extracted folder, then click **Run**.

[Autodesk's guide to installing add-ins from GitHub](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/UsingSamplesFromGitHub_UM.htm).

The add-in works on planar faces, including curved boundaries and existing holes. It creates native Fusion sketch geometry and a cut feature.

For implementation details, see [Advanced notes](ADVANCED.md). For changes between versions, see the [Changelog](CHANGELOG.md).
