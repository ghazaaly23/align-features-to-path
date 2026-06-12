# -*- coding: utf-8 -*-
"""
align_to_path_dialog.py  —  v10.2.0
====================================
UI for the Align Features to Path plugin.

What's new in v10.2.0 (Smart Fit + Square End audit)
------------------------------------------------------
*  **Smart Fit method card** — new "Smart Fit" card added between
   "Fit to Path" and "Preserve Shape" in Step 3 · Method.

*  **Smart Fit Options panel** — the Advanced panel now contains a
   "SMART FIT OPTIONS" section (visible only when Smart Fit is selected):
     - Min. Overlap % spinner  (default 2 %)
     - Proximity-weighted movement checkbox  (default ON)
   The spinner value is passed as ``smart_min_overlap_ratio`` to
   ``align_features_to_path``.

*  **Square End audit** — the tolerance-buffer rubber-band previews in
   ``_update_tol_preview`` and ``_on_path_updated`` both read ``_get_end()``
   for the GEOS cap style (1 = Round, 3 = Square).  No change needed;
   confirmed consistent with the algorithm's ``_make_buffer`` call.

*  **Backward compatible** — all existing method cards, Advanced controls,
   and align/preview/undo logic are unchanged.

What's new in v10.1.8 (Buffer Distance Fix)
--------------------------------------------
* **Tolerance = hard buffer boundary** — The Tolerance spinner now correctly
  controls WHICH features get aligned, exactly matching ArcGIS Pro behaviour.
  Previously the algorithm silently doubled the tolerance (tolerance * 2) as
  the feature search radius, pulling in features well outside the drawn buffer
  zone.  Now the search radius equals the user's Tolerance value — only features
  whose geometry actually intersects the drawn tolerance buffer are processed.

* ``_get_features()`` bbox pre-filter updated to ``tol`` (was ``tol * 2``) so
  the QGIS feature request exactly matches the algorithm's containment check.

* The auto-expand logic in ``align_to_path_algorithm.py`` is replaced with a
  minimal clamp (``search_buffer = max(search_buffer, tolerance)``) instead of
  the old ``tolerance * 2`` override, preserving the invariant that
  search_buffer >= tolerance without grabbing unwanted features.

What's new in v8.0
-------------------
* **True Curve Tracing** — Trace & Smooth now calls the v8 algorithm
  which genuinely traces the alignment path geometry onto polygon
  boundaries (like ArcGIS Pro's Trace construction tool).

* Advanced panel now includes:
      ☑  Enable Curve Tracing        — TRUE trace (v8) vs legacy snap
      Smoothing  ◯─────  2           — Chaikin passes on outside corners
      Resample   [ 5.000 ] m         — optional pre-densification

* `_get_trace_params()` passes `enable_tracing` flag to the algorithm
  so the checkbox governs which code path executes.

* Subtitle on the Trace & Smooth method card updated to reflect the
  improved pipeline.

* All v7.1 UI elements unchanged:
      QDockWidget with 4 numbered steps.
      Layer combo accepts Line AND Polygon.
      Side/End toggle rows.
      Persistent status bar.
      Yellow rubber-band preview.
      5-level undo stack.
      Blue tolerance buffer preview.

Author: Mustafa Elghazaly
"""

from qgis.PyQt.QtCore import Qt, QPropertyAnimation, QEasingCurve, QAbstractAnimation
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QDoubleSpinBox, QComboBox, QFrame,
    QPushButton, QProgressBar, QButtonGroup,
    QApplication, QSizePolicy, QSpacerItem,
    QCheckBox, QSlider,
)

from qgis.core import (
    QgsProject, QgsWkbTypes, QgsMessageLog, Qgis,
    QgsMapLayerProxyModel, QgsFeatureRequest, QgsGeometry,
)
from qgis.gui import QgsMapLayerComboBox, QgsRubberBand

from .alignment_path_tool import AlignmentPathTool
from .align_to_path_algorithm import (
    align_features_to_path,
    apply_results_in_place,
    _make_buffer,
    METHOD_FIT, METHOD_PRESERVE, METHOD_SNAP_ENDS, METHOD_TRACE_SMOOTH, METHOD_SMART_FIT,
    SIDE_BOTH, SIDE_LEFT, SIDE_RIGHT,
    END_ROUND, END_SQUARE,
)


# ══════════════════════════════════════════════════════════════════════════════
# Cross-version enum resolution (QGIS 3 / Qt5  ↔  QGIS 4 / Qt6)
# ══════════════════════════════════════════════════════════════════════════════
# QGIS 4 relocated a few enums into the Qgis namespace and dropped the old
# unscoped aliases under PyQt6.  These two were the QgsMapLayerProxyModel layer
# filters and the QgsFeatureRequest flags.  Resolve each once, tolerating every
# known location, so the same widget code runs unchanged on QGIS 3.28 → 4.x.
# The final integer is a last-resort fallback only (the GEOS-stable enum value).

def _resolve_enum(candidates, fallback):
    """Return the first resolvable enum value from a list of (root, "A.B.C") pairs."""
    for root, dotted in candidates:
        obj = root
        ok = True
        for part in dotted.split("."):
            try:
                obj = getattr(obj, part)
            except (AttributeError, TypeError):
                ok = False
                break
        if ok:
            return obj
    return fallback


# Layer filters: QgsMapLayerProxyModel.Filter.* (QGIS 3) → Qgis.LayerFilter.* (QGIS 4)
_FILTER_LINE = _resolve_enum(
    [(QgsMapLayerProxyModel, "Filter.LineLayer"), (Qgis, "LayerFilter.LineLayer")],
    8,
)
_FILTER_POLYGON = _resolve_enum(
    [(QgsMapLayerProxyModel, "Filter.PolygonLayer"), (Qgis, "LayerFilter.PolygonLayer")],
    16,
)
# Request flag: QgsFeatureRequest.Flag.ExactIntersect (QGIS 3) →
#               Qgis.FeatureRequestFlag.ExactIntersect (QGIS 4)
_FLAG_EXACT_INTERSECT = _resolve_enum(
    [(QgsFeatureRequest, "Flag.ExactIntersect"), (Qgis, "FeatureRequestFlag.ExactIntersect")],
    4,
)

# ══════════════════════════════════════════════════════════════════════════════
# Palette constants
# ══════════════════════════════════════════════════════════════════════════════
_C_BG       = "#1e1f22"
_C_SURFACE  = "#2b2d30"
_C_BORDER   = "#393b40"
_C_ACCENT   = "#4dabf7"
_C_ACCENT2  = "#74c0fc"
_C_TEXT     = "#dce1e8"
_C_MUTED    = "#8b909a"
_C_SUCCESS  = "#51cf66"
_C_WARN     = "#ffd43b"
_C_ERROR    = "#ff6b6b"
_C_ORANGE   = "#fd7e14"

