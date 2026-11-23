# fusion360-isogrid

A Fusion 360 add-in that cuts an isogrid pattern into a planar face. It previews the result before creating an editable sketch and extrusion cut.

## Quick start

1. Open **Solid → Add-Ins → fusion360-isogrid**.
2. Select a **Target face**. Optionally select a sketch profile under **Optional sketch boundary** to limit the patterned area.
3. Set **Auto Fit minimum pitch** and **Auto Fit maximum pitch** to a sensible range for the part.
4. Click **Find Fits**. Inspect the preview and try the suggested **Auto Fit candidates**.
5. Adjust **Rib width**, **Extrusion depth**, or any other settings you care about, then click **OK**.

You can also place the grid manually using pitch, offsets and rotation. The default settings are a starting point.

## Install

1. Download the repository ZIP (via **Code → Download ZIP**) or clone it.
2. In Fusion, open **Utilities → Scripts and Add-Ins → Add-Ins**.
3. Click **+**, select the `fusion360-isogrid` folder and click **Run**.

The add-in works on planar faces, including curved boundaries and existing holes. It creates native Fusion sketch geometry and a cut feature.

For implementation details, see [Advanced notes](ADVANCED.md). For changes between versions, see the [Changelog](CHANGELOG.md).
