# -*- coding: utf-8 -*-
"""
alignment_path_tool.py  — v4 (trace-along-feature mode)
=========================================================
What's new in v4
-----------------
*  **Trace mode** — toggle with T key or the "Trace" button.  When active,
   moving the cursor along an existing feature highlights the shortest path
   along that feature's geometry from the last committed point to the cursor.
   Clicking commits all the intermediate vertices at once, perfectly
   duplicating the traced feature's shape — analogous to ArcGIS Pro's
   Trace construction method.

*  `_find_trace_path()` — walks the nearest vector-layer edge geometry from
   the last committed point to the cursor, returning an ordered list of
   QgsPointXY that follows the feature exactly.

*  Trace rubber band styled in cyan so it's visually distinct from the
   normal path rubber band (blue).

*  T key toggles trace mode on/off while drawing.

*  All v3 features unchanged:
   - Real vertex snapping (QgsSnappingUtils + manual fallback).
   - Orange snap-vertex marker.
   - pathFinished / pathUpdated / drawingCancelled signals.

Author: Mustafa Elghazaly
"""

import math
import time  # FIX 1: used for the double-click time-window threshold
from typing import List, Optional, Tuple

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QCursor

from qgis.core import (
    QgsGeometry,
    QgsPointXY,
    QgsWkbTypes,
    QgsMessageLog,
    QgsProject,
    QgsSnappingConfig,
    QgsPointLocator,
    QgsFeatureRequest,
    Qgis,
)
from qgis.gui import QgsMapTool, QgsRubberBand, QgsVertexMarker

# ---------------------------------------------------------------------------
# Compatibility shim
# ---------------------------------------------------------------------------
try:
    from qgis.core import QgsTolerance
    try:
        # Qt6 / QGIS 4 (and modern 3.x): fully-scoped enum access.
        QgsTolerance_ProjectUnits = QgsTolerance.UnitType.ProjectUnits
    except AttributeError:
        # Older PyQt5 / QGIS where the unscoped alias is the only form.
        QgsTolerance_ProjectUnits = QgsTolerance.ProjectUnits
except (ImportError, AttributeError):
    QgsTolerance_ProjectUnits = 1


# ── Trace path helpers ─────────────────────────────────────────────────────────

def _dist(a: QgsPointXY, b: QgsPointXY) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def _nearest_vertex_on_geom(
    target: QgsPointXY,
    geom: QgsGeometry,
) -> Tuple[float, int, QgsPointXY]:
    """
    Return (distance, vertex_index, vertex_point) for the nearest vertex
    of `geom` to `target`.
    """
    best_d   = float("inf")
    best_idx = 0
    best_pt  = target
    for i, v in enumerate(geom.vertices()):
        vpt = QgsPointXY(v.x(), v.y())
        d = _dist(target, vpt)
        if d < best_d:
            best_d   = d
            best_idx = i
            best_pt  = vpt
    return best_d, best_idx, best_pt


def _extract_vertices(geom: QgsGeometry) -> List[QgsPointXY]:
    """Extract all vertices of a (possibly multi) geometry in order."""
    pts = []
    for v in geom.vertices():
        pts.append(QgsPointXY(v.x(), v.y()))
    return pts


# ── True edge-tracing helpers (v8 patch) ──────────────────────────────────────
# The following helpers implement a TRUE edge-following trace behaviour
# (analogous to ArcGIS Pro's Trace construction tool) using QGIS-native
# geometry APIs (boundary(), lineLocatePoint(), interpolate(), segmentize()).
# They replace the previous vertex-based traversal that produced jumpy paths.

def _to_traceable_line(geom: QgsGeometry, geom_type) -> Optional[QgsGeometry]:
    """Return a line-type geometry suitable for edge tracing.

    For polygons:   prefer QgsGeometry.boundary() (returns the rings as a
                    (Multi)LineString / CompoundCurve, preserving topology).
                    Falls back to convertToType(LineGeometry) for very old
                    QGIS builds where boundary() is unavailable.
    For lines:      returned unchanged.
    """
    if geom_type == QgsWkbTypes.GeometryType.PolygonGeometry:
        try:
            b = geom.boundary()
            if b is not None and not b.isEmpty():
                return b
        except Exception:
            pass
        try:
            return geom.convertToType(QgsWkbTypes.GeometryType.LineGeometry, False)
        except Exception:
            return None
    return geom


def _segmentize_if_curved(line_geom: QgsGeometry) -> QgsGeometry:
    """If the line has curved segments (CircularString / CompoundCurve / etc.),
    expand them into a fine polyline via QGIS's native segmentize().  Otherwise
    return the geometry unchanged so straight LineStrings are not needlessly
    densified.
    """
    try:
        if QgsWkbTypes.isCurvedType(line_geom.wkbType()):
            abs_g = line_geom.constGet()
            if abs_g is not None:
                segmented = abs_g.segmentize()
                if segmented is not None:
                    return QgsGeometry(segmented.clone())
    except Exception:
        pass
    return line_geom


def _pick_closest_line_part(
    line_geom: QgsGeometry, anchor: QgsPointXY
) -> Optional[QgsGeometry]:
    """For multi-part line geometries, return a single-part line whose part is
    closest to `anchor`.  For single-part lines, return as-is.

    Picking a single part lets us use lineLocatePoint() / interpolate() with
    intuitive (non-cumulative-across-parts) semantics.
    """
    try:
        if not line_geom.isMultipart():
            return line_geom
    except Exception:
        return line_geom

    anchor_geom = QgsGeometry.fromPointXY(anchor)
    best_part   = None
    best_d      = float("inf")
    try:
        for part in line_geom.parts():
            part_geom = QgsGeometry(part.clone())
            if part_geom.isEmpty():
                continue
            d = part_geom.distance(anchor_geom)
            if d < best_d:
                best_d    = d
                best_part = part_geom
    except Exception:
        return line_geom
    return best_part if best_part is not None else line_geom


