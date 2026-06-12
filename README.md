# Align Features to Path

**QGIS Plugin — v10.2.0**

A QGIS plugin that snaps and aligns polygon or line features to a hand-drawn alignment path, with five alignment methods including **true curve tracing** and **Smart Fit** — analogous to ArcGIS Pro's *Align Features* and *Trace* tools.

- **Author:** Mustafa Nehad Elghazaly
- **Email:** mostafanehad188@gmail.com
- **Repository:** https://github.com/mustafanehad188/align-features-to-path
- **QGIS:** 3.28 – 4.x

---

## Methods

| Method | Description |
|---|---|
| **Fit to Path** | Moves all ring vertices within tolerance to the nearest point on the path. |
| **Smart Fit** | Like Fit to Path but with intersection-significance filtering and proximity-weighted vertex movement. Skips features that only clip a corner of the buffer (L-corner pulls, crossing lines). |
| **Preserve Shape** | Only snaps vertices that already lie inside the tolerance buffer; outside vertices are kept exactly. |
| **Snap Ends Only** | Snaps only the first and last vertex of each ring. Useful for line features. |
| **Trace & Smooth** | Replaces boundary edges inside the tolerance buffer with the actual path curve. Optional Chaikin smoothing on outside corners. Optional pre-densification. |

---

## What's New in v10.2.0 — Smart Fit

- **Intersection-significance pre-filter:** Features that only clip a corner of the buffer (L-corner pulls, crossing lines) are automatically skipped based on a configurable overlap-ratio threshold.
- **Proximity-weighted vertex movement:** Vertices close to the path snap almost fully; distant vertices move gently (quadratic falloff), eliminating aggressive global pull.
- **UI:** New "Smart Fit" method card in the panel; Advanced section gains a *Smart Fit Options* group (Min. Overlap % spinner + Proximity-weighted checkbox), visible only in Smart Fit mode.
- All previous methods unchanged — fully backward compatible.

---

## Key Features

- **Global Master Boundary Alignment** (v10): all near-path vertices across every affected polygon are forced to the exact same master path coordinates — bitwise-identical shared boundaries, zero gaps or slivers.
- **Full QGIS 4 compatibility** (v10.1): all Qt/QGIS enums fully scoped for PyQt6.
- **True curve tracing:** path geometry with CircularString/CompoundCurve is densified proportionally before tracing.
- **Trace Mode** drawing tool: follow existing feature edges automatically (like ArcGIS Pro's Trace segment construction).
- **Live preview** rubber band before committing changes.
- **5-level undo** via QGIS edit buffer.

---

## Installation

### From ZIP (manual)
1. Download the latest release ZIP from the [Releases](https://github.com/mustafanehad188/align-features-to-path/releases) page.
2. In QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**.
3. Select the downloaded ZIP and click **Install Plugin**.

### From folder
Copy the `align_features_to_path` folder into your QGIS plugins directory:

| OS | Path |
|---|---|
| Windows | `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\` |
| macOS | `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/` |
| Linux | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/` |

Then enable it in **Plugins → Manage and Install Plugins**.

---

## Usage

1. Open the panel via **Vector → Align Features to Path → Align Features to Path**.
2. **Draw the alignment path** — left-click to add vertices, double-click to finish. Press **⤷ Trace** (or `T`) to follow existing feature edges automatically.
3. Choose the **layer** to align and set the **tolerance** (search distance from path).
4. Pick a **method**. For curved roads / cadastral boundaries use **Trace & Smooth**. For complex parcels with crossing neighbours use **Smart Fit**.
5. Set **Side** (Both / Left / Right) and **End style** (Round / Square) as needed.
6. Click **👁 Preview** to see a yellow overlay, then **▶ Align** to apply. Use Ctrl+Z or **↩ Undo** to revert.

---

## Changelog

### v10.2.0
Smart Fit mode. New `METHOD_SMART_FIT` with intersection-significance pre-filter and proximity-weighted vertex movement. UI updated with Smart Fit Options panel.

### v10.1.8
Buffer distance fix — tolerance value now correctly acts as hard containment boundary matching ArcGIS Pro behaviour.

### v10.1.7
Coherent Fit to Path gap-closing fix via densification + master-path projection.

### v10.1.1
QGIS 4 loading fixes — fully scoped Qt/QGIS enums for PyQt6.

### v10.1.0
QGIS 4 compatibility groundwork — buffer style resolution, curve shims, `QgsMessageLog` guards.

### v10.0.0
Global Master Boundary Alignment — deterministic master-path snap with two-tier vertex pinning.

### v9.x
Hardened shared-boundary alignment, spatial hash merge, deterministic trace direction.

### v8.0.0
True path tracing, Trace Mode button, arc/curve-aware densification, Chaikin smoothing.

---

## License

GNU General Public License v2 or later — see [LICENSE](LICENSE) for details.

---

## Issues & Contributions

Please open issues or pull requests on [GitHub](https://github.com/mustafanehad188/align-features-to-path).