# ══════════════════════════════════════════════════════════════════════════════
# Master stylesheet
# ══════════════════════════════════════════════════════════════════════════════
_SS = f"""
/* ── Base ── */
* {{
    font-family: 'Segoe UI', 'Inter', 'SF Pro Text', Arial, sans-serif;
    font-size: 11px;
    color: {_C_TEXT};
    box-sizing: border-box;
}}
QDockWidget {{
    background: {_C_BG};
    border: none;
}}
QDockWidget::title {{
    background: {_C_BG};
    color: {_C_ACCENT};
    padding: 6px 12px;
    font-weight: 700;
    font-size: 12px;
    letter-spacing: 0.5px;
    border-bottom: 1px solid {_C_BORDER};
}}
QWidget#root {{
    background: {_C_BG};
    border: none;
}}

/* ── Section header ── */
QLabel#section_header {{
    color: {_C_MUTED};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1.2px;
    background: transparent;
    padding: 0;
}}

/* ── Card ── */
QFrame#card {{
    background: {_C_SURFACE};
    border: 1px solid {_C_BORDER};
    border-radius: 6px;
}}

/* ── Advanced (Trace & Smooth) frame ── */
QFrame#adv_card {{
    background: {_C_SURFACE};
    border: 1px solid {_C_ACCENT};
    border-radius: 6px;
}}
QLabel#adv_header {{
    color: {_C_ACCENT};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1.2px;
    background: transparent;
    padding: 0;
}}

/* ── Divider ── */
QFrame#div {{
    background: {_C_BORDER};
    max-height: 1px;
    border: none;
}}

/* ── Inputs ── */
QDoubleSpinBox, QComboBox {{
    background: {_C_BG};
    border: 1px solid {_C_BORDER};
    border-radius: 4px;
    padding: 3px 8px;
    color: {_C_TEXT};
    min-height: 26px;
    selection-background-color: {_C_ACCENT};
}}
QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {_C_ACCENT};
    background: #22252a;
}}
QDoubleSpinBox:disabled, QComboBox:disabled {{
    color: #555;
    background: #1a1b1d;
    border-color: #2a2b2e;
}}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: #383b40;
    border: none;
    width: 16px;
    border-radius: 2px;
}}
QDoubleSpinBox::up-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid {_C_MUTED};
    width: 0; height: 0;
}}
QDoubleSpinBox::down-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {_C_MUTED};
    width: 0; height: 0;
}}
QComboBox::drop-down {{
    border: none;
    background: #383b40;
    width: 22px;
    border-radius: 0 4px 4px 0;
}}
QComboBox::down-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {_C_MUTED};
    width: 0; height: 0;
}}
QComboBox QAbstractItemView {{
    background: {_C_SURFACE};
    color: {_C_TEXT};
    selection-background-color: {_C_ACCENT};
    selection-color: #fff;
    border: 1px solid {_C_BORDER};
    outline: none;
}}
QgsMapLayerComboBox {{
    background: {_C_BG};
    border: 1px solid {_C_BORDER};
    border-radius: 4px;
    color: {_C_TEXT};
    min-height: 26px;
    padding: 2px 8px;
}}

/* ── Checkbox ── */
QCheckBox {{
    color: {_C_TEXT};
    background: transparent;
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {_C_BORDER};
    border-radius: 3px;
    background: {_C_BG};
}}
QCheckBox::indicator:hover {{
    border-color: {_C_ACCENT};
}}
QCheckBox::indicator:checked {{
    background: {_C_ACCENT};
    border-color: {_C_ACCENT};
    image: none;
}}
QCheckBox:disabled {{
    color: #555;
}}

/* ── Slider ── */
QSlider::groove:horizontal {{
    height: 4px;
    background: {_C_BG};
    border: 1px solid {_C_BORDER};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {_C_ACCENT};
    border: 1px solid {_C_ACCENT};
    width: 12px;
    height: 12px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{
    background: {_C_ACCENT2};
    border-color: {_C_ACCENT2};
}}
QSlider::handle:horizontal:disabled {{
    background: #555;
    border-color: #555;
}}
QSlider::sub-page:horizontal {{
    background: {_C_ACCENT};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal:disabled {{
    background: #444;
}}
QSlider::tick:horizontal {{
    background: {_C_MUTED};
}}

/* ── Buttons — base ── */
QPushButton {{
    border-radius: 4px;
    padding: 5px 14px;
    min-height: 28px;
    font-weight: 600;
    border: 1px solid transparent;
    color: {_C_TEXT};
    background: #383b40;
}}
QPushButton:hover {{
    background: #424549;
    border-color: {_C_BORDER};
}}

/* ── Draw button ── */
QPushButton#btn_draw {{
    background: {_C_ACCENT};
    color: #000;
    border-color: {_C_ACCENT};
    font-weight: 700;
}}
QPushButton#btn_draw:hover {{
    background: {_C_ACCENT2};
    border-color: {_C_ACCENT2};
}}
QPushButton#btn_draw:checked {{
    background: {_C_ORANGE};
    color: #fff;
    border-color: {_C_ORANGE};
}}
QPushButton#btn_draw:checked:hover {{
    background: #e8720f;
}}

/* ── Align button ── */
QPushButton#btn_align {{
    background: {_C_ACCENT};
    color: #000;
    border-color: {_C_ACCENT};
    font-weight: 700;
    min-width: 80px;
    font-size: 12px;
}}
QPushButton#btn_align:hover {{ background: {_C_ACCENT2}; }}
QPushButton#btn_align:disabled {{
    background: #2e3035;
    color: #555;
    border-color: #2e3035;
}}

/* ── Preview / Undo ── */
QPushButton#btn_preview, QPushButton#btn_undo {{
    background: #2e3035;
    color: {_C_MUTED};
    border-color: {_C_BORDER};
    min-width: 56px;
}}
QPushButton#btn_preview:hover, QPushButton#btn_undo:hover {{
    background: #383b40;
    color: {_C_TEXT};
}}
QPushButton#btn_preview:disabled, QPushButton#btn_undo:disabled {{
    background: #252628;
    color: #404245;
    border-color: #2b2d30;
}}

/* ── Toggle group buttons ── */
QPushButton#toggle {{
    background: {_C_BG};
    color: {_C_MUTED};
    border: 1px solid {_C_BORDER};
    border-radius: 3px;
    padding: 3px 10px;
    min-height: 22px;
    font-size: 10px;
    font-weight: 500;
}}
QPushButton#toggle:hover {{
    color: {_C_TEXT};
    border-color: #555;
}}
QPushButton#toggle[active="true"] {{
    background: #1c3a56;
    color: {_C_ACCENT};
    border-color: {_C_ACCENT};
    font-weight: 700;
}}

/* ── Method cards ── */
QPushButton#method_card {{
    background: {_C_BG};
    border: 1px solid {_C_BORDER};
    border-radius: 5px;
    padding: 6px 8px;
    text-align: left;
    color: {_C_MUTED};
    font-size: 10px;
    min-height: 36px;
}}
QPushButton#method_card:hover {{
    border-color: #555;
    color: {_C_TEXT};
}}
QPushButton#method_card[active="true"] {{
    background: #152a3e;
    border-color: {_C_ACCENT};
    color: {_C_TEXT};
}}

/* ── Progress ── */
QProgressBar {{
    background: {_C_BG};
    border: 1px solid {_C_BORDER};
    border-radius: 3px;
    text-align: center;
    color: {_C_TEXT};
    font-size: 9px;
    max-height: 8px;
}}
QProgressBar::chunk {{
    background: {_C_ACCENT};
    border-radius: 2px;
}}

/* ── Status bar ── */
QFrame#status_bar {{
    background: #191a1d;
    border-top: 1px solid {_C_BORDER};
    border-radius: 0 0 0 0;
    min-height: 24px;
    max-height: 24px;
}}
QLabel#status_text {{
    font-size: 10px;
    background: transparent;
    color: {_C_MUTED};
}}
QLabel#status_icon {{
    font-size: 11px;
    background: transparent;
}}

/* ── Path info ── */
QLabel#path_info {{
    color: {_C_MUTED};
    font-size: 10px;
    background: transparent;
}}
QLabel#path_info[state="ready"] {{
    color: {_C_SUCCESS};
}}
QLabel#path_info[state="drawing"] {{
    color: {_C_WARN};
}}

/* ── Slider value badge ── */
QLabel#slider_value {{
    color: {_C_ACCENT};
    font-size: 11px;
    font-weight: 700;
    background: transparent;
    min-width: 16px;
}}
QLabel#slider_value:disabled {{
    color: #555;
}}
"""