def _line_is_closed(line_geom: QgsGeometry) -> bool:
    """True if the line's first and last vertices coincide (closed ring)."""
    try:
        verts = list(line_geom.vertices())
        if len(verts) < 2:
            return False
        first = verts[0]
        last  = verts[-1]
        return (abs(first.x() - last.x()) < 1e-9 and
                abs(first.y() - last.y()) < 1e-9)
    except Exception:
        return False


def _line_vertex_distances(
    line_geom: QgsGeometry,
) -> List[Tuple[float, QgsPointXY]]:
    """Return a list of (cumulative_distance_along_line, vertex_point) tuples
    for every vertex of the (single-part, already-segmentized) line.
    """
    out: List[Tuple[float, QgsPointXY]] = []
    try:
        verts = list(line_geom.vertices())
    except Exception:
        return out
    if not verts:
        return out

    prev = QgsPointXY(verts[0].x(), verts[0].y())
    out.append((0.0, prev))
    cum = 0.0
    for v in verts[1:]:
        pt = QgsPointXY(v.x(), v.y())
        cum += math.hypot(pt.x() - prev.x(), pt.y() - prev.y())
        out.append((cum, pt))
        prev = pt
    return out


def _extract_forward_path(
    vertex_distances: List[Tuple[float, QgsPointXY]],
    d_lo: float,
    d_hi: float,
    p_lo: QgsPointXY,
    p_hi: QgsPointXY,
) -> List[QgsPointXY]:
    """Extract the ordered point list along the line from arc-length d_lo to
    d_hi (with d_lo <= d_hi), starting at p_lo and ending at p_hi, including
    every original line vertex whose arc-length lies strictly between them.
    """
    out: List[QgsPointXY] = [p_lo]
    eps = 1e-7
    for d, pt in vertex_distances:
        if d <= d_lo + eps:
            continue
        if d >= d_hi - eps:
            break
        out.append(pt)
    out.append(p_hi)
    return out


def _extract_closed_wrap_path(
    vertex_distances: List[Tuple[float, QgsPointXY]],
    d_start: float,
    d_end: float,
    total_len: float,
    p_start: QgsPointXY,
    p_end: QgsPointXY,
) -> List[QgsPointXY]:
    """For a closed ring, build the path that wraps around the OTHER way from
    d_start to d_end (the complement of the direct sub-arc).
    """
    out: List[QgsPointXY] = [p_start]
    eps = 1e-7
    if d_start <= d_end:
        # Direct path covers (d_start, d_end).  Wrap covers the complement:
        # walk from d_start downward through 0 / total_len back down to d_end.
        for d, pt in reversed(vertex_distances):
            if d < d_start - eps and d > eps:
                out.append(pt)
        for d, pt in reversed(vertex_distances):
            if d > d_end + eps and d < total_len - eps:
                out.append(pt)
    else:
        # d_start > d_end: walk from d_start upward through total_len / 0
        # back up to d_end.
        for d, pt in vertex_distances:
            if d > d_start + eps and d < total_len - eps:
                out.append(pt)
        for d, pt in vertex_distances:
            if d < d_end - eps and d > eps:
                out.append(pt)
    out.append(p_end)
    return out