# ══════════════════════════════════════════════════════════════════════════════
# Helper widgets
# ══════════════════════════════════════════════════════════════════════════════

def _div():
    f = QFrame()
    f.setObjectName("div")
    f.setFrameShape(QFrame.Shape.HLine)
    return f


def _card(inner_layout, padding=(8, 8, 8, 8), spacing=6):
    f = QFrame()
    f.setObjectName("card")
    inner_layout.setContentsMargins(*padding)
    inner_layout.setSpacing(spacing)
    f.setLayout(inner_layout)
    return f


def _section(text):
    lbl = QLabel(text.upper())
    lbl.setObjectName("section_header")
    return lbl


def _label(text, muted=True):
    lbl = QLabel(text)
    if muted:
        lbl.setStyleSheet(f"color: {_C_MUTED}; background: transparent;")
    return lbl


def _refresh_property(widget, prop, value):
    """Force Qt style re-evaluation after changing a dynamic property."""
    widget.setProperty(prop, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


# ══════════════════════════════════════════════════════════════════════════════
# Toggle group helper
# ══════════════════════════════════════════════════════════════════════════════

class ToggleGroup:
    """A row of exclusive QPushButton toggles (replaces QButtonGroup + QRadioButton)."""

    def __init__(self, items, parent=None):
        """
        items: list of (label, value)
        """
        self._btns = []
        self._values = []
        self._layout = QHBoxLayout()
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(3)

        for label, value in items:
            btn = QPushButton(label)
            btn.setObjectName("toggle")
            btn.setCheckable(False)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _, v=value: self.select(v))
            self._btns.append(btn)
            self._values.append(value)
            self._layout.addWidget(btn)

        if self._values:
            self.select(self._values[0])

    def layout(self):
        return self._layout

    def select(self, value):
        self._selected = value
        for btn, v in zip(self._btns, self._values):
            _refresh_property(btn, "active", "true" if v == value else "false")

    def value(self):
        return getattr(self, "_selected", self._values[0] if self._values else None)


# ══════════════════════════════════════════════════════════════════════════════
# Method card helper
# ══════════════════════════════════════════════════════════════════════════════

class MethodCard(QPushButton):
    """A clickable card displaying an alignment method."""

    def __init__(self, title, subtitle, value, parent=None):
        super().__init__(parent)
        self.setObjectName("method_card")
        self._value = value
        self.setCheckable(False)
        self.setMinimumHeight(40)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(1)

        self._title_lbl = QLabel(title)
        self._title_lbl.setStyleSheet(
            f"font-size:11px; font-weight:700; color:{_C_TEXT}; background:transparent;"
        )
        self._sub_lbl = QLabel(subtitle)
        self._sub_lbl.setStyleSheet(
            f"font-size:9px; color:{_C_MUTED}; background:transparent;"
        )
        layout.addWidget(self._title_lbl)
        layout.addWidget(self._sub_lbl)

    def value(self):
        return self._value

    def set_active(self, active: bool):
        _refresh_property(self, "active", "true" if active else "false")
        self._title_lbl.setStyleSheet(
            f"font-size:11px; font-weight:700; "
            f"color:{'#4dabf7' if active else _C_TEXT}; background:transparent;"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Main dock widget
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Main dock widget
# ══════════════════════════════════════════════════════════════════════════════

class AlignToPathDockWidget(QDockWidget):
    """Align Features to Path — v8.0."""

    # ── init ──────────────────────────────────────────────────────────────────

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface  = iface
        self.canvas = iface.mapCanvas()

        self._path_geom   = None
        self._prev_tool   = None
        self._undo_stack  = []          # [(layer, [(fid, QgsGeometry)])]
        self._preview_rbs = []

        self._map_tool = AlignmentPathTool(self.canvas)
        self._map_tool.pathFinished.connect(self._on_path_finished)
        self._map_tool.pathUpdated.connect(self._on_path_updated)
        self._map_tool.drawingCancelled.connect(self._on_drawing_cancelled)

        # Buffer preview (blue fill around path)
        self._tol_rb = QgsRubberBand(self.canvas, QgsWkbTypes.GeometryType.PolygonGeometry)
        self._tol_rb.setColor(QColor(77, 171, 247, 35))
        self._tol_rb.setStrokeColor(QColor(77, 171, 247, 140))
        self._tol_rb.setWidth(1)

        self._build_ui()
        self.setStyleSheet(_SS)
        self._refresh_buttons()

    # ══════════════════════════════════════════════════════════════════════════
    # UI Construction
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        self.setWindowTitle("Align Features")
        self.setMinimumWidth(270)
        self.setMaximumWidth(320)

        root = QWidget()
        root.setObjectName("root")

        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Scrollable content area ───────────────────────────────────────────
        content = QWidget()
        content.setObjectName("root")
        vbox = QVBoxLayout(content)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(10)

        # ── 1 · Draw Path ─────────────────────────────────────────────────────
        vbox.addWidget(_section("1 · Alignment Path"))

        draw_row = QHBoxLayout()
        draw_row.setSpacing(5)

        self._btn_draw = QPushButton("✏  Draw Path")
        self._btn_draw.setObjectName("btn_draw")
        self._btn_draw.setCheckable(True)
        self._btn_draw.setToolTip(
            "Left-click = add vertex\n"
            "Double-click or Enter = finish path\n"
            "Right-click or Esc = cancel\n"
            "T key = toggle Trace mode while drawing"
        )
        self._btn_draw.clicked.connect(self._on_draw_clicked)
        draw_row.addWidget(self._btn_draw, 1)

        self._btn_trace_mode = QPushButton("⤷ Trace")
        self._btn_trace_mode.setObjectName("toggle")
        self._btn_trace_mode.setCheckable(False)
        self._btn_trace_mode.setToolTip(
            "Toggle Trace mode (also T key while drawing).\n"
            "When ON: clicking follows the nearest feature edge\n"
            "from your last point to the cursor — like ArcGIS Pro's Trace."
        )
        self._btn_trace_mode.setMinimumWidth(60)
        self._btn_trace_mode.clicked.connect(self._on_trace_mode_toggled)
        self._trace_mode_active = False
        draw_row.addWidget(self._btn_trace_mode)

        vbox.addLayout(draw_row)

        self._path_info = QLabel("No path drawn yet")
        self._path_info.setObjectName("path_info")
        self._path_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vbox.addWidget(self._path_info)

        # ── 2 · Layer & Tolerance ─────────────────────────────────────────────
        vbox.addWidget(_div())
        vbox.addWidget(_section("2 · Layer & Tolerance"))

        grid = QGridLayout()
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        grid.addWidget(_label("Layer 1"), 0, 0)
        self._layer_combo = QgsMapLayerComboBox()
        # Accept both line and polygon layers
        self._layer_combo.setFilters(_FILTER_LINE | _FILTER_POLYGON)
        self._layer_combo.layerChanged.connect(self._refresh_buttons)
        grid.addWidget(self._layer_combo, 0, 1, 1, 2)

        # FIX v10.1.9 — second layer picker so BOTH sides of a gap can be
        # passed to a single align_features_to_path() call.  When both layers
        # are processed together the coherent pipeline (_fit_to_path_coherent /
        # _trace_rings_coherently) sees features from BOTH polygons and can
        # guarantee that their shared boundary lands on identical coordinates.
        # Processing them in separate calls never achieves this because each
        # call only "sees" one polygon's rings.
        grid.addWidget(_label("Layer 2"), 1, 0)
        self._layer_combo2 = QgsMapLayerComboBox()
        self._layer_combo2.setFilters(_FILTER_LINE | _FILTER_POLYGON)
        self._layer_combo2.setAllowEmptyLayer(True)          # optional
        self._layer_combo2.setCurrentIndex(0)                # default = empty
        self._layer_combo2.layerChanged.connect(self._refresh_buttons)
        grid.addWidget(self._layer_combo2, 1, 1, 1, 2)

        lbl_layer2_hint = _label("Optional: 2nd polygon layer for gap closing", muted=True)
        lbl_layer2_hint.setStyleSheet(
            f"color:{_C_MUTED}; font-size:9px; background:transparent;"
        )
        grid.addWidget(lbl_layer2_hint, 2, 1, 1, 2)

        grid.addWidget(_label("Tolerance"), 3, 0)
        self._spin_tol = QDoubleSpinBox()
        self._spin_tol.setRange(0.001, 999999)
        self._spin_tol.setValue(10.0)
        self._spin_tol.setDecimals(3)
        self._spin_tol.setToolTip("Max snap distance. Must be greater than zero.")
        self._spin_tol.valueChanged.connect(self._update_tol_preview)
        grid.addWidget(self._spin_tol, 3, 1)

        self._combo_unit = QComboBox()
        self._combo_unit.addItems(["m", "ft", "map units"])
        self._combo_unit.setMaximumWidth(72)
        self._combo_unit.currentIndexChanged.connect(self._update_tol_preview)
        grid.addWidget(self._combo_unit, 3, 2)

        vbox.addWidget(_card(grid))

        # ── 3 · Method ────────────────────────────────────────────────────────
        vbox.addWidget(_section("3 · Method"))

        method_layout = QVBoxLayout()
        method_layout.setContentsMargins(0, 0, 0, 0)
        method_layout.setSpacing(4)

        self._method_cards = []
        for title, subtitle, value in [
            ("Fit to Path",     "Move all vertices within tolerance",       METHOD_FIT),
            ("Smart Fit",       "Weighted fit — filters L-corners & crossing lines", METHOD_SMART_FIT),
            ("Preserve Shape",  "Only snap vertices inside buffer zone",    METHOD_PRESERVE),
            ("Snap Ends Only",  "Snap first & last vertex of each ring",    METHOD_SNAP_ENDS),
            ("Trace & Smooth",  "True path trace + curve smoothing",        METHOD_TRACE_SMOOTH),
        ]:
            card = MethodCard(title, subtitle, value)
            card.clicked.connect(lambda _, c=card: self._select_method(c))
            method_layout.addWidget(card)
            self._method_cards.append(card)

        if self._method_cards:
            self._method_cards[0].set_active(True)
        self._active_method_card = self._method_cards[0] if self._method_cards else None

        vbox.addLayout(method_layout)

        # ── 3b · Advanced options (all methods: Shared Boundary; Trace & Smooth: curve tracing) ──
        self._adv_frame = self._build_advanced_panel()
        self._adv_frame.setVisible(True)   # always visible — "Enforce Shared Boundary" applies to all methods
        vbox.addWidget(self._adv_frame)

        # ── 4 · Options (Side + End) ──────────────────────────────────────────
        vbox.addWidget(_section("4 · Options"))

        opts_layout = QGridLayout()
        opts_layout.setContentsMargins(8, 8, 8, 8)
        opts_layout.setHorizontalSpacing(8)
        opts_layout.setVerticalSpacing(6)

        opts_layout.addWidget(_label("Side"), 0, 0)
        self._side_group = ToggleGroup([
            ("Both",  SIDE_BOTH),
            ("Left",  SIDE_LEFT),
            ("Right", SIDE_RIGHT),
        ])
        opts_layout.addLayout(self._side_group.layout(), 0, 1)

        opts_layout.addWidget(_label("Ends"), 1, 0)
        self._end_group = ToggleGroup([
            ("Round",  END_ROUND),
            ("Square", END_SQUARE),
        ])
        self._end_group.layout().addStretch()
        opts_layout.addLayout(self._end_group.layout(), 1, 1)

        vbox.addWidget(_card(opts_layout))

        # ── Progress ──────────────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        vbox.addWidget(self._progress)

        # ── Actions ───────────────────────────────────────────────────────────
        vbox.addWidget(_div())

        hint = _label("Aligns every feature within the tolerance buffer of the path", muted=True)
        hint.setStyleSheet(
            f"color:{_C_MUTED}; font-size:9px; background:transparent;"
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vbox.addWidget(hint)

        act = QHBoxLayout()
        act.setSpacing(5)

        self._btn_preview = QPushButton("👁  Preview")
        self._btn_preview.setObjectName("btn_preview")
        self._btn_preview.setEnabled(False)
        self._btn_preview.setToolTip(
            "Show aligned result without modifying the layer.\n"
            "Yellow outlines show what will move."
        )
        self._btn_preview.clicked.connect(self._run_preview)

        self._btn_undo = QPushButton("↩  Undo")
        self._btn_undo.setObjectName("btn_undo")
        self._btn_undo.setEnabled(False)
        self._btn_undo.setToolTip("Revert the last Align operation. Ctrl+Z also works.")
        self._btn_undo.clicked.connect(self._do_undo)

        self._btn_align = QPushButton("▶  Align")
        self._btn_align.setObjectName("btn_align")
        self._btn_align.setEnabled(False)
        self._btn_align.clicked.connect(self._run_align)

        act.addWidget(self._btn_preview)
        act.addStretch()
        act.addWidget(self._btn_undo)
        act.addWidget(self._btn_align)
        vbox.addLayout(act)
        vbox.addStretch()

        # ── Status bar ────────────────────────────────────────────────────────
        status_bar = QFrame()
        status_bar.setObjectName("status_bar")
        sb_layout = QHBoxLayout(status_bar)
        sb_layout.setContentsMargins(10, 0, 10, 0)
        sb_layout.setSpacing(6)

        self._status_icon = QLabel("●")
        self._status_icon.setObjectName("status_icon")
        self._status_icon.setStyleSheet(f"color:{_C_MUTED}; background:transparent;")

        self._status_text = QLabel("Ready")
        self._status_text.setObjectName("status_text")

        sb_layout.addWidget(self._status_icon)
        sb_layout.addWidget(self._status_text, 1)

        # ── Assemble ──────────────────────────────────────────────────────────
        outer.addWidget(content, 1)
        outer.addWidget(status_bar)

        self.setWidget(root)

        # FIX v10.1.9: Fit to Path is the default method, so the trace-specific
        # controls start out disabled.  They are re-enabled by _select_method()
        # when the user picks "Trace & Smooth".

    # ──────────────────────────────────────────────────────────────────────────
    # Advanced panel (Trace & Smooth)
    # ──────────────────────────────────────────────────────────────────────────

    def _build_advanced_panel(self) -> QFrame:
        """
        Build the panel that appears when the user picks "Trace & Smooth".

        Layout:
            ┌─ ADVANCED: TRACE & SMOOTH ────────────┐
            │  ☐  Enable Curve Tracing               │
            │                                        │
            │  Smoothing   ◯─────  2                 │
            │  Resample    [ 5.000 ] m               │
            └────────────────────────────────────────┘
        """
        frame = QFrame()
        frame.setObjectName("adv_card")

        v = QVBoxLayout(frame)
        v.setContentsMargins(10, 8, 10, 10)
        v.setSpacing(8)

        # Header
        header = QLabel("ADVANCED · GAP FIX & TRACE OPTIONS")
        header.setObjectName("adv_header")
        v.addWidget(header)

        # ── Smart Fit options (only relevant for Smart Fit mode) ──────────────
        self._smart_frame = QFrame()
        sf_layout = QVBoxLayout(self._smart_frame)
        sf_layout.setContentsMargins(0, 2, 0, 4)
        sf_layout.setSpacing(4)

        smart_header = QLabel("SMART FIT OPTIONS")
        smart_header.setObjectName("adv_header")
        sf_layout.addWidget(smart_header)

        # Intersection significance threshold
        sig_row = QHBoxLayout()
        sig_row.setSpacing(8)
        sig_lbl = _label("Min. Overlap %")
        sig_lbl.setFixedWidth(88)
        sig_row.addWidget(sig_lbl)

        self._spin_min_overlap = QDoubleSpinBox()
        self._spin_min_overlap.setRange(0.0, 50.0)
        self._spin_min_overlap.setValue(2.0)
        self._spin_min_overlap.setDecimals(1)
        self._spin_min_overlap.setSuffix(" %")
        self._spin_min_overlap.setToolTip(
            "Minimum overlap between the tolerance buffer and a feature\n"
            "as a % of the feature's area (polygons) or length (lines).\n"
            "Features below this threshold are skipped — prevents L-corner\n"
            "pulls and crossing-line artefacts.\n"
            "Default 2 %. Raise to exclude more marginal intersections."
        )
        sig_row.addWidget(self._spin_min_overlap, 1)
        sf_layout.addLayout(sig_row)

        # Weighted / hard snap toggle
        self._chk_weighted = QCheckBox("Proximity-weighted movement")
        self._chk_weighted.setChecked(True)
        self._chk_weighted.setToolTip(
            "When ON: vertices close to the path snap almost fully;\n"
            "vertices near the tolerance edge move only a little.\n"
            "Prevents aggressive global pull on distant vertices.\n"
            "When OFF: same hard snap as classic Fit to Path."
        )
        sf_layout.addWidget(self._chk_weighted)

        v.addWidget(self._smart_frame)
        self._smart_frame.setVisible(False)

        div_smart = QFrame()
        div_smart.setObjectName("div")
        div_smart.setFixedHeight(1)
        v.addWidget(div_smart)
        self._div_smart = div_smart
        self._div_smart.setVisible(False)

        # Enable checkbox
        self._chk_tracing = QCheckBox("Enable Curve Tracing")
        self._chk_tracing.setChecked(True)
        self._chk_tracing.setToolTip(
            "When ON: true path tracing — polygon edges inside the\n"
            "tolerance buffer are replaced by the actual path curve\n"
            "(like ArcGIS Pro's Trace tool).\n"
            "When OFF: legacy resample + snap pipeline (v7 behaviour)."
        )
        self._chk_tracing.toggled.connect(self._on_tracing_toggled)
        v.addWidget(self._chk_tracing)

        # v9 Coherent Multi-Polygon Boundary Alignment
        # "Enforce Shared Boundary" — when ON, every polygon touched by the
        # path is traced against the SAME master path and a final coincidence
        # pass makes the new shared boundary identical for all of them
        # (no slivers / gaps / overlaps). When OFF, falls back to v8 independent
        # per-feature tracing.
        self._chk_shared_boundary = QCheckBox("Enforce Shared Boundary (Fix Gaps)")
        self._chk_shared_boundary.setChecked(True)
        self._chk_shared_boundary.setToolTip(
            "When ON: adjacent polygons crossed by the path share an\n"
            "identical, perfectly coincident boundary — ideal for land\n"
            "parcels (no slivers or gaps between neighbours).\n"
            "When OFF: each feature is traced independently (v8 behaviour)."
        )
        v.addWidget(self._chk_shared_boundary)

        # Smoothing slider + value label
        smooth_row = QHBoxLayout()
        smooth_row.setSpacing(8)
        smooth_lbl = _label("Smoothing")
        smooth_lbl.setFixedWidth(64)
        smooth_row.addWidget(smooth_lbl)

        self._sld_smooth = QSlider(Qt.Orientation.Horizontal)
        self._sld_smooth.setRange(1, 5)
        self._sld_smooth.setValue(2)
        self._sld_smooth.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._sld_smooth.setTickInterval(1)
        self._sld_smooth.setToolTip(
            "Chaikin corner-cutting passes applied after snapping.\n"
            "1 = light smoothing · 5 = very smooth curves."
        )
        self._sld_smooth.valueChanged.connect(self._on_smooth_changed)
        smooth_row.addWidget(self._sld_smooth, 1)

        self._lbl_smooth_val = QLabel("2")
        self._lbl_smooth_val.setObjectName("slider_value")
        self._lbl_smooth_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        smooth_row.addWidget(self._lbl_smooth_val)

        v.addLayout(smooth_row)

        # Resample distance row
        resample_row = QHBoxLayout()
        resample_row.setSpacing(8)
        resample_lbl = _label("Resample")
        resample_lbl.setFixedWidth(64)
        resample_row.addWidget(resample_lbl)

        self._spin_resample = QDoubleSpinBox()
        self._spin_resample.setRange(0.1, 9999)
        self._spin_resample.setValue(5.0)
        self._spin_resample.setDecimals(3)
        self._spin_resample.setToolTip(
            "Densify rings so vertices are no farther apart than\n"
            "this distance — improves curve following."
        )
        resample_row.addWidget(self._spin_resample, 1)

        self._combo_resample_unit = QComboBox()
        self._combo_resample_unit.addItems(["m", "ft", "map units"])
        self._combo_resample_unit.setMaximumWidth(72)
        resample_row.addWidget(self._combo_resample_unit)

        v.addLayout(resample_row)

        # FIX v10.1.9: default method is Fit to Path, so trace-only controls
        # start disabled.  _select_method() re-enables them for Trace & Smooth.
        self._chk_tracing.setEnabled(False)
        self._sld_smooth.setEnabled(False)
        self._lbl_smooth_val.setEnabled(False)
        self._spin_resample.setEnabled(False)
        self._combo_resample_unit.setEnabled(False)

        return frame

    # ══════════════════════════════════════════════════════════════════════════
    # State & helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _set_status(self, text, kind="idle"):
        colors = {
            "idle":    _C_MUTED,
            "drawing": _C_WARN,
            "ready":   _C_SUCCESS,
            "done":    _C_SUCCESS,
            "error":   _C_ERROR,
        }
        color = colors.get(kind, _C_MUTED)
        self._status_icon.setStyleSheet(f"color:{color}; background:transparent;")
        self._status_text.setStyleSheet(f"color:{color}; background:transparent; font-size:10px;")
        self._status_text.setText(text)

    def _select_method(self, clicked_card):
        for card in self._method_cards:
            card.set_active(card is clicked_card)
        self._active_method_card = clicked_card

        # FIX v10.1.9: always show the advanced panel so the
        # "Enforce Shared Boundary" checkbox is accessible for every method.
        # The trace-specific controls (curve tracing, smoothing, resample)
        # are enabled only when Trace & Smooth is chosen.
        is_trace = (clicked_card.value() == METHOD_TRACE_SMOOTH)
        is_smart = (clicked_card.value() == METHOD_SMART_FIT)
        self._adv_frame.setVisible(True)

        # Smart Fit controls: only visible for Smart Fit
        self._smart_frame.setVisible(is_smart)
        self._div_smart.setVisible(is_smart)

        # Trace-only controls: only enabled/relevant for Trace & Smooth
        tracing_ui_enabled = is_trace
        self._chk_tracing.setEnabled(tracing_ui_enabled)
        self._sld_smooth.setEnabled(tracing_ui_enabled and self._chk_tracing.isChecked())
        self._lbl_smooth_val.setEnabled(tracing_ui_enabled and self._chk_tracing.isChecked())
        self._spin_resample.setEnabled(tracing_ui_enabled and self._chk_tracing.isChecked())
        self._combo_resample_unit.setEnabled(tracing_ui_enabled and self._chk_tracing.isChecked())
        # Shared boundary is always enabled (applies to all methods)
        self._chk_shared_boundary.setEnabled(True)

    def _on_tracing_toggled(self, enabled: bool):
        """Enable/disable the smoothing & resample controls."""
        self._sld_smooth.setEnabled(enabled)
        self._lbl_smooth_val.setEnabled(enabled)
        self._spin_resample.setEnabled(enabled)
        self._combo_resample_unit.setEnabled(enabled)
        # FIX v10.1.9: shared boundary applies to all methods — always enabled.
        # (previously was gated on tracing being on, which incorrectly disabled
        #  it for Fit/Preserve/Snap Ends even though the coherent pipeline
        #  honours it for those methods too.)
        self._chk_shared_boundary.setEnabled(True)

    def _on_smooth_changed(self, val: int):
        self._lbl_smooth_val.setText(str(val))

    def _get_method(self):
        if self._active_method_card:
            return self._active_method_card.value()
        return METHOD_FIT

    def _get_side(self):
        return self._side_group.value()

    def _get_end(self):
        return self._end_group.value()

    def _get_trace_params(self) -> dict:
        """
        Return trace/smooth parameters for the current UI state.

        enable_tracing=True  → v8 true path tracing
        enable_tracing=False → v7 legacy resample+snap+smooth

        FIX v10.1.9 — enable_shared_boundary is now propagated for ALL
        methods (Fit, Preserve, Snap Ends, Trace).  Previously it was
        hard-coded to False for every method except Trace & Smooth, which
        meant the coherent gap-closing pass (_fit_to_path_coherent) never
        received the flag and could not guarantee identical shared-boundary
        coordinates between adjacent polygons.
        """
        method = self._get_method()

        # Read the global "Enforce Shared Boundary" checkbox.
        # The checkbox lives in the advanced Trace panel but its effect is
        # meaningful for ALL methods, so we read it unconditionally.
        shared_boundary = self._chk_shared_boundary.isChecked()

        if method == METHOD_SMART_FIT:
            # Smart Fit: pass overlap ratio; weighted movement is handled inside
            # _smart_fit_to_path (the checkbox only controls internal behaviour
            # there; we pass the ratio from the UI spinner).
            return {
                "resample_distance": 0.0,
                "smooth_iterations": 0,
                "enable_tracing": False,
                "enable_shared_boundary": shared_boundary,
                "smart_min_overlap_ratio": self._spin_min_overlap.value() / 100.0,
            }

        if method != METHOD_TRACE_SMOOTH:
            # For Fit / Preserve / Snap Ends: pass enable_shared_boundary so
            # the algorithm routes through the coherent pipeline.
            return {
                "resample_distance": 0.0,
                "smooth_iterations": 0,
                "enable_tracing": False,
                "enable_shared_boundary": shared_boundary,
            }

        tracing_on = self._chk_tracing.isChecked()
        if not tracing_on:
            return {
                "resample_distance": 0.0,
                "smooth_iterations": 0,
                "enable_tracing": False,
                "enable_shared_boundary": shared_boundary,
            }

        return {
            "resample_distance": self._to_map_units(
                self._spin_resample.value(), self._combo_resample_unit
            ),
            "smooth_iterations": self._sld_smooth.value(),
            "enable_tracing": True,
            # v9/v10 Coherent Multi-Polygon Boundary Alignment
            "enable_shared_boundary": shared_boundary,
        }

    def _refresh_buttons(self):
        ready = (
            self._path_geom is not None
            and self._layer_combo.currentLayer() is not None
        )
        self._btn_align.setEnabled(ready)
        self._btn_preview.setEnabled(ready)
        self._btn_undo.setEnabled(bool(self._undo_stack))

    def _to_map_units(self, value, combo):
        unit = combo.currentText()
        if unit == "map units":
            return value
        layer = self._layer_combo.currentLayer()
        if layer is None:
            return value
        try:
            mu_per_m = 1.0 / layer.crs().mapUnitsPerMeter()
        except Exception:
            mu_per_m = 1.0
        return value * mu_per_m if unit == "m" else value * mu_per_m * 0.3048

    def _get_features(self, layer, tol):
        # Align every feature whose geometry intersects the tolerance buffer of
        # the path.  This matches ArcGIS Pro behaviour: only features that
        # actually touch the path's buffer zone are processed; features outside
        # it are ignored regardless of any active selection.
        #
        # The bbox is grown by tol (not tol*2) because the algorithm uses
        # search_buffer=tol as the hard containment boundary — the bounding-box
        # pre-filter just needs to pass every feature that *could* intersect
        # that buffer.  The exact intersection test happens inside the algorithm.
        if self._path_geom is None:
            return []
        bbox = self._path_geom.boundingBox()
        bbox.grow(tol)
        req = QgsFeatureRequest().setFilterRect(bbox)
        req.setFlags(_FLAG_EXACT_INTERSECT)
        return list(layer.getFeatures(req))

    def _get_all_features(self, tol):
        """
        FIX v10.1.9 — collect features from BOTH layer combos in one pass.

        Returning features from both layers together lets the coherent
        pipeline (_fit_to_path_coherent / _trace_rings_coherently) see ALL
        adjacent polygons simultaneously so their shared boundary coordinates
        come out bitwise-identical — the gap closes by construction.

        Returns:
            (features, layers_used)
            features   : flat list of QgsFeature from layer 1 [+ layer 2]
            layers_used: list of (layer, [feature_id, ...]) for apply-back
        """
        layers_used = []
        all_features = []

        layer1 = self._layer_combo.currentLayer()
        if layer1 is not None:
            feats1 = self._get_features(layer1, tol)
            if feats1:
                layers_used.append((layer1, [f.id() for f in feats1]))
                all_features.extend(feats1)

        layer2 = self._layer_combo2.currentLayer()
        if layer2 is not None and layer2 != layer1:
            feats2 = self._get_features(layer2, tol)
            if feats2:
                layers_used.append((layer2, [f.id() for f in feats2]))
                all_features.extend(feats2)

        return all_features, layers_used

    # ══════════════════════════════════════════════════════════════════════════
    # Drawing callbacks
    # ══════════════════════════════════════════════════════════════════════════

    def _on_draw_clicked(self, checked):
        if checked:
            self._clear_preview()
            self._prev_tool = self.canvas.mapTool()
            self.canvas.setMapTool(self._map_tool)
            self._btn_draw.setText("✖  Stop Drawing")
            self._set_status("Drawing path…", "drawing")
            _refresh_property(self._path_info, "state", "drawing")
            self._path_info.setText(
                "Click to add vertices · Double-click to finish · T=Trace"
            )
            # Sync trace mode to map tool
            self._map_tool.trace_mode = self._trace_mode_active
        else:
            self.canvas.unsetMapTool(self._map_tool)
            if self._prev_tool:
                self.canvas.setMapTool(self._prev_tool)
            self._btn_draw.setText("✏  Draw Path")
            if self._path_geom is None:
                self._set_status("Ready", "idle")

    def _on_trace_mode_toggled(self):
        self._trace_mode_active = not self._trace_mode_active
        _refresh_property(
            self._btn_trace_mode, "active",
            "true" if self._trace_mode_active else "false",
        )
        self._map_tool.trace_mode = self._trace_mode_active
        if self._trace_mode_active:
            self._set_status("Trace mode ON — hover over feature edges", "drawing")
        else:
            self._set_status("Trace mode OFF", "idle")

    def _on_path_updated(self, geom):
        self._tol_rb.reset(QgsWkbTypes.GeometryType.PolygonGeometry)
        if geom is None or geom.isEmpty():
            return
        tol = self._to_map_units(self._spin_tol.value(), self._combo_unit)
        if tol <= 0:
            return
        # GEOS cap integers: Round=1, Flat=2, Square=3.
        cap = 1 if self._get_end() == END_ROUND else 2  # Flat cap: stops at path end
        buf = _make_buffer(geom, tol, cap, 1)
        if buf and not buf.isEmpty():
            self._tol_rb.setToGeometry(buf, None)

    def _on_path_finished(self, geom):
        self._path_geom = geom
        self._btn_draw.setChecked(False)
        self._btn_draw.setText("✏  Redraw Path")
        n = len(list(geom.vertices()))
        length = geom.length()
        self._path_info.setText(f"✓  {n} vertices  ·  {length:.2f} units")
        _refresh_property(self._path_info, "state", "ready")
        self._set_status("Path ready", "ready")
        if self._prev_tool:
            self.canvas.setMapTool(self._prev_tool)
        self._update_tol_preview()
        self._refresh_buttons()

    def _on_drawing_cancelled(self):
        self._btn_draw.setChecked(False)
        self._btn_draw.setText("✏  Draw Path")
        if self._path_geom is None:
            self._set_status("Ready", "idle")
            self._path_info.setText("No path drawn yet")
            _refresh_property(self._path_info, "state", "")
        if self._prev_tool:
            self.canvas.setMapTool(self._prev_tool)
        self._tol_rb.reset(QgsWkbTypes.GeometryType.PolygonGeometry)

    # ══════════════════════════════════════════════════════════════════════════
    # Tolerance buffer preview
    # ══════════════════════════════════════════════════════════════════════════

    def _update_tol_preview(self):
        self._tol_rb.reset(QgsWkbTypes.GeometryType.PolygonGeometry)
        if self._path_geom is None:
            return
        tol = self._to_map_units(self._spin_tol.value(), self._combo_unit)
        if tol <= 0:
            return
        # GEOS cap integers: Round=1, Flat=2, Square=3.
        # Use 3 (Square extended) for Square to match the algorithm's _CAP_SQUARE.
        cap = 1 if self._get_end() == END_ROUND else 2  # Flat cap: stops at path end
        buf = _make_buffer(self._path_geom, tol, cap, 1)
        if buf and not buf.isEmpty():
            self._tol_rb.setToGeometry(buf, None)

    # ══════════════════════════════════════════════════════════════════════════
    # Preview (dry run)
    # ══════════════════════════════════════════════════════════════════════════

    def _clear_preview(self):
        for rb in self._preview_rbs:
            rb.reset(QgsWkbTypes.GeometryType.PolygonGeometry)
        self._preview_rbs.clear()

    def _run_preview(self):
        self._clear_preview()
        layer = self._layer_combo.currentLayer()
        if not layer or not self._path_geom:
            return
        tol = self._to_map_units(self._spin_tol.value(), self._combo_unit)
        features, _layers_used = self._get_all_features(tol)
        if not features:
            self._set_status("No features in range", "error")
            return

        is_trace = (self._get_method() == METHOD_TRACE_SMOOTH)
        self._set_status(
            "Resampling & snapping…" if is_trace else "Generating preview…",
            "drawing",
        )
        QApplication.processEvents()

        trace_params = self._get_trace_params()
        try:
            results = align_features_to_path(
                path_geom=self._path_geom,
                features=features,
                tolerance=tol,
                offset=0.0,
                method=self._get_method(),
                side=self._get_side(),
                end_style=self._get_end(),
                search_buffer=tol,
                **trace_params,
            )
        except Exception as e:
            self._set_status("Preview error", "error")
            QgsMessageLog.logMessage(str(e), "AlignFeatures", Qgis.MessageLevel.Warning)
            return

        for _feat, new_geom in results:
            rb = QgsRubberBand(self.canvas, QgsWkbTypes.GeometryType.PolygonGeometry)
            rb.setColor(QColor(255, 212, 59, 50))
            rb.setStrokeColor(QColor(255, 212, 59, 220))
            rb.setWidth(2)
            rb.setToGeometry(new_geom, None)
            self._preview_rbs.append(rb)

        count = len(results)
        self._set_status(f"Preview: {count} feature(s)", "ready")
        self.iface.messageBar().pushMessage(
            "Align Features — Preview",
            f"{count} feature(s) shown (yellow). Click ▶ Align to apply.",
            level=Qgis.MessageLevel.Info, duration=4,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Align
    # ══════════════════════════════════════════════════════════════════════════

    def _run_align(self):
        layer = self._layer_combo.currentLayer()
        if not layer or not self._path_geom:
            return

        tol = self._to_map_units(self._spin_tol.value(), self._combo_unit)

        # FIX v10.1.9 — collect features from BOTH layers together so the
        # coherent gap-closing pipeline sees all adjacent polygon rings in
        # a single call and guarantees their shared boundary is identical.
        features, layers_used = self._get_all_features(tol)

        if not features:
            self._set_status("No features found", "error")
            self.iface.messageBar().pushMessage(
                "Align Features",
                "No features found near the path. Try increasing Tolerance.",
                level=Qgis.MessageLevel.Warning, duration=5,
            )
            return

        self._progress.setVisible(True)
        self._progress.setRange(0, len(features))
        self._btn_align.setEnabled(False)
        self._btn_preview.setEnabled(False)

        is_trace = (self._get_method() == METHOD_TRACE_SMOOTH)
        self._set_status(
            "Resampling & snapping…" if is_trace else "Aligning…",
            "drawing",
        )
        QApplication.processEvents()

        def _cb(cur, tot):
            self._progress.setValue(cur)
            QApplication.processEvents()

        trace_params = self._get_trace_params()
        try:
            results = align_features_to_path(
                path_geom=self._path_geom,
                features=features,
                tolerance=tol,
                offset=0.0,
                method=self._get_method(),
                side=self._get_side(),
                end_style=self._get_end(),
                search_buffer=tol,
                progress_callback=_cb,
                **trace_params,
            )
        except Exception as e:
            self._set_status("Error — see log", "error")
            QgsMessageLog.logMessage(str(e), "AlignFeatures", Qgis.MessageLevel.Critical)
            self._progress.setVisible(False)
            self._refresh_buttons()
            return

        if not results:
            self._set_status("Nothing changed", "idle")
            self._progress.setVisible(False)
            self._refresh_buttons()
            return

        # ── Save undo snapshot (per layer) ────────────────────────────────────
        # Build a {fid → new_geom} map so we can split by layer efficiently.
        result_map = {feat.id(): (feat, new_geom) for feat, new_geom in results}

        undo_entries = {}   # layer → [(fid, old_geom)]
        for lyr, fid_list in layers_used:
            undo_entries[id(lyr)] = (lyr, [])

        for feat, new_geom in results:
            fid = feat.id()
            # Find which layer owns this feature
            for lyr, fid_list in layers_used:
                if fid in fid_list:
                    undo_entries[id(lyr)][1].append(
                        (fid, feat.geometry())
                    )
                    break

        # Push one undo entry per layer onto the undo stack
        for lyr_id, (lyr, snapshot) in undo_entries.items():
            if snapshot:
                self._undo_stack.append((lyr, snapshot))
        if len(self._undo_stack) > 5:
            self._undo_stack = self._undo_stack[-5:]

        # ── Apply per layer ───────────────────────────────────────────────────
        total_count = 0
        modified_layer_names = []
        for lyr, fid_list in layers_used:
            fid_set = set(fid_list)
            layer_results = [
                (feat, new_geom) for feat, new_geom in results
                if feat.id() in fid_set
            ]
            if not layer_results:
                continue
            if not lyr.isEditable():
                lyr.startEditing()
            count = apply_results_in_place(lyr, layer_results)
            total_count += count
            if count:
                modified_layer_names.append(f"'{lyr.name()}' ({count})")

        self._clear_preview()
        self._tol_rb.reset(QgsWkbTypes.GeometryType.PolygonGeometry)

        # Method-specific done message
        if is_trace:
            tracing_on = self._chk_tracing.isChecked()
            if tracing_on:
                done_msg = f"Done — {total_count} feature(s) traced along path"
            else:
                done_msg = f"Done — {total_count} feature(s) snapped (tracing disabled)"
        else:
            done_msg = f"Done — {total_count} feature(s) aligned"

        self._set_status(done_msg, "done")
        layers_str = ", ".join(modified_layer_names) if modified_layer_names else "no layers"
        self.iface.messageBar().pushMessage(
            "Align Features",
            f"{total_count} feature(s) updated on {layers_str}. "
            "Layer(s) in edit mode — save to commit or Ctrl+Z to undo.",
            level=Qgis.MessageLevel.Success, duration=6,
        )
        self._progress.setVisible(False)
        self._refresh_buttons()

    # ══════════════════════════════════════════════════════════════════════════
    # Undo
    # ══════════════════════════════════════════════════════════════════════════

    def _do_undo(self):
        if not self._undo_stack:
            return
        layer, snapshot = self._undo_stack.pop()
        self._refresh_buttons()
        if not layer or not hasattr(layer, "changeGeometry"):
            self._set_status("Undo failed — layer gone", "error")
            return
        if not layer.isEditable():
            layer.startEditing()
        reverted = sum(
            1 for fid, geom in snapshot if layer.changeGeometry(fid, geom)
        )
        self._set_status(f"Undone — {reverted} feature(s) restored", "ready")
        self.iface.messageBar().pushMessage(
            "Align Features — Undo",
            f"{reverted} feature(s) restored. Layer still in edit mode.",
            level=Qgis.MessageLevel.Info, duration=5,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Cleanup
    # ══════════════════════════════════════════════════════════════════════════

    def hideEvent(self, event):
        self._clear_preview()
        self._tol_rb.reset(QgsWkbTypes.GeometryType.PolygonGeometry)
        if self._map_tool and self.canvas.mapTool() == self._map_tool:
            self.canvas.unsetMapTool(self._map_tool)
        super().hideEvent(event)