def _find_trace_path(
    start: QgsPointXY,
    end_cursor: QgsPointXY,
    layers,
    snap_tol: float,
) -> Optional[List[QgsPointXY]]:
    """
    TRUE edge-following trace (v8 — ArcGIS-Pro-like behaviour).

    Returns an ordered list of QgsPointXY that follows the actual geometry
    segments of the nearest visible feature from `start` to a point near
    `end_cursor`, or None if no suitable feature is found.

    Algorithm
    ---------
    1.  Search visible line/polygon layers for the feature whose boundary is
        nearest to `start`.  For polygons, the boundary is obtained via
        QgsGeometry.boundary() (preserves topology and ring structure).
    2.  For multi-part boundaries, pick the single ring / line part closest
        to `start` — this correctly handles exterior vs interior rings.
    3.  If the chosen part has curved segments (CircularString /
        CompoundCurve), expand them via segmentize() so the traced output
        faithfully follows the curve.  Straight LineStrings are left alone
        to avoid unnecessary densification.
    4.  Project BOTH `start` and `end_cursor` onto the line edges (NOT onto
        the nearest vertices) using lineLocatePoint() + interpolate().
    5.  Build the forward sub-path along the line from the start projection
        to the end projection, including every intermediate line vertex.
    6.  If the line is a closed ring, also build the wrap-around path and
        choose the shorter (most logical) of the two candidates.
    7.  Prepend `start` (the user's last committed point) as a lead-in vertex
        if it does not already coincide with the start projection, and
        deduplicate consecutive coincident points.

    The result is an edge-following, topology-respecting vertex list.
    """
    # ── 1. Find candidate feature ────────────────────────────────────────────
    mid = QgsPointXY((start.x() + end_cursor.x()) * 0.5,
                     (start.y() + end_cursor.y()) * 0.5)

    search_radius = _dist(start, end_cursor) + max(snap_tol * 4.0, snap_tol)
    try:
        search_rect = QgsGeometry.fromPointXY(mid).buffer(
            search_radius, 8
        ).boundingBox()
    except Exception:
        return None

    start_pt_geom = QgsGeometry.fromPointXY(start)
    # Cursor-driven selection (ArcGIS-Pro-like): the edge being traced is the
    # one UNDER/NEAREST the cursor, so the trace can turn onto a neighbouring
    # feature at junctions instead of freezing on the junction vertex of the
    # start-nearest feature.
    cursor_pt_geom = QgsGeometry.fromPointXY(end_cursor)

    best_line   = None     # traceable line geometry (full feature boundary)
    best_dist   = float("inf")

    for layer in layers:
        if not hasattr(layer, "getFeatures"):
            continue
        try:
            wkb = layer.wkbType()
            if wkb in (QgsWkbTypes.Type.NoGeometry, QgsWkbTypes.Type.Unknown):
                continue
            geom_type = QgsWkbTypes.geometryType(wkb)
            if geom_type not in (
                QgsWkbTypes.GeometryType.LineGeometry, QgsWkbTypes.GeometryType.PolygonGeometry
            ):
                continue
        except Exception:
            continue

        try:
            for feat in layer.getFeatures(
                QgsFeatureRequest().setFilterRect(search_rect)
            ):
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue
                trace_geom = _to_traceable_line(geom, geom_type)
                if trace_geom is None or trace_geom.isEmpty():
                    continue
                d = trace_geom.distance(cursor_pt_geom)
                if d < best_dist:
                    best_dist = d
                    best_line = trace_geom
        except Exception:
            continue

    if best_line is None:
        QgsMessageLog.logMessage(
            "_find_trace_path: no traceable feature found within search radius "
            f"({search_radius:.4f} map units) — falling back to straight line.",
            "AlignFeatures", Qgis.MessageLevel.Info,
        )
        return [start, end_cursor]  # straight-line fallback

    # Must be reasonably close to the trace target
    if best_dist > snap_tol * 3.0:
        QgsMessageLog.logMessage(
            f"_find_trace_path: nearest feature is {best_dist:.4f} map units away "
            f"(threshold={snap_tol * 3.0:.4f}).  "
            "Falling back to straight line.",
            "AlignFeatures", Qgis.MessageLevel.Info,
        )
        return [start, end_cursor]  # straight-line fallback

    # ── 2. Pick the single ring / part to trace along (nearest the CURSOR) ───
    line_part = _pick_closest_line_part(best_line, end_cursor)
    if line_part is None or line_part.isEmpty():
        QgsMessageLog.logMessage(
            "_find_trace_path: could not extract a single line part — straight-line fallback.",
            "AlignFeatures", Qgis.MessageLevel.Info,
        )
        return [start, end_cursor]

    # ── 3. Densify curved segments to capture true arc shape ─────────────────
    line_part = _segmentize_if_curved(line_part)

    total_len = 0.0
    try:
        total_len = line_part.length()
    except Exception:
        total_len = 0.0
    if total_len < 1e-10:
        QgsMessageLog.logMessage(
            "_find_trace_path: line part has zero length — straight-line fallback.",
            "AlignFeatures", Qgis.MessageLevel.Info,
        )
        return [start, end_cursor]

    # ── 4. Project both endpoints onto edges (NOT nearest vertex) ────────────
    try:
        d_start = line_part.lineLocatePoint(start_pt_geom)
        d_end   = line_part.lineLocatePoint(
            QgsGeometry.fromPointXY(end_cursor)
        )
    except Exception as _exc:
        QgsMessageLog.logMessage(
            f"_find_trace_path: lineLocatePoint failed ({_exc}) — straight-line fallback.",
            "AlignFeatures", Qgis.MessageLevel.Info,
        )
        return [start, end_cursor]
    if d_start is None or d_end is None or d_start < 0 or d_end < 0:
        QgsMessageLog.logMessage(
            "_find_trace_path: invalid line-locate result — straight-line fallback.",
            "AlignFeatures", Qgis.MessageLevel.Info,
        )
        return [start, end_cursor]

    try:
        proj_start_g = line_part.interpolate(d_start)
        proj_end_g   = line_part.interpolate(d_end)
    except Exception as _exc2:
        QgsMessageLog.logMessage(
            f"_find_trace_path: interpolate() failed ({_exc2}) — straight-line fallback.",
            "AlignFeatures", Qgis.MessageLevel.Info,
        )
        return [start, end_cursor]
    if (proj_start_g is None or proj_start_g.isEmpty() or
            proj_end_g is None or proj_end_g.isEmpty()):
        QgsMessageLog.logMessage(
            "_find_trace_path: empty projection result — straight-line fallback.",
            "AlignFeatures", Qgis.MessageLevel.Info,
        )
        return [start, end_cursor]

    proj_start = proj_start_g.asPoint()
    proj_end   = proj_end_g.asPoint()

    # ── 5. Build candidate forward (and reverse for closed rings) paths ──────
    vd = _line_vertex_distances(line_part)
    if len(vd) < 2:
        QgsMessageLog.logMessage(
            "_find_trace_path: vertex list too short — straight-line fallback.",
            "AlignFeatures", Qgis.MessageLevel.Info,
        )
        return [start, end_cursor]

    is_closed = _line_is_closed(line_part)

    if d_start <= d_end:
        forward = _extract_forward_path(vd, d_start, d_end, proj_start, proj_end)
    else:
        path_in_order = _extract_forward_path(
            vd, d_end, d_start, proj_end, proj_start
        )
        forward = list(reversed(path_in_order))

    candidates: List[List[QgsPointXY]] = [forward]

    if is_closed:
        wrap = _extract_closed_wrap_path(
            vd, d_start, d_end, total_len, proj_start, proj_end
        )
        if wrap and len(wrap) >= 2:
            candidates.append(wrap)

    def _arc_length(p: List[QgsPointXY]) -> float:
        return sum(_dist(p[i], p[i + 1]) for i in range(len(p) - 1))

    candidates = [c for c in candidates if c and len(c) >= 2]
    if not candidates:
        QgsMessageLog.logMessage(
            "_find_trace_path: no valid path candidates — straight-line fallback.",
            "AlignFeatures", Qgis.MessageLevel.Info,
        )
        return [start, end_cursor]

    # ── 6. Choose the shortest / most stable continuous path ─────────────────
    best_path = min(candidates, key=_arc_length)

    # ── 7. Connect to the user's last committed point + deduplicate ──────────
    # If the projected start differs from the user's last committed vertex,
    # prepend `start` as a lead-in so the trace visually connects to it.
    if _dist(best_path[0], start) > 1e-6:
        best_path.insert(0, start)

    deduped = [best_path[0]]
    for pt in best_path[1:]:
        if _dist(pt, deduped[-1]) > 1e-8:
            deduped.append(pt)

    if len(deduped) >= 2:
        return deduped
    QgsMessageLog.logMessage(
        "_find_trace_path: deduplicated path has < 2 points — straight-line fallback.",
        "AlignFeatures", Qgis.MessageLevel.Info,
    )
    return [start, end_cursor]


# ── Curve mode helpers ─────────────────────────────────────────────────────────

def _straight_line_points(
    p0: QgsPointXY,
    p1: QgsPointXY,
    n: int = 32,
) -> List[QgsPointXY]:
    """Densified straight segment from p0 to p1 — graceful fallback used by
    _arc_points() whenever the three-point geometry collapses (zero tangent,
    zero chord, or near-collinear)."""
    ax, ay = p0.x(), p0.y()
    bx, by = p1.x(), p1.y()
    pts = [p0]
    inv = 1.0 / (n + 1)
    for i in range(1, n + 1):
        t = i * inv
        pts.append(QgsPointXY(ax + t * (bx - ax),
                              ay + t * (by - ay)))
    pts.append(p1)
    return pts


def _arc_points(
    p_start: QgsPointXY,
    tangent: Tuple[float, float],
    p_end: QgsPointXY,
    n: int = 48,
    flip: int = 1,
) -> List[QgsPointXY]:
    """Build a circular arc from ``p_start`` to ``p_end`` whose tangent
    direction at ``p_start`` matches the unit vector ``tangent``.

    Adapted directly from Abanoub's ``arc_from_tangent`` design — a
    single tangent-anchored arc, no biarc, no through-point.  The
    workflow that drives this function is one click per arc:
    each new click adds one arc starting from the previously committed
    vertex with its tangent inherited from the previous segment's exit
    direction (computed by ``AlignmentPathTool._incoming_tangent()``).

    Parameters
    ----------
    p_start
        Start of the arc (the last committed vertex of the polyline).
    tangent
        Unit direction vector ``(tx, ty)`` at ``p_start``.  Callers
        should pre-normalise — ``_incoming_tangent()`` already does.
    p_end
        End of the arc (the new click, or cursor position in preview).
    n
        Minimum number of segments along the arc.  Long sweeps get more
        subdivisions automatically (~1 segment per 6°).
    flip
        Side selector: ``+1`` curves the arc to the LEFT of the tangent
        direction, ``-1`` curves it to the RIGHT.  Bound to the **F**
        key in the map tool so the user can flip mid-stroke if the arc
        bulges the wrong way.

    Returns
    -------
    List[QgsPointXY]
        ``seg_count + 1`` densified vertices from p_start to p_end
        along the arc, or a straight-line densification when the
        geometry degenerates (tangent parallel to chord, zero chord).
    """
    EPS = 1e-10

    tx, ty = tangent

    # Perpendicular normal, flipped to choose the arc side.
    # +flip → centre on the LEFT  of the tangent direction (CCW sweep).
    # −flip → centre on the RIGHT of the tangent direction (CW  sweep).
    nx, ny = -ty * flip, tx * flip

    # Vector from p_end → p_start, used in the closed-form radius solve.
    ax = p_start.x() - p_end.x()
    ay = p_start.y() - p_end.y()
    denom = 2.0 * (ax * nx + ay * ny)

    if abs(denom) < EPS:
        # Tangent parallel/anti-parallel to chord → arc collapses to a
        # straight line.  Graceful fallback so the preview never blanks.
        return _straight_line_points(p_start, p_end, n)

    # Signed radius (negative when the arc swings the other way).
    r  = -(ax * ax + ay * ay) / denom
    cx = p_start.x() + r * nx
    cy = p_start.y() + r * ny
    ar = abs(r)

    a1 = math.atan2(p_start.y() - cy, p_start.x() - cx)
    a2 = math.atan2(p_end.y()   - cy, p_end.x()   - cx)

    # Sweep direction follows the sign of r so the arc actually bulges
    # toward the perpendicular-normal side chosen above.
    if r > 0.0:
        da = (a2 - a1) % (2.0 * math.pi)
        if da > math.pi:
            da -= 2.0 * math.pi
    else:
        da = -((a1 - a2) % (2.0 * math.pi))
        if da < -math.pi:
            da += 2.0 * math.pi

    # Adaptive densification: at least n segments, plus ~1 per 6° so a
    # long sweep never looks polygonal.
    seg_count = max(n, int(math.ceil(abs(da) / math.radians(6.0))))
    return [
        QgsPointXY(
            cx + ar * math.cos(a1 + da * i / seg_count),
            cy + ar * math.sin(a1 + da * i / seg_count),
        )
        for i in range(seg_count + 1)
    ]


# ── Main map tool ──────────────────────────────────────────────────────────────

class AlignmentPathTool(QgsMapTool):
    """
    Interactive polyline drawing tool with vertex snapping and trace mode.

    Signals
    -------
    pathFinished(QgsGeometry)  – user finished drawing
    pathUpdated(QgsGeometry)   – emitted on each new vertex
    drawingCancelled()         – user cancelled

    Drawing-completion logic (this revision)
    ----------------------------------------
    QGIS delivers a double-click as THREE events, in this order:

        canvasReleaseEvent   (release #1 — appends the final vertex)
        canvasDoubleClickEvent (finishes the path)
        canvasReleaseEvent   (release #2 — must be swallowed)

    The logic below is built around that ordering so that:
      * a path can never finish with fewer than 3 points,
      * a slow/deliberate second click in the same spot does NOT finish
        (only a genuine fast double-click does — see the time-window guard),
      * the trailing release #2 of a double-click never leaves a dangling
        vertex or a duplicate,
      * the very first click ALWAYS starts a fresh session, even if it
        snapped to a distant vertex.
    """

    pathFinished     = pyqtSignal(object)
    pathUpdated      = pyqtSignal(object)
    drawingCancelled = pyqtSignal()

    _LINE_COLOR    = QColor(0, 120, 215, 230)
    _LINE_WIDTH    = 2
    _PREVIEW_COLOR = QColor(0, 120, 215, 100)
    _TRACE_COLOR   = QColor(0, 200, 180, 220)    # cyan-teal for trace preview
    _SNAP_COLOR    = QColor(255, 165, 0)
    _CURVE_COLOR   = QColor(220, 80, 220, 220)   # magenta for curve preview

    _DEFAULT_SNAP_PX = 12

    # ── Drawing-completion tuning (CHANGED / NEW class attributes) ─────────────
    # FIX 1: double-click detection radius reduced from the old hard-coded 8 px
    #        to 5 px so two nearby-but-distinct clicks are not mistaken for a
    #        double-click.
    _DOUBLE_CLICK_PX = 5
    # FIX 1: the "small threshold" that prevents accidental finishes — a second
    #        click only counts as the trailing half of a double-click if it
    #        arrives within this many milliseconds of the previous click.  A
    #        slow, deliberate second click in the same spot will therefore add
    #        a vertex instead of finishing.  (Qt's default double-click interval
    #        is ~400 ms; tune here if needed.)
    _DOUBLE_CLICK_MS = 400
    # FIX 3: configurable trace-preview tolerance multiplier (was hard-coded 4).
    _TRACE_TOL_MULTIPLIER = 4

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self._points        = []
        self._is_drawing    = False
        # FIX 3: explicit session-state flag, separate from the per-vertex
        # _is_drawing.  True between _start_drawing() and _finish()/_cancel().
        self._drawing_active = False
        self._last_click_pt = None
        # FIX 1: timestamp of the last committed click, for the double-click
        # time-window check.  0.0 means "no click yet".
        self._last_click_time = 0.0
        # Set by _finish() so the trailing release #2 of a finishing
        # double-click is swallowed instead of starting a new session.
        self._just_finished = False
        self._snap_pt: Optional[QgsPointXY] = None
        self._trace_mode    = False
        self._trace_path: Optional[List[QgsPointXY]] = None
        # Undo stack — each entry is a snapshot of self._points taken
        # immediately BEFORE a click is committed.  Backspace / Ctrl+Z
        # pops the last snapshot and restores it.
        self._undo_stack: List[List[QgsPointXY]] = []
        # Curve mode state (C key toggle — Abanoub-style tangent-arc):
        # one click per arc, tangent inherited from previous segment.
        self._curve_mode  = False
        self._arc_flip    = 1                              # F key toggles +1 / −1
        self._last_map_pt: Optional[QgsPointXY] = None     # last cursor pos, for F-key preview refresh

        # Committed rubber band
        self._rb = QgsRubberBand(canvas, QgsWkbTypes.GeometryType.LineGeometry)
        self._rb.setColor(self._LINE_COLOR)
        self._rb.setWidth(self._LINE_WIDTH)

        # Normal preview band (last point → cursor)
        self._rb_preview = QgsRubberBand(canvas, QgsWkbTypes.GeometryType.LineGeometry)
        self._rb_preview.setColor(self._PREVIEW_COLOR)
        self._rb_preview.setWidth(self._LINE_WIDTH)
        self._rb_preview.setLineStyle(Qt.PenStyle.DashLine)

        # Trace preview band (highlights the traced path)
        self._rb_trace = QgsRubberBand(canvas, QgsWkbTypes.GeometryType.LineGeometry)
        self._rb_trace.setColor(self._TRACE_COLOR)
        self._rb_trace.setWidth(3)
        self._rb_trace.setLineStyle(Qt.PenStyle.SolidLine)

        # Curve preview band (magenta arc preview while in Curve mode)
        self._rb_curve = QgsRubberBand(canvas, QgsWkbTypes.GeometryType.LineGeometry)
        self._rb_curve.setColor(self._CURVE_COLOR)
        self._rb_curve.setWidth(2)
        self._rb_curve.setLineStyle(Qt.PenStyle.DashLine)

        # Snap marker
        self._snap_marker = QgsVertexMarker(canvas)
        self._snap_marker.setColor(self._SNAP_COLOR)
        self._snap_marker.setIconType(QgsVertexMarker.IconType.ICON_BOX)
        self._snap_marker.setIconSize(10)
        self._snap_marker.setPenWidth(2)
        self._snap_marker.setVisible(False)

        # Trace mode indicator marker (teal circle)
        self._trace_marker = QgsVertexMarker(canvas)
        self._trace_marker.setColor(self._TRACE_COLOR)
        self._trace_marker.setIconType(QgsVertexMarker.IconType.ICON_CIRCLE)
        self._trace_marker.setIconSize(14)
        self._trace_marker.setPenWidth(2)
        self._trace_marker.setVisible(False)

        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

        # Event filter — intercepts canvas-level key events in QGIS 4 / Qt6.
        # QGIS 4 consumes key events at the canvas before the tool's
        # keyPressEvent is called, so we install a filter (same pattern used
        # by Abanoub's ArcMapTool) to catch Backspace reliably.
        canvas.installEventFilter(self)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def trace_mode(self) -> bool:
        return self._trace_mode

    @trace_mode.setter
    def trace_mode(self, value: bool):
        self._trace_mode = value
        if not value:
            self._rb_trace.reset(QgsWkbTypes.GeometryType.LineGeometry)
            self._trace_path = None
            self._trace_marker.setVisible(False)
        QgsMessageLog.logMessage(
            f"Trace mode: {'ON' if value else 'OFF'}",
            "AlignFeatures", Qgis.MessageLevel.Info,
        )

    # ── Event filter (QGIS 4 / Qt6 Backspace fix) ────────────────────────────

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """Intercept canvas-level key events so Backspace reaches keyPressEvent
        even on QGIS 4 / Qt6, where the canvas consumes key events before the
        tool's keyPressEvent is invoked.  Mirrors Abanoub's ArcMapTool design.
        """
        try:
            from qgis.PyQt.QtCore import QEvent
            if obj is self.canvas and event.type() == QEvent.Type.KeyPress:
                self.keyPressEvent(event)
                if event.isAccepted():
                    return True
        except Exception:
            pass
        return super().eventFilter(obj, event)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def activate(self):
        super().activate()
        self._reset()
        self.canvas.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        # FIX 4: clear, action-oriented instruction message.
        QgsMessageLog.logMessage(
            "Drawing started - click to add vertices, double-click or press "
            "Enter to finish",
            "AlignFeatures", Qgis.MessageLevel.Info,
        )
        # Keep the detailed hint as well (cancel / trace toggle).
        QgsMessageLog.logMessage(
            "Right-click or Esc = cancel.  T = toggle trace mode.",
            "AlignFeatures", Qgis.MessageLevel.Info,
        )

    def deactivate(self):
        self.canvas.removeEventFilter(self)
        self._clear_bands()
        self._snap_marker.setVisible(False)
        self._trace_marker.setVisible(False)
        super().deactivate()

    # ── Snapping helpers ───────────────────────────────────────────────────────

    def _snap_tolerance_map_units(self) -> float:
        try:
            cfg = QgsProject.instance().snappingConfig()
            if cfg.enabled():
                try:
                    unit = cfg.toleranceUnit()
                except AttributeError:
                    unit = QgsTolerance_ProjectUnits
                if unit == QgsTolerance_ProjectUnits:
                    return cfg.tolerance()
        except Exception:
            pass
        try:
            return self._DEFAULT_SNAP_PX * self.canvas.mapUnitsPerPixel()
        except Exception:
            return self._DEFAULT_SNAP_PX

    def _find_snap_point(self, map_pt: QgsPointXY) -> Optional[QgsPointXY]:
        # Try QgsSnappingUtils first
        try:
            snap_utils = self.canvas.snappingUtils()
            snap_utils.prepareIndexStartingIfNeeded()
            match = snap_utils.snapToMap(map_pt)
            if match.isValid() and match.type() == QgsPointLocator.Type.Vertex:
                return match.point()
        except Exception:
            pass

        # Manual fallback
        tol = self._snap_tolerance_map_units()
        best_d  = float("inf")
        best_pt = None

        for layer in QgsProject.instance().mapLayers().values():
            if not hasattr(layer, "getFeatures"):
                continue
            try:
                if layer.wkbType() in (QgsWkbTypes.Type.NoGeometry, QgsWkbTypes.Type.Unknown):
                    continue
            except Exception:
                continue
            try:
                search_rect = QgsGeometry.fromPointXY(map_pt).buffer(tol, 4).boundingBox()
                for feat in layer.getFeatures(QgsFeatureRequest().setFilterRect(search_rect)):
                    geom = feat.geometry()
                    if geom is None or geom.isEmpty():
                        continue
                    for v in geom.vertices():
                        vpt = QgsPointXY(v.x(), v.y())
                        d = math.hypot(map_pt.x() - vpt.x(), map_pt.y() - vpt.y())
                        if d < best_d and d <= tol:
                            best_d  = d
                            best_pt = vpt
            except Exception:
                continue

        return best_pt

    def _update_snap(self, map_pt: QgsPointXY):
        snap = self._find_snap_point(map_pt)
        self._snap_pt = snap
        if snap is not None:
            self._snap_marker.setCenter(snap)
            self._snap_marker.setVisible(True)
        else:
            self._snap_marker.setVisible(False)

    def _visible_layers(self):
        return [
            lyr for lyr in QgsProject.instance().mapLayers().values()
            if hasattr(lyr, "getFeatures")
        ]

    # ── Curve mode helpers ─────────────────────────────────────────────────────

    def _incoming_tangent(self) -> Optional[Tuple[float, float]]:
        """Unit-vector tangent at the last committed vertex, derived from
        the direction of the previous segment.  Returns ``None`` when the
        path has fewer than two vertices.

        Because arc segments are stored as densified vertices, the last
        two points of an arc record give the arc's exit tangent
        naturally — so the same calculation works whether the previous
        segment was a straight line or a curve.
        """
        if len(self._points) < 2:
            return None
        prev = self._points[-2]
        here = self._points[-1]
        dx = here.x() - prev.x()
        dy = here.y() - prev.y()
        L  = math.hypot(dx, dy)
        if L < 1e-9:
            return None
        return (dx / L, dy / L)

    def _render_curve_preview(self, cursor_pt: QgsPointXY) -> None:
        """Draw the live tangent-arc preview into the curve rubber band.

        Called from ``canvasMoveEvent`` on every mouse move while curve
        mode is active, and from ``keyPressEvent`` whenever **F** flips
        the arc side so the user sees the new direction immediately
        without having to wiggle the mouse.
        """
        self._rb_curve.reset(QgsWkbTypes.GeometryType.LineGeometry)
        if not self._points:
            return
        tangent = self._incoming_tangent()
        if tangent is not None:
            for pt in _arc_points(self._points[-1], tangent, cursor_pt,
                                  flip=self._arc_flip):
                self._rb_curve.addPoint(pt)
        else:
            # No tangent yet → straight-line preview (first curve click
            # always lays down a line to seed the tangent).
            self._rb_curve.addPoint(self._points[-1])
            self._rb_curve.addPoint(cursor_pt)

    # ── Trace mode ─────────────────────────────────────────────────────────────

    def _update_trace_preview(self, map_pt: QgsPointXY):
        """Compute and display the trace path from last committed point to cursor."""
        self._rb_trace.reset(QgsWkbTypes.GeometryType.LineGeometry)
        self._trace_path = None

        if not self._points:
            return

        # FIX 3 / FIX 7: use the configurable class attribute directly (it is now
        # always defined on the class, so no getattr fallback is required).
        tol = self._snap_tolerance_map_units() * self._TRACE_TOL_MULTIPLIER

        # Free trace movement: use the RAW cursor position, not the vertex-
        # snapped point.  _find_trace_path projects the cursor onto the edge
        # continuously (lineLocatePoint), so the trace end follows the mouse
        # in every direction instead of locking onto the nearest vertex.
        cursor_pt = map_pt
        trace = _find_trace_path(
            self._points[-1], cursor_pt, self._visible_layers(), tol
        )

        if trace and len(trace) >= 2:
            # A real edge-following trace was found.
            self._trace_path = trace
            for pt in trace:
                self._rb_trace.addPoint(pt)
            self._trace_marker.setCenter(trace[-1])
            self._trace_marker.setVisible(True)
        else:
            # FIX 7: _find_trace_path found no usable edge (or returned too few
            # points).  Fall back to a straight line from the last committed
            # vertex to the cursor, drawn on the trace band, and store it as the
            # active trace path so a click still commits a valid segment.
            self._trace_marker.setVisible(False)
            cursor_pt = map_pt   # raw cursor — no vertex pinning in trace mode
            fallback = [self._points[-1], cursor_pt]
            # Guard against a zero-length fallback (cursor sitting exactly on the
            # last vertex) — leave _trace_path None so nothing degenerate commits.
            if _dist(fallback[0], fallback[1]) > 1e-9:
                self._trace_path = fallback
                for pt in fallback:
                    self._rb_trace.addPoint(pt)

    # ── Canvas events ──────────────────────────────────────────────────────────

    def canvasMoveEvent(self, event):
        map_pt = QgsPointXY(event.mapPoint())
        self._update_snap(map_pt)

        if not self._is_drawing or not self._points:
            return

        cursor_pt = self._snap_pt if self._snap_pt is not None else map_pt
        self._last_map_pt = cursor_pt   # remember for F-key preview refresh

        if self._trace_mode:
            self._update_trace_preview(map_pt)
            # Hide normal preview when trace is active
            self._rb_preview.reset(QgsWkbTypes.GeometryType.LineGeometry)
            self._rb_curve.reset(QgsWkbTypes.GeometryType.LineGeometry)
        elif self._curve_mode and self._is_drawing:
            self._rb_trace.reset(QgsWkbTypes.GeometryType.LineGeometry)
            self._trace_marker.setVisible(False)
            self._rb_preview.reset(QgsWkbTypes.GeometryType.LineGeometry)
            self._render_curve_preview(cursor_pt)
        else:
            self._rb_trace.reset(QgsWkbTypes.GeometryType.LineGeometry)
            self._trace_marker.setVisible(False)
            self._rb_curve.reset(QgsWkbTypes.GeometryType.LineGeometry)
            self._rb_preview.reset(QgsWkbTypes.GeometryType.LineGeometry)
            self._rb_preview.addPoint(self._points[-1])
            self._rb_preview.addPoint(cursor_pt)

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        # FIX 1: swallow the trailing release (#2) of a double-click that has
        # just finished the path via canvasDoubleClickEvent.  Without this the
        # second release would be seen as a brand-new first click and leave a
        # dangling vertex.
        if self._just_finished:
            self._just_finished = False
            return

        map_pt = QgsPointXY(event.mapPoint())
        pt = self._snap_pt if self._snap_pt is not None else map_pt

        now = time.monotonic()

        # FIX 6: the very first click ALWAYS starts a fresh drawing session and
        # is always registered — even if it snapped to a distant vertex.  We
        # bypass the double-click guard entirely here because there is nothing
        # to finish yet, and any stale click-tracking state from a previous
        # session must never swallow the first click.
        if not self._points:
            self._start_drawing()
            self._undo_stack.append(list(self._points))  # snapshot before first click
            self._points.append(pt)
            self._last_click_pt   = pt
            self._last_click_time = now
            self._is_drawing      = True
            self._rebuild_rb()
            return

        # FIX 1: double-click detection.  This release is treated as the
        # trailing half of a double-click ONLY when it is BOTH
        #   (a) within _DOUBLE_CLICK_PX pixels of the previous click  (was 8 px),
        #   (b) within the _DOUBLE_CLICK_MS time window of it (the threshold
        #       that stops a slow deliberate second click from finishing).
        # When that pattern is detected we FINISH only if there are already at
        # least 3 points (FIX 1); otherwise we simply swallow the release so it
        # cannot append a duplicate vertex.  (canvasDoubleClickEvent normally
        # performs the finish first; this branch is a platform-safe fallback
        # plus the duplicate guard for the < 3 case.)
        if self._last_click_pt is not None:
            canvas_last = self.toCanvasCoordinates(self._last_click_pt)
            dist_px     = (canvas_last - event.pos()).manhattanLength()
            within_time = (now - self._last_click_time) <= (self._DOUBLE_CLICK_MS / 1000.0)
            if dist_px < self._DOUBLE_CLICK_PX and within_time:
                if len(self._points) >= 3:
                    self._finish()
                return

        # Normal single click — record tracking state, then commit.
        self._last_click_pt   = pt
        self._last_click_time = now

        if self._trace_mode and self._trace_path and len(self._points) >= 1:
            # Commit all trace points at once (skip first — already committed)
            self._undo_stack.append(list(self._points))   # snapshot before trace commit
            for trace_pt in self._trace_path[1:]:
                self._points.append(trace_pt)
            self._trace_path = None
            self._rb_trace.reset(QgsWkbTypes.GeometryType.LineGeometry)
        elif self._curve_mode and self._is_drawing and self._points:
            # Abanoub-style: one click per arc.  Tangent comes from the
            # exit direction of the previous segment.  If there's no
            # tangent yet (only one vertex committed) just lay down a
            # straight segment — same as line mode for that single click,
            # which gives us the seed direction for the NEXT arc.
            self._undo_stack.append(list(self._points))   # snapshot before arc commit
            tangent = self._incoming_tangent()
            if tangent is not None:
                arc_pts = _arc_points(
                    self._points[-1], tangent, pt,
                    flip=self._arc_flip,
                )
                for arc_pt in arc_pts[1:]:   # skip first — already in _points
                    self._points.append(arc_pt)
            else:
                # No tangent yet → straight click, builds the seed
                # direction for subsequent arcs.
                self._points.append(pt)
            self._rb_curve.reset(QgsWkbTypes.GeometryType.LineGeometry)
        else:
            self._undo_stack.append(list(self._points))   # snapshot before normal click
            self._points.append(pt)

        self._is_drawing     = True
        self._drawing_active = True
        self._rebuild_rb()
        if len(self._points) >= 2:
            self.pathUpdated.emit(QgsGeometry.fromPolylineXY(self._points))

    def canvasDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        # FIX 2: never finish with fewer than 3 points.  (The count here
        # includes the final vertex that release #1 of this double-click just
        # appended, so >= 3 means at least two deliberate vertices plus the
        # closing click.)
        if len(self._points) < 3:
            return

        # Remove the duplicate vertex that release #1 appended if it coincides
        # with the previous vertex (i.e. the user double-clicked on an existing
        # point rather than at a new location).
        if len(self._points) >= 2:
            last = self._points[-1]
            prev = self._points[-2]
            if (abs(last.x() - prev.x()) < 1e-10 and
                    abs(last.y() - prev.y()) < 1e-10):
                self._points.pop()

        self._finish()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Delete):
            self._cancel()
        elif event.key() == Qt.Key.Key_Backspace or (
            event.key() == Qt.Key.Key_Z
            and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        ):
            # ── Undo last committed click (Abanoub-style) ──────────────
            # Each click snapshot is pushed onto _undo_stack just before
            # committing, so popping it restores the previous _points list.
            if self._undo_stack:
                self._points = self._undo_stack.pop()
                self._rebuild_rb()
                # Sync _is_drawing: once we have at least one point the tool
                # is still in drawing mode.
                self._is_drawing = bool(self._points)
                n = len(self._points)
                QgsMessageLog.logMessage(
                    f"Undo — {n} point(s) remaining.",
                    "AlignFeatures", Qgis.MessageLevel.Info,
                )
                event.accept()
            else:
                event.ignore()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Enter is an explicit, unambiguous finish — 2 points is enough.
            if len(self._points) >= 2:
                self._finish()
        elif event.key() == Qt.Key.Key_T:
            # Toggle trace mode
            self.trace_mode = not self._trace_mode
        elif event.key() == Qt.Key.Key_C:
            # Toggle curve mode
            self._curve_mode = not self._curve_mode
            self._arc_flip   = 1       # reset side when entering/leaving
            self._rb_curve.reset(QgsWkbTypes.GeometryType.LineGeometry)
            # If we just turned curve mode ON and the cursor is over the
            # canvas, render an initial preview immediately.
            if self._curve_mode and self._last_map_pt is not None:
                self._render_curve_preview(self._last_map_pt)
            QgsMessageLog.logMessage(
                f"Curve mode: {'ON' if self._curve_mode else 'OFF'}"
                + ("  (F = flip arc side)" if self._curve_mode else ""),
                "AlignFeatures", Qgis.MessageLevel.Info,
            )
        elif event.key() == Qt.Key.Key_F and self._curve_mode:
            # Flip the side the arc bulges to.  Refresh preview immediately
            # so the user doesn't have to nudge the mouse to see the change.
            self._arc_flip *= -1
            if self._last_map_pt is not None and self._is_drawing:
                self._render_curve_preview(self._last_map_pt)
            QgsMessageLog.logMessage(
                f"Arc side: {'left' if self._arc_flip == 1 else 'right'}",
                "AlignFeatures", Qgis.MessageLevel.Info,
            )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _start_drawing(self):
        """FIX 5: Establish a clean slate at the start of every drawing session.

        Called automatically on the first click so that no stale points, rubber
        bands, trace path, or click-tracking state from a previous (finished or
        cancelled) session can leak into the new path.  This makes each drawing
        session fully independent and is what guarantees the first click always
        behaves predictably.
        """
        self._clear_bands()
        self._points          = []
        self._undo_stack      = []   # clear undo history for the new session
        self._trace_path      = None
        self._last_click_pt   = None
        self._last_click_time = 0.0
        self._snap_pt         = None
        self._just_finished   = False
        self._is_drawing      = True
        self._drawing_active  = True
        self._arc_flip        = 1
        self._last_map_pt     = None
        QgsMessageLog.logMessage(
            "Drawing session started.", "AlignFeatures", Qgis.MessageLevel.Info,
        )

    def _rebuild_rb(self):
        self._rb.reset(QgsWkbTypes.GeometryType.LineGeometry)
        for pt in self._points:
            self._rb.addPoint(pt)

    def _finish(self):
        if len(self._points) < 2:
            QgsMessageLog.logMessage(
                "Need at least 2 points.", "AlignFeatures", Qgis.MessageLevel.Warning
            )
            return
        geom   = QgsGeometry.fromPolylineXY(self._points)
        length = geom.length()
        n      = len(self._points)
        QgsMessageLog.logMessage(
            f"Path finished: {n} vertices, length={length:.4f} map units.",
            "AlignFeatures", Qgis.MessageLevel.Info,
        )
        self._clear_bands()
        self._reset()
        # FIX 1: mark that a finish just happened so the trailing release #2 of
        # the finishing double-click is swallowed by canvasReleaseEvent.
        self._just_finished  = True
        self._drawing_active = False
        self.pathFinished.emit(geom)

    def _cancel(self):
        self._clear_bands()
        self._reset()
        self._drawing_active = False
        self.drawingCancelled.emit()

    def _clear_bands(self):
        self._rb.reset(QgsWkbTypes.GeometryType.LineGeometry)
        self._rb_preview.reset(QgsWkbTypes.GeometryType.LineGeometry)
        self._rb_trace.reset(QgsWkbTypes.GeometryType.LineGeometry)
        self._rb_curve.reset(QgsWkbTypes.GeometryType.LineGeometry)
        self._snap_marker.setVisible(False)
        self._trace_marker.setVisible(False)

    def _reset(self):
        self._points          = []
        self._undo_stack      = []   # clear undo history on reset
        self._is_drawing      = False
        self._drawing_active  = False
        self._last_click_pt   = None
        self._last_click_time = 0.0
        # NOTE: _just_finished is intentionally NOT cleared here — _finish()
        # calls _reset() and then sets _just_finished = True, and we must not
        # stomp that flag before the trailing release is swallowed.  It is
        # cleared in canvasReleaseEvent and in _start_drawing().
        self._snap_pt         = None
        self._trace_path      = None
        self._arc_flip        = 1
        self._last_map_pt     = None
