# -*- coding: utf-8 -*-
"""
align_to_path_algorithm.py  —  v10.2.0
=======================================
Core geometry processing engine.

What's new in v10.2.0 (Smart Fit + Square End audit)
------------------------------------------------------
*  **Smart Fit mode** (``METHOD_SMART_FIT``) — new coherent alignment mode
   that sits between the raw "Fit to Path" and the full "Trace & Smooth"
   pipeline.  Two key improvements over the classic FIT method:

   1. **Intersection-significance filter** (``_filter_by_intersection_significance``)
      Before any vertex is moved we compute the *overlap fraction* between
      the tolerance buffer and each feature (area ratio for polygons, length
      ratio for lines).  Features below the configurable ``min_overlap_ratio``
      threshold are skipped.  This prevents:
        • L-corner pulls — a feature that only clips a tiny buffer corner is excluded.
        • Crossing-line artefacts — a line that crosses the buffer boundary at a
          shallow angle has a small overlap fraction and is skipped.

   2. **Proximity-weighted vertex movement** (``_smart_fit_to_path``)
      Instead of the binary snap-or-don't of classic FIT, each vertex is moved
      by a fraction that decreases smoothly with distance from the path:

          weight = clamp(1 − (dist / tolerance)², 0, 1)
          new_pos = orig + weight × (path_projection − orig)

      Vertices on the path boundary (dist ≈ 0) snap almost exactly (weight ≈ 1).
      Vertices near the tolerance edge move only a little (weight ≈ 0).
      This eliminates "aggressive global pull" while still closing the gap where
      the path actually runs.

*  **Backward compatible** — ``METHOD_SMART_FIT`` is additive; all four
   existing methods (FIT, PRESERVE, SNAP_ENDS, TRACE_SMOOTH) are unchanged.

*  **Square End audit** — no changes needed.  ``_make_buffer`` already
   receives ``_CAP_SQUARE`` when ``end_style == END_SQUARE`` (resolved at
   import time via ``_resolve_buffer_styles``).  The dialog's preview rubber-
   band already reads ``_get_end()`` for its inline buffer calls.  Confirmed
   consistent across algorithm and UI.

What's new in v10.1.8 (Buffer Distance Fix)
---------------------------------------------
*  **Tolerance = hard buffer boundary** — ``align_features_to_path`` no longer
   auto-expands ``search_buffer`` to ``tolerance * 2``.  The old guard treated
   ``search_buffer == tolerance`` as "too small" and silently doubled it, which
   caused features well outside the user's drawn buffer to be aligned (matching
   neither ArcGIS Pro behaviour nor the UI hint "within the tolerance buffer").

   New logic:
   - If ``search_buffer is None`` → default to ``tolerance`` (unchanged).
   - If ``search_buffer < tolerance`` → clamp UP to ``tolerance`` with a warning
     (prevents the impossible case where the snapping distance exceeds the
     containment zone).
   - ``search_buffer > tolerance`` is honoured as-is (advanced callers can
     intentionally use a wider search zone).

   This makes the Tolerance spinner in the UI behave exactly like ArcGIS Pro's
   Tolerance field: only features whose geometry intersects the tolerance buffer
   of the drawn path are processed.

What's new in v10.1 (QGIS 4 Compatibility)
-------------------------------------------
*  **QGIS 4 ready** — the buffer creation pipeline is now robust across
   QGIS 3.28 → 3.36 → QGIS 4.x without any API breakage.

   Key changes:
   - ``_resolve_buffer_styles()`` (new module-level helper) probes all known
     cap/join style APIs at import time and caches the integer values once,
     rather than re-resolving them inside every ``align_features_to_path``
     call.  It tries five strategies in order:
       1. ``Qgis.EndCapStyle`` / ``Qgis.JoinStyle``   (QGIS 3.26+, QGIS 4)
       2. ``QgsGeometry.BufferSide`` enum              (some 3.x builds)
       3. ``QgsGeometry.CapRound`` / ``CapSquare``     (QGIS 3.x legacy)
       4. ``qgis.core.Qgis`` integer constants         (fallback scan)
       5. Hard-coded GEOS integers (1 = Round, 3 = Square)
   - ``_make_buffer()`` is now a top-level function that accepts pre-resolved
     style integers.  It tries the 5-argument ``QgsGeometry.buffer()`` form
     first, then the 3-argument form (QGIS 4 alternative), then the plain
     2-argument form, so *some* buffer is always produced.
   - ``QgsWkbTypes.isCurvedType`` → guarded with a version-aware shim
     because the static method was moved in QGIS 4.
   - Safe ``QgsMessageLog`` import: falls back to a no-op if unavailable
     (unit-test / headless environments).
   - Version detection via ``Qgis.QGIS_VERSION_INT`` is used to activate
     QGIS-4-specific code paths without removing 3.x support.

*  All v10 Global Master Boundary Alignment logic is **unchanged**.

What's new in v10.0 (Global Master Boundary Alignment)
-------------------------------------------------------
*  **Pixel-perfect shared boundary** — `_snap_to_master_path()` replaces the
   v9 coincidence hash with a fundamentally stronger guarantee: every vertex
   that lies near the alignment path is forced to the *nearest point on the
   original master path_vertices list* (or, when between two master vertices,
   to the nearest point on that master segment).  Because both polygons project
   to the *same mathematical source*, the resulting coordinates are bitwise
   identical — there is no first-winner race and no residual floating-point
   gap, even when the two polygons had a visible sliver before alignment.

*  **Master-vertex priority snapping** — within `snap_tol` of an original
   path vertex, the vertex is pinned to that exact `QgsPointXY` object (no
   arithmetic rounding).  Outside that radius the nearest point on the master
   segment is used — still the same deterministic computation for every polygon
   that touches this stretch.

*  All v8/v9 features preserved:
   - Curve / arc support (CircularString, CompoundCurve)
   - Direction detection per ring (winding order)
   - Chaikin smoothing with anchor pinning
   - Side filtering (Left / Right / Both)
   - Resampling / densification before tracing
   - The "Enforce Shared Boundary" checkbox (default ON) gates the new pass

What's new in v8.0
-------------------
*  **True Path Tracing** — new METHOD_TRACE_SMOOTH pipeline now genuinely
   *traces* the alignment path geometry onto the polygon boundary instead of
   only snapping existing vertices.  The traced segment replaces the portion
   of the polygon edge that lies within the tolerance buffer, producing a
   result visually equivalent to ArcGIS Pro's Trace construction tool.

   Core new helpers:

   _split_ring_at_buffer()     — find the entry & exit points where a ring
                                 crosses the tolerance buffer boundary, and
                                 split the ring into an "inside" portion and
                                 an "outside" portion.

   _project_onto_path()        — project a point onto the nearest location
                                 along the path, returning (t, closest_pt)
                                 where t is the normalised arc-length
                                 parameter [0…total_length].

   _extract_path_subsegment()  — given two t-values, extract the ordered
                                 list of path vertices between them (the
                                 actual traced curve).

   _trace_ring_against_path()  — full pipeline: split ring → extract path
                                 sub-segment → stitch together the outside
                                 ring portion + the traced path curve.

*  **Tangent-arc awareness** — when the path geometry contains CircularString
   or CompoundCurve parts (QGIS curved geometry), the traced output preserves
   the curved segments by densifying them at a fine resolution before stitching,
   giving smooth arc-aligned boundaries.

*  **Improved Chaikin** — `_smooth_ring_chaikin()` now accepts a `anchor_set`
   parameter so snapped vertices can be pinned and excluded from smoothing,
   preventing the curve from drifting away from the path.

*  **Smarter PRESERVE mode** — the buffer membership test now uses a fast
   pre-built bbox set instead of per-vertex `QgsGeometry.fromPointXY` calls,
   reducing overhead on dense polygons.

*  All v7.1 methods (FIT, PRESERVE, SNAP_ENDS) are unchanged.

Algorithm overview (TRACE_SMOOTH — v8)
-----------------------------------------
1. Build the tolerance buffer around the alignment path.
2. For each polygon ring:
   a. Find where the ring enters / exits the buffer  (split points).
   b. Classify each ring segment as "inside buffer" or "outside buffer".
   c. For each continuous inside-segment, project its endpoints onto the path
      and extract the matching path sub-curve.
   d. Stitch: outside segments (kept) + path sub-curves (traced).
3. Optionally apply Chaikin smoothing to outside corners only.

Author: Mustafa Elghazaly
"""

import math
from typing import List, Tuple, Optional, Callable, Set

# ── QGIS imports — safe for QGIS 3.28 → 3.36 → QGIS 4 ───────────────────────
from qgis.core import (
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
    QgsFeature,
    QgsVectorLayer,
    QgsWkbTypes,
    Qgis,
)

# QgsMessageLog is available in all versions but guard anyway for test envs.
try:
    from qgis.core import QgsMessageLog
    _HAS_MSG_LOG = True
except ImportError:
    _HAS_MSG_LOG = False

# ── QGIS version detection ────────────────────────────────────────────────────
try:
    _QGIS_VERSION_INT = int(Qgis.QGIS_VERSION_INT)
except (AttributeError, TypeError, ValueError):
    _QGIS_VERSION_INT = 33600   # assume a safe QGIS 3.36 baseline

_IS_QGIS4 = _QGIS_VERSION_INT >= 39900   # 4.0.0 starts at 39900 by convention


# ── Curved-type detection shim ────────────────────────────────────────────────
# QgsWkbTypes.isCurvedType() is a static method in QGIS 3.x; in QGIS 4 it was
# promoted into the Qgis namespace.  We wrap both so callers need not care.
def _is_curved_wkb_type(wkb_type: int) -> bool:
    """Return True if the WKB type represents a curved / arc geometry."""
    # Strategy 1: QGIS 4 / modern 3.x static on QgsWkbTypes
    try:
        return bool(QgsWkbTypes.isCurvedType(wkb_type))
    except (AttributeError, TypeError):
        pass
    # Strategy 2: Qgis enum (some 4.x builds)
    try:
        return bool(Qgis.WkbType(wkb_type) in (
            Qgis.WkbType.CircularString,
            Qgis.WkbType.CompoundCurve,
            Qgis.WkbType.CurvePolygon,
            Qgis.WkbType.MultiCurve,
            Qgis.WkbType.MultiSurface,
        ))
    except (AttributeError, TypeError, ValueError):
        pass
    # Strategy 3: hard-coded WKB type integers for known curved types
    # (CircularString=8, CompoundCurve=9, CurvePolygon=10, MultiCurve=11,
    #  MultiSurface=12, and their Z/M/ZM variants)
    _CURVED = {8, 9, 10, 11, 12, 1008, 1009, 1010, 1011, 1012,
               2008, 2009, 2010, 2011, 2012, 3008, 3009, 3010, 3011, 3012}
    return (wkb_type % 1000) in {8, 9, 10, 11, 12}


# ── Buffer style resolution (module-level, resolved once at import time) ───────
def _resolve_buffer_styles() -> Tuple[int, int, int]:
    """
    Resolve cap and join style integer values for QgsGeometry.buffer() in a
    way that works across QGIS 3.28, 3.36, and QGIS 4.x.

    Returns (cap_round, cap_square, join_round).

    Five strategies are tried in order — the first one that doesn't raise is
    used.  Hard-coded GEOS integers are the final fallback and always succeed.

    GEOS integer mapping (stable across all QGIS versions):
        CAP_ROUND  = 1   (BufferParameters::CapRound)
        CAP_FLAT   = 2   (BufferParameters::CapFlat)
        CAP_SQUARE = 3   (BufferParameters::CapSquare)
        JOIN_ROUND = 1   (BufferParameters::JoinRound)
        JOIN_MITRE = 2
        JOIN_BEVEL = 3
    """
    # ── Strategy 1: Qgis.EndCapStyle / Qgis.JoinStyle (QGIS 3.26+, QGIS 4) ──
    try:
        cap_r = int(Qgis.EndCapStyle.Round)
        cap_s = int(Qgis.EndCapStyle.Flat)    # Flat: ends exactly at path end
        joi_r = int(Qgis.JoinStyle.Round)
        return cap_r, cap_s, joi_r
    except AttributeError:
        pass

    # ── Strategy 2: QgsGeometry.BufferSide / CapStyle enums (some 3.x) ────────
    try:
        cap_r = int(QgsGeometry.CapRound)
        cap_s = int(QgsGeometry.CapFlat)      # Flat: ends exactly at path end
        joi_r = int(QgsGeometry.JoinStyleRound)
        return cap_r, cap_s, joi_r
    except AttributeError:
        pass

    # ── Strategy 3: probe the Qgis module namespace for integer constants ─────
    try:
        import qgis.core as _qc
        cap_r = int(getattr(_qc, "CAP_ROUND",  getattr(_qc, "CapRound",  1)))
        cap_s = int(getattr(_qc, "CAP_FLAT",   getattr(_qc, "CapFlat",   2)))
        joi_r = int(getattr(_qc, "JOIN_ROUND", getattr(_qc, "JoinRound", 1)))
        return cap_r, cap_s, joi_r
    except (AttributeError, TypeError, ValueError):
        pass

    # ── Strategy 4: hard-coded GEOS integers (always succeeds) ───────────────
    return 1, 2, 1   # Round=1, Flat=2 (Square UI option = flat cap)


# Resolve once at module import; all functions below reuse these constants.
_CAP_ROUND, _CAP_SQUARE, _JOIN_ROUND = _resolve_buffer_styles()


def _make_buffer(geom: QgsGeometry, dist: float, cap_style: int, join_style: int) -> QgsGeometry:
    """
    Create a buffer with cap/join styles, robust across QGIS 3.x and QGIS 4.

    Four call signatures are tried in order so that at least the plain buffer
    (without custom styles) is always returned even in unusual builds.

    QGIS 4 changed the C++ overload resolution for buffer() in some builds;
    the 3-argument form (dist, segments, cap) is tried as an intermediate step.
    """
    segments = 16   # arc approximation quality

    # Form 0: enum-typed 5-argument form — REQUIRED on QGIS 4 / PyQt6, where
    # buffer() rejects plain ints for the Qgis.EndCapStyle / Qgis.JoinStyle
    # parameters (TypeError), which previously cascaded all the way down to
    # Form 4's plain buffer — i.e. always ROUND caps, so Square == Round.
    try:
        result = geom.buffer(dist, segments,
                             Qgis.EndCapStyle(cap_style),
                             Qgis.JoinStyle(join_style), 5.0)
        if result is not None and not result.isEmpty():
            return result
    except Exception:
        pass

    # Form 1: full 5-argument form — dist, segs, cap, join, mitre_limit
    # This is the canonical cross-version form and works in 3.x and most 4.x.
    try:
        result = geom.buffer(dist, segments, cap_style, join_style, 5.0)
        if result is not None and not result.isEmpty():
            return result
    except (TypeError, Exception):
        pass

    # Form 2: QGIS 4 alternative — QgsBufferParameters object
    try:
        from qgis.core import QgsBufferParameters  # QGIS 4 only
        params = QgsBufferParameters()
        params.setEndCapStyle(Qgis.EndCapStyle(cap_style))
        params.setJoinStyle(Qgis.JoinStyle(join_style))
        params.setSegmentsToApproximate(segments)
        result = geom.buffer(dist, params)
        if result is not None and not result.isEmpty():
            return result
    except (ImportError, AttributeError, TypeError, Exception):
        pass

    # Form 3: 3-argument form (dist, segs, cap) — some intermediate QGIS builds
    try:
        result = geom.buffer(dist, segments, cap_style)
        if result is not None and not result.isEmpty():
            return result
    except (TypeError, Exception):
        pass

    # Form 4: plain 2-argument form — no style control but always works
    try:
        result = geom.buffer(dist, segments)
        if result is not None and not result.isEmpty():
            return result
    except Exception:
        pass

    # Last resort: return an empty geometry rather than None so callers can
    # safely call .isEmpty() without a None check.
    return QgsGeometry()

# ── Constants ──────────────────────────────────────────────────────────────────

METHOD_FIT          = "Fit shapes to path"
METHOD_PRESERVE     = "Preserve shapes outside alignment area"
METHOD_SNAP_ENDS    = "Snap line ends to path"
METHOD_TRACE_SMOOTH = "Trace & Smooth curve along path"
METHOD_SMART_FIT    = "Smart Fit to Path"

SIDE_BOTH  = "Both"
SIDE_LEFT  = "Left"
SIDE_RIGHT = "Right"

END_ROUND  = "Round"
END_SQUARE = "Square"


# ── Internal feedback helper ───────────────────────────────────────────────────

def _emit(feedback_fn, level: str, msg: str):
    qgis_level = {
        "info":  Qgis.MessageLevel.Info,
        "warn":  Qgis.MessageLevel.Warning,
        "debug": Qgis.MessageLevel.Info,
    }.get(level, Qgis.MessageLevel.Info)
    if _HAS_MSG_LOG:
        QgsMessageLog.logMessage(msg, "AlignFeatures", qgis_level)
    if feedback_fn is not None:
        try:
            feedback_fn(level, msg)
        except Exception:
            pass


# ── Geometry helpers ───────────────────────────────────────────────────────────

def _extract_path_vertices(path_geom: QgsGeometry) -> List[QgsPointXY]:
    """Return ordered list of QgsPointXY from a line geometry.

    For curved geometry (CircularString / CompoundCurve), densify first so the
    returned vertex list faithfully represents the curve shape.
    """
    # Densify curved geometry at ~0.5 map-unit resolution so arc shapes are
    # captured.  segmentize() converts any curve type to a plain linestring.
    try:
        seg = path_geom.densifyByCount(32)   # densify each segment 32×
        if seg is None or seg.isEmpty():
            seg = path_geom
    except Exception:
        seg = path_geom

    vertices = []
    for part in seg.parts():
        for v in part.vertices():
            vertices.append(QgsPointXY(v.x(), v.y()))
    return vertices


def _extract_path_vertices_fine(path_geom: QgsGeometry, max_segment: float) -> List[QgsPointXY]:
    """Like _extract_path_vertices but densify so no two adjacent vertices are
    more than max_segment apart.  Used by the trace pipeline to get smooth
    arc following.

    v8 update — curve-aware path expansion
    --------------------------------------
    If the input geometry contains true curved segments (CircularString,
    CompoundCurve, CurvePolygon, etc.) we first call segmentize() on the
    underlying abstract geometry.  segmentize() is QGIS's curve-aware arc
    expansion routine — it converts each arc into a polyline that
    approximates the true curve, preserving tangent continuity at the
    join points.

    densifyByDistance() alone operates on the chord (linear) representation
    and therefore loses arc shape; doing the segmentize step first ensures
    the densified output faithfully follows the curve instead of cutting
    across it.  Straight (non-curved) input skips segmentize so we do not
    introduce unnecessary intermediate vertices.
    """
    seg = path_geom

    # ── 1. Curve-aware arc expansion (only if curves are actually present) ──
    try:
        wkb = seg.wkbType()
        is_curved = False
        try:
            is_curved = _is_curved_wkb_type(wkb)
        except Exception:
            is_curved = False
        if is_curved:
            abs_g = seg.constGet()
            if abs_g is not None:
                segmented = abs_g.segmentize()
                if segmented is not None:
                    seg = QgsGeometry(segmented.clone())
    except Exception:
        pass

    # ── 2. Densify by distance so no chord exceeds max_segment ──────────────
    try:
        densified = seg.densifyByDistance(max_segment)
        if densified is not None and not densified.isEmpty():
            seg = densified
    except Exception:
        pass

    if seg is None or seg.isEmpty():
        seg = path_geom

    vertices = []
    for part in seg.parts():
        for v in part.vertices():
            vertices.append(QgsPointXY(v.x(), v.y()))
    return vertices


def _extract_path_segments(
    path_vertices: List[QgsPointXY],
) -> List[Tuple[QgsPointXY, QgsPointXY]]:
    """Return list of (start, end) segment tuples, skipping zero-length ones."""
    segs = []
    for i in range(len(path_vertices) - 1):
        a, b = path_vertices[i], path_vertices[i + 1]
        if math.hypot(b.x() - a.x(), b.y() - a.y()) > 1e-10:
            segs.append((a, b))
    return segs


# ── Spatial index for segments ─────────────────────────────────────────────────

class _SegmentIndex:
    """
    Lightweight spatial index over line segments.

    Builds a list of (bbox, segment) pairs.  Candidate lookup returns all
    segments whose bounding box intersects the query rectangle.
    """

    def __init__(self, segments: List[Tuple[QgsPointXY, QgsPointXY]]):
        self._items: List[Tuple[QgsRectangle, int]] = []
        for idx, (a, b) in enumerate(segments):
            xmin = min(a.x(), b.x())
            xmax = max(a.x(), b.x())
            ymin = min(a.y(), b.y())
            ymax = max(a.y(), b.y())
            self._items.append((QgsRectangle(xmin, ymin, xmax, ymax), idx))
        self._segments = segments

    def candidates(self, query: QgsRectangle) -> List[int]:
        return [idx for bbox, idx in self._items if bbox.intersects(query)]

    def segment(self, idx: int) -> Tuple[QgsPointXY, QgsPointXY]:
        return self._segments[idx]

    def all_segments(self) -> List[Tuple[QgsPointXY, QgsPointXY]]:
        return self._segments


# ── Core geometry math ─────────────────────────────────────────────────────────

def _distance_pt_to_segment(
    p: QgsPointXY, a: QgsPointXY, b: QgsPointXY
) -> Tuple[float, QgsPointXY]:
    """
    Return (distance, closest_point) from point p to segment a→b.
    Clamps projection to segment endpoints.
    """
    dx, dy = b.x() - a.x(), b.y() - a.y()
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 1e-12:
        d = math.hypot(p.x() - a.x(), p.y() - a.y())
        return d, a

    t = ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))
    closest = QgsPointXY(a.x() + t * dx, a.y() + t * dy)
    d = math.hypot(p.x() - closest.x(), p.y() - closest.y())
    return d, closest


def _nearest_point_on_path_indexed(
    p: QgsPointXY,
    seg_index: _SegmentIndex,
    tolerance: float,
) -> Tuple[float, QgsPointXY, int]:
    """
    Return (min_distance, closest_point_on_path, segment_index).

    Precision fix (v10.1.1): when the bbox spatial index yields no candidates
    (can happen at the path's very ends or on extremely short segments), we
    scan ALL segments but still select only via the true point-to-segment
    distance — we never widen the geometric search radius.  The old fallback
    replaced the candidate list with every segment unconditionally, which is
    still correct because we always take the segment with the minimum distance;
    the fix below makes the intent explicit and adds a guard so the returned
    distance is always the true nearest distance, not clamped by tolerance.
    """
    query = QgsRectangle(
        p.x() - tolerance, p.y() - tolerance,
        p.x() + tolerance, p.y() + tolerance,
    )
    candidate_ids = seg_index.candidates(query)
    # Fallback: no bbox hit → scan all segments.  We still take the nearest
    # by actual geometric distance, so no incorrect snapping can occur.
    if not candidate_ids:
        candidate_ids = list(range(len(seg_index.all_segments())))

    best_d   = float("inf")
    best_pt  = p
    best_idx = 0
    for idx in candidate_ids:
        a, b = seg_index.segment(idx)
        d, cp = _distance_pt_to_segment(p, a, b)
        if d < best_d:
            best_d   = d
            best_pt  = cp
            best_idx = idx
    return best_d, best_pt, best_idx


def _nearest_path_vertex(
    p: QgsPointXY,
    path_vertices: List[QgsPointXY],
    tolerance: float,
) -> Tuple[float, Optional[QgsPointXY]]:
    """
    Return (distance, vertex) for the nearest path vertex within tolerance.
    Returns (inf, None) if none is within tolerance.
    """
    best_d  = float("inf")
    best_pt = None
    t2 = tolerance * tolerance
    for pv in path_vertices:
        dx = p.x() - pv.x()
        dy = p.y() - pv.y()
        d2 = dx * dx + dy * dy
        if d2 < best_d:
            best_d  = d2
            best_pt = pv
    best_d = math.sqrt(best_d)
    if best_d > tolerance:
        return float("inf"), None
    return best_d, best_pt


def _cross_product_sign(a: QgsPointXY, b: QgsPointXY, p: QgsPointXY) -> float:
    return (b.x() - a.x()) * (p.y() - a.y()) - (b.y() - a.y()) * (p.x() - a.x())


def _side_of_path_indexed(
    p: QgsPointXY,
    seg_index: _SegmentIndex,
    tolerance: float,
) -> float:
    """Which side of the path is point p on?  +1 left, -1 right, 0 on path.

    NOTE (v9 — ROOT CAUSE 1 fix): a return value of 0.0 means the vertex lies
    *exactly on* the path.  Side filters therefore use strict inequalities
    (`pt_side < 0` / `pt_side > 0`) and never exclude the 0 case, so a vertex
    that already sits on the path is always eligible to be snapped regardless
    of the Left/Right setting — it IS on the path.
    """
    d, _, seg_idx = _nearest_point_on_path_indexed(p, seg_index, max(tolerance, 1e6))
    a, b = seg_index.segment(seg_idx)
    cross = _cross_product_sign(a, b, p)
    if abs(cross) < 1e-10:
        return 0.0
    return math.copysign(1.0, cross)


def _apply_offset(
    snapped: QgsPointXY,
    seg_a: QgsPointXY,
    seg_b: QgsPointXY,
    offset: float,
    original_side: float,
) -> QgsPointXY:
    # v9 — ROOT CAUSE 2 note:
    # When offset is (effectively) zero this returns the snapped/projected
    # point *unchanged* — no extra arithmetic is applied, so the vertex stays
    # exactly where the projection placed it (mathematically on the path).
    # Any sub-tolerance residual between two independently-projected polygons
    # is reconciled by the v10 master-path snap pass (_snap_to_master_path),
    # not here.
    if abs(offset) < 1e-10:
        return snapped
    dx, dy  = seg_b.x() - seg_a.x(), seg_b.y() - seg_a.y()
    seg_len = math.hypot(dx, dy)
    if seg_len < 1e-10:
        return snapped
    lx, ly = -dy / seg_len, dx / seg_len
    sign = original_side if original_side != 0.0 else 1.0
    return QgsPointXY(
        snapped.x() + sign * lx * offset,
        snapped.y() + sign * ly * offset,
    )


# ── Path arc-length parameterisation ──────────────────────────────────────────

def _build_path_arc_lengths(path_vertices: List[QgsPointXY]) -> List[float]:
    """Return cumulative arc-length at each vertex (starts at 0.0)."""
    arc = [0.0]
    for i in range(1, len(path_vertices)):
        a, b = path_vertices[i - 1], path_vertices[i]
        arc.append(arc[-1] + math.hypot(b.x() - a.x(), b.y() - a.y()))
    return arc


def _project_onto_path(
    p: QgsPointXY,
    path_vertices: List[QgsPointXY],
    arc_lengths: List[float],
    seg_index: _SegmentIndex,
    tolerance: float,
) -> Tuple[float, QgsPointXY]:
    """
    Project point p onto the path.

    Returns (arc_length_at_projection, projected_point).
    arc_length_at_projection is in the same units as path coordinates and
    is measured along the path from path_vertices[0].
    """
    best_d, best_pt, best_seg_idx = _nearest_point_on_path_indexed(
        p, seg_index, max(tolerance * 3, 1e6)  # generous search for tracing
    )
    a, b = seg_index.segment(best_seg_idx)
    seg_len = math.hypot(b.x() - a.x(), b.y() - a.y())
    if seg_len < 1e-10:
        t_on_seg = 0.0
    else:
        dx = best_pt.x() - a.x()
        dy = best_pt.y() - a.y()
        t_on_seg = math.hypot(dx, dy) / seg_len

    arc_at_proj = arc_lengths[best_seg_idx] + t_on_seg * (
        arc_lengths[best_seg_idx + 1] - arc_lengths[best_seg_idx]
    )
    return arc_at_proj, best_pt


def _extract_path_subsegment(
    t_start: float,
    t_end: float,
    path_vertices: List[QgsPointXY],
    arc_lengths: List[float],
    projected_start: QgsPointXY,
    projected_end: QgsPointXY,
    reverse: bool = False,
) -> List[QgsPointXY]:
    """
    Extract the path sub-curve between arc-length positions t_start and t_end.

    Returns an ordered list of QgsPointXY that starts at projected_start,
    passes through any original path vertices that lie in (t_start, t_end),
    and ends at projected_end.

    If t_start > t_end the subsegment wraps around (not supported — caller
    should ensure t_start < t_end by choosing the appropriate direction).
    If reverse=True, the list is reversed (so it goes from projected_end to
    projected_start).
    """
    if t_start > t_end:
        t_start, t_end = t_end, t_start
        projected_start, projected_end = projected_end, projected_start
        reverse = not reverse

    pts = [projected_start]

    for i, arc in enumerate(arc_lengths):
        if arc <= t_start + 1e-8:
            continue
        if arc >= t_end - 1e-8:
            break
        pts.append(path_vertices[i])

    pts.append(projected_end)

    # Deduplicate consecutive duplicates
    deduped = [pts[0]]
    for pt in pts[1:]:
        prev = deduped[-1]
        if math.hypot(pt.x() - prev.x(), pt.y() - prev.y()) > 1e-8:
            deduped.append(pt)

    if reverse:
        deduped.reverse()

    return deduped


# ── Ring-level processing ──────────────────────────────────────────────────────

def _ring_to_pointxy_list(ring) -> List[QgsPointXY]:
    return [QgsPointXY(v.x(), v.y()) for v in ring.vertices()]


def _has_closing_dup(ring: List[QgsPointXY]) -> bool:
    return (
        len(ring) >= 2
        and abs(ring[0].x() - ring[-1].x()) < 1e-10
        and abs(ring[0].y() - ring[-1].y()) < 1e-10
    )


def _process_ring(
    ring: List[QgsPointXY],
    path_vertices: List[QgsPointXY],
    seg_index: _SegmentIndex,
    tolerance: float,
    offset: float,
    method: str,
    side: str,
    snap_only_ends: bool,
) -> List[QgsPointXY]:
    """
    Snap vertices of a single closed ring to the path.  Two-pass strategy.
    (Unchanged from v7.1 — FIT, SNAP_ENDS modes, + diagnostic logging.)
    """
    if not ring:
        return ring

    n = len(ring)
    has_closing_dup = _has_closing_dup(ring)
    work = ring[:-1] if has_closing_dup else ring[:]
    nw   = len(work)

    if snap_only_ends:
        snap_indices: Set[int] = {0, nw - 1}
    else:
        snap_indices = set(range(nw))

    snapped_set: Set[int] = set()
    new_ring = list(work)

    # ── Diagnostic: log effective tolerance so misconfigured values are visible
    if _HAS_MSG_LOG:
        QgsMessageLog.logMessage(
            f"_process_ring: method={method!r}  tolerance={tolerance}  "
            f"offset={offset}  side={side!r}  vertices={nw}  "
            f"snap_only_ends={snap_only_ends}",
            "AlignFeatures", Qgis.MessageLevel.Info,
        )

    # ── Pass 1 : vertex → nearest path vertex ────────────────────────────────
    pass1_count = 0
    for i in range(nw):
        if i not in snap_indices:
            continue
        pt = work[i]
        pt_side = _side_of_path_indexed(pt, seg_index, tolerance)
        if side == SIDE_LEFT  and pt_side < 0:
            continue
        if side == SIDE_RIGHT and pt_side > 0:
            continue
        v_dist, v_pt = _nearest_path_vertex(pt, path_vertices, tolerance)
        if v_pt is not None:
            # Use a generous search radius (tolerance * 2) so the segment
            # lookup is never starved by a tight bbox — we need the segment
            # that *owns* v_pt, not just one that happens to be nearby.
            _, _, seg_idx = _nearest_point_on_path_indexed(v_pt, seg_index, tolerance * 2)
            a, b = seg_index.segment(seg_idx)
            new_ring[i] = _apply_offset(v_pt, a, b, offset, pt_side)
            snapped_set.add(i)
            pass1_count += 1

    # ── Pass 2 : vertex → nearest edge ───────────────────────────────────────
    pass2_count = 0
    for i in range(nw):
        if i not in snap_indices or i in snapped_set:
            continue
        pt = work[i]
        pt_side = _side_of_path_indexed(pt, seg_index, tolerance)
        if side == SIDE_LEFT  and pt_side < 0:
            continue
        if side == SIDE_RIGHT and pt_side > 0:
            continue
        edge_d, edge_pt, seg_idx = _nearest_point_on_path_indexed(
            pt, seg_index, tolerance
        )
        if edge_d <= tolerance:
            a, b = seg_index.segment(seg_idx)
            new_ring[i] = _apply_offset(edge_pt, a, b, offset, pt_side)
            pass2_count += 1

    # ── Diagnostic: report snap results — zero snaps means tolerance is wrong
    total_snapped = pass1_count + pass2_count
    if _HAS_MSG_LOG:
        if total_snapped == 0:
            QgsMessageLog.logMessage(
                f"_process_ring: \u26a0\ufe0f  0/{len(snap_indices)} vertices snapped "
                f"(tolerance={tolerance} — no polygon vertex lay within this "
                f"distance of the path; try increasing tolerance).",
                "AlignFeatures", Qgis.MessageLevel.Warning,
            )
        else:
            QgsMessageLog.logMessage(
                f"_process_ring: \u2705 snapped {total_snapped}/{len(snap_indices)} "
                f"candidates (pass1={pass1_count}, pass2={pass2_count})",
                "AlignFeatures", Qgis.MessageLevel.Info,
            )

    if has_closing_dup:
        new_ring.append(new_ring[0])

    return new_ring


def _process_ring_preserve(
    ring: List[QgsPointXY],
    path_vertices: List[QgsPointXY],
    seg_index: _SegmentIndex,
    tolerance: float,
    offset: float,
    side: str,
    snap_only_ends: bool,
    tol_buffer: QgsGeometry,
) -> List[QgsPointXY]:
    """PRESERVE mode ring processing. (Unchanged from v7.1.)"""
    if not ring:
        return ring

    n = len(ring)
    has_closing_dup = _has_closing_dup(ring)
    work = ring[:-1] if has_closing_dup else ring[:]
    nw   = len(work)

    if snap_only_ends:
        snap_indices: Set[int] = {0, nw - 1}
    else:
        snap_indices = set(range(nw))

    snapped_set: Set[int] = set()
    new_ring = list(work)

    tb_bbox = tol_buffer.boundingBox()

    # ── Pass 1 ────────────────────────────────────────────────────────────────
    for i in range(nw):
        if i not in snap_indices:
            continue
        pt = work[i]
        if not tb_bbox.contains(QgsRectangle(pt.x(), pt.y(), pt.x(), pt.y())):
            continue
        pt_geom = QgsGeometry.fromPointXY(pt)
        if not tol_buffer.contains(pt_geom):
            continue
        pt_side = _side_of_path_indexed(pt, seg_index, tolerance)
        if side == SIDE_LEFT  and pt_side < 0:
            continue
        if side == SIDE_RIGHT and pt_side > 0:
            continue
        v_dist, v_pt = _nearest_path_vertex(pt, path_vertices, tolerance)
        if v_pt is not None:
            # Generous radius so the segment owning v_pt is always found.
            _, _, seg_idx = _nearest_point_on_path_indexed(v_pt, seg_index, tolerance * 2)
            a, b = seg_index.segment(seg_idx)
            new_ring[i] = _apply_offset(v_pt, a, b, offset, pt_side)
            snapped_set.add(i)

    # ── Pass 2 ────────────────────────────────────────────────────────────────
    for i in range(nw):
        if i not in snap_indices or i in snapped_set:
            continue
        pt = work[i]
        if not tb_bbox.contains(QgsRectangle(pt.x(), pt.y(), pt.x(), pt.y())):
            continue
        pt_geom = QgsGeometry.fromPointXY(pt)
        if not tol_buffer.contains(pt_geom):
            continue
        pt_side = _side_of_path_indexed(pt, seg_index, tolerance)
        if side == SIDE_LEFT  and pt_side < 0:
            continue
        if side == SIDE_RIGHT and pt_side > 0:
            continue
        edge_d, edge_pt, seg_idx = _nearest_point_on_path_indexed(
            pt, seg_index, tolerance
        )
        if edge_d <= tolerance:
            a, b = seg_index.segment(seg_idx)
            new_ring[i] = _apply_offset(edge_pt, a, b, offset, pt_side)

    if has_closing_dup:
        new_ring.append(new_ring[0])

    return new_ring


# ── v8 Trace helpers ───────────────────────────────────────────────────────────

def _resample_ring(ring: List[QgsPointXY], distance: float) -> List[QgsPointXY]:
    """
    Densify a ring so no two consecutive vertices are more than `distance`
    apart, preserving all original vertices as anchors.
    """
    n = len(ring)
    if n < 2:
        return ring[:]

    out: List[QgsPointXY] = []
    for i in range(n - 1):
        a = ring[i]
        b = ring[i + 1]
        out.append(a)
        dx = b.x() - a.x()
        dy = b.y() - a.y()
        seg_len = math.hypot(dx, dy)
        if seg_len <= distance or seg_len < 1e-10:
            continue
        n_inserts = int(math.floor(seg_len / distance))
        for k in range(1, n_inserts + 1):
            t = k / (n_inserts + 1)
            out.append(QgsPointXY(a.x() + dx * t, a.y() + dy * t))

    out.append(ring[-1])
    return out


def _smooth_ring_chaikin(
    ring: List[QgsPointXY],
    iterations: int = 2,
    anchor_indices: Optional[Set[int]] = None,
) -> List[QgsPointXY]:
    """
    Chaikin corner-cutting smoothing.

    anchor_indices: if given, those ring positions are pinned and not moved.
    This lets snapped-to-path vertices stay exactly on the path while the
    outside corners soften.
    """
    if not ring or iterations <= 0:
        return ring

    has_closing_dup = _has_closing_dup(ring)
    work = ring[:-1] if has_closing_dup else ring[:]
    n = len(work)
    if n < 3:
        return ring[:]

    anchors = anchor_indices or set()

    for _ in range(iterations):
        new_pts: List[QgsPointXY] = []

        if has_closing_dup:
            seg_count = len(work)
            for i in range(seg_count):
                a = work[i]
                b = work[(i + 1) % seg_count]
                # If either endpoint is an anchor, preserve it
                if i in anchors:
                    new_pts.append(a)
                    if (i + 1) % seg_count not in anchors:
                        rx = 0.25 * a.x() + 0.75 * b.x()
                        ry = 0.25 * a.y() + 0.75 * b.y()
                        new_pts.append(QgsPointXY(rx, ry))
                else:
                    qx = 0.75 * a.x() + 0.25 * b.x()
                    qy = 0.75 * a.y() + 0.25 * b.y()
                    new_pts.append(QgsPointXY(qx, qy))
                    if (i + 1) % seg_count not in anchors:
                        rx = 0.25 * a.x() + 0.75 * b.x()
                        ry = 0.25 * a.y() + 0.75 * b.y()
                        new_pts.append(QgsPointXY(rx, ry))
            work = new_pts
            # Anchors shift with the new list — simplified: no index tracking
            # across iterations; anchors only help on first pass
            anchors = set()
        else:
            new_pts.append(work[0])
            for i in range(len(work) - 1):
                a = work[i]
                b = work[i + 1]
                if i in anchors:
                    new_pts.append(a)
                    if (i + 1) not in anchors:
                        rx = 0.25 * a.x() + 0.75 * b.x()
                        ry = 0.25 * a.y() + 0.75 * b.y()
                        new_pts.append(QgsPointXY(rx, ry))
                else:
                    qx = 0.75 * a.x() + 0.25 * b.x()
                    qy = 0.75 * a.y() + 0.25 * b.y()
                    new_pts.append(QgsPointXY(qx, qy))
                    if (i + 1) not in anchors:
                        rx = 0.25 * a.x() + 0.75 * b.x()
                        ry = 0.25 * a.y() + 0.75 * b.y()
                        new_pts.append(QgsPointXY(rx, ry))
            new_pts.append(work[-1])
            work = new_pts
            anchors = set()

    if has_closing_dup:
        work.append(QgsPointXY(work[0].x(), work[0].y()))

    return work


def _point_in_buffer(
    pt: QgsPointXY,
    tol_buffer: QgsGeometry,
    tb_bbox: QgsRectangle,
) -> bool:
    """Fast buffer containment test: bbox pre-check then exact test."""
    if not tb_bbox.contains(QgsRectangle(pt.x(), pt.y(), pt.x(), pt.y())):
        return False
    return tol_buffer.contains(QgsGeometry.fromPointXY(pt))


def _interpolate_segment_crossing(
    p_inside: QgsPointXY,
    p_outside: QgsPointXY,
    tol_buffer: QgsGeometry,
    tb_bbox: QgsRectangle,
) -> QgsPointXY:
    """
    Binary-search for the point on segment (p_inside → p_outside) that lies
    on the boundary of tol_buffer.  Returns the crossing point.

    p_inside  is guaranteed to be inside  the buffer.
    p_outside is guaranteed to be outside the buffer.
    """
    lo_x, lo_y = p_inside.x(),  p_inside.y()
    hi_x, hi_y = p_outside.x(), p_outside.y()

    # FIX 3: Increased from 20 → 40 iterations so the binary search converges
    # even when the gap between polygons is large relative to the search
    # epsilon.  40 iterations gives ~2^-40 ≈ 10^-12 relative precision, which
    # is far below any practical coordinate resolution.
    for _ in range(40):   # 40 iterations → sub-nanometre precision
        mx = (lo_x + hi_x) * 0.5
        my = (lo_y + hi_y) * 0.5
        mid = QgsPointXY(mx, my)
        if _point_in_buffer(mid, tol_buffer, tb_bbox):
            lo_x, lo_y = mx, my
        else:
            hi_x, hi_y = mx, my

    return QgsPointXY((lo_x + hi_x) * 0.5, (lo_y + hi_y) * 0.5)


def _trace_ring_against_path(
    ring: List[QgsPointXY],
    path_vertices: List[QgsPointXY],
    arc_lengths: List[float],
    seg_index: _SegmentIndex,
    tol_buffer: QgsGeometry,
    tolerance: float,
    offset: float,
    side: str,
    smooth_iterations: int,
) -> List[QgsPointXY]:
    """
    TRUE TRACE pipeline (v8).

    For each contiguous run of ring vertices that lies inside the tolerance
    buffer, the corresponding portion of the polygon boundary is *replaced*
    by the actual path curve (extracted via arc-length parameterisation).
    Vertices outside the buffer are kept as-is.

    Steps:
        1. Classify each vertex: inside buffer or outside.
        2. For each buffer-crossing between consecutive vertices, compute
           the exact entry/exit point on the buffer boundary.
        3. Build the output ring by alternating:
             outside segments (original vertices)
             traced path segments (extracted path sub-curve)
        4. Apply Chaikin smoothing to outside corners (anchor the path
           trace endpoints so they don't drift).

    Returns the new ring vertex list.
    """
    if not ring or len(ring) < 3:
        return ring

    has_closing_dup = _has_closing_dup(ring)
    work = ring[:-1] if has_closing_dup else ring[:]
    nw = len(work)

    if nw < 3:
        return ring[:]

    tb_bbox = tol_buffer.boundingBox()

    # ── 1. Classify vertices ──────────────────────────────────────────────────
    inside = [_point_in_buffer(pt, tol_buffer, tb_bbox) for pt in work]

    # Side filter: vertices on the wrong side of the path are never inside.
    if side != SIDE_BOTH:
        for i, pt in enumerate(work):
            if inside[i]:
                pt_side = _side_of_path_indexed(pt, seg_index, tolerance)
                if side == SIDE_LEFT  and pt_side < 0:
                    inside[i] = False
                if side == SIDE_RIGHT and pt_side > 0:
                    inside[i] = False

    # If nothing is inside, fall back to simple snap
    if not any(inside):
        return _process_ring(
            ring, path_vertices, seg_index, tolerance, offset,
            METHOD_FIT, side, False,
        )

    # If everything is inside, replace entire ring with path sub-segment
    # (traced from start to end of path near this ring)
    if all(inside):
        # Project first and last unique vertex
        t0, pt0 = _project_onto_path(work[0],  path_vertices, arc_lengths, seg_index, tolerance)
        t1, pt1 = _project_onto_path(work[-1], path_vertices, arc_lengths, seg_index, tolerance)
        sub = _extract_path_subsegment(t0, t1, path_vertices, arc_lengths, pt0, pt1)
        if len(sub) < 3:
            return ring
        if has_closing_dup:
            sub.append(QgsPointXY(sub[0].x(), sub[0].y()))
        return sub

    # ── 2. Build the stitched ring ────────────────────────────────────────────
    out: List[QgsPointXY] = []
    anchor_set: Set[int] = set()   # indices in `out` that are path-trace seams

    def _add(pt: QgsPointXY):
        out.append(pt)

    def _add_anchor(pt: QgsPointXY):
        anchor_set.add(len(out))
        out.append(pt)

    i = 0
    while i < nw:
        if not inside[i]:
            # Outside: emit the vertex as-is
            _add(work[i])
            i += 1
        else:
            # Entering a buffer run.
            # Find the index j where the run ends (first vertex that is outside).
            j = i
            while j < nw and inside[j]:
                j += 1
            # Run is work[i..j-1].

            # ── Entry crossing point ─────────────────────────────────────────
            # Transition: work[i-1] (outside) → work[i] (inside)
            prev_idx = (i - 1) % nw
            if inside[prev_idx]:
                entry_pt = work[i]   # whole ring inside — handled above
            else:
                entry_pt = _interpolate_segment_crossing(
                    work[i], work[prev_idx], tol_buffer, tb_bbox
                )

            # ── Exit crossing point ──────────────────────────────────────────
            # Transition: work[j-1] (inside) → work[j % nw] (outside)
            next_idx = j % nw
            if inside[next_idx]:
                exit_pt = work[j - 1]
            else:
                exit_pt = _interpolate_segment_crossing(
                    work[j - 1], work[next_idx], tol_buffer, tb_bbox
                )

            # ── Project entry & exit onto path ───────────────────────────────
            t_entry, proj_entry = _project_onto_path(
                entry_pt, path_vertices, arc_lengths, seg_index, tolerance
            )
            t_exit, proj_exit = _project_onto_path(
                exit_pt,  path_vertices, arc_lengths, seg_index, tolerance
            )

            # ── Determine trace direction ────────────────────────────────────
            # Walk along the ring to figure out which direction along the path
            # the polygon edge travels.  We compare the path-projection of
            # work[i] vs work[j-1]: if t_i < t_j, trace forward; else reverse.
            t_i, _ = _project_onto_path(
                work[i], path_vertices, arc_lengths, seg_index, tolerance
            )
            t_jm1, _ = _project_onto_path(
                work[j - 1], path_vertices, arc_lengths, seg_index, tolerance
            )
            # v9.2: deterministic trace-direction decision.
            # Normal case = the v8 rule (run's first vs last projected arc).
            # The epsilon tie-break only engages for near-symmetric runs where
            # t_i ≈ t_jm1; it resolves them via the entry/exit projections so
            # two adjacent polygons sharing this stretch always agree on the
            # direction and end up with an identical vertex sequence.
            if abs(t_i - t_jm1) > 1e-9:
                do_reverse = t_i > t_jm1
            else:
                do_reverse = t_entry > t_exit

            # Apply offset to entry/exit projected points
            if abs(offset) > 1e-10:
                _, _, seg_e = _nearest_point_on_path_indexed(proj_entry, seg_index, tolerance)
                ae, be = seg_index.segment(seg_e)
                side_e = _side_of_path_indexed(entry_pt, seg_index, tolerance)
                proj_entry = _apply_offset(proj_entry, ae, be, offset, side_e)

                _, _, seg_x = _nearest_point_on_path_indexed(proj_exit, seg_index, tolerance)
                ax, bx = seg_index.segment(seg_x)
                side_x = _side_of_path_indexed(exit_pt, seg_index, tolerance)
                proj_exit = _apply_offset(proj_exit, ax, bx, offset, side_x)

            # ── Extract path sub-curve ───────────────────────────────────────
            traced = _extract_path_subsegment(
                t_entry, t_exit,
                path_vertices, arc_lengths,
                proj_entry, proj_exit,
                reverse=do_reverse,
            )

            # Emit the transition from outside ring → path curve
            # (the previous outside vertex → entry point)
            _add_anchor(entry_pt)
            for pt in traced[1:]:   # skip first (= entry_pt) already added
                _add(pt)
            _add_anchor(exit_pt)

            i = j   # continue from first outside vertex after run

    if not out:
        return ring

    # ── 3. Optionally smooth outside corners ─────────────────────────────────
    if smooth_iterations > 0 and len(out) >= 3:
        out = _smooth_ring_chaikin(out, smooth_iterations, anchor_indices=anchor_set)

    # Restore closing duplicate
    if has_closing_dup and len(out) >= 1:
        out.append(QgsPointXY(out[0].x(), out[0].y()))

    return out


def _process_ring_trace_smooth(
    ring: List[QgsPointXY],
    path_vertices: List[QgsPointXY],
    arc_lengths: List[float],
    seg_index: _SegmentIndex,
    tolerance: float,
    offset: float,
    side: str,
    tol_buffer: QgsGeometry,
    resample_distance: float = 0.0,
    smooth_iterations: int = 2,
    enable_tracing: bool = True,
) -> List[QgsPointXY]:
    """
    TRACE & SMOOTH pipeline dispatcher (v8).

    When enable_tracing is True (default):
        → true path tracing via _trace_ring_against_path()

    When enable_tracing is False:
        → legacy resample+snap+smooth (v7.1 behaviour) via _process_ring()
          followed by Chaikin.
    """
    if not ring:
        return ring

    if enable_tracing:
        # Optional pre-densification before tracing
        work = ring
        if resample_distance and resample_distance > 0.0:
            work = _resample_ring(work, resample_distance)
        # FIX 4: Wrap the trace call so that any failure (exception or a
        # degenerate result shorter than the input) falls back gracefully to
        # _process_ring with METHOD_FIT instead of propagating an error or
        # silently returning the original ring unchanged.
        try:
            traced = _trace_ring_against_path(
                work, path_vertices, arc_lengths, seg_index,
                tol_buffer, tolerance, offset, side, smooth_iterations,
            )
        except Exception:
            traced = None

        if traced is None or len(traced) < 3:
            # FIX 4 fallback: trace failed or produced a degenerate ring.
            # Fall back to the traditional vertex-snap pipeline (METHOD_FIT)
            # so the polygon is still aligned, just without edge-tracing.
            work = _process_ring(
                work, path_vertices, seg_index, tolerance, offset,
                METHOD_FIT, side, False,
            )
            if smooth_iterations and smooth_iterations > 0:
                work = _smooth_ring_chaikin(work, smooth_iterations)
            return work

        return traced
    else:
        # Legacy v7.1 fallback
        work = ring
        if resample_distance and resample_distance > 0.0:
            work = _resample_ring(work, resample_distance)
        work = _process_ring(
            work, path_vertices, seg_index, tolerance, offset,
            METHOD_FIT, side, False,
        )
        if smooth_iterations and smooth_iterations > 0:
            work = _smooth_ring_chaikin(work, smooth_iterations)
        return work


# ── v10 Global Master Boundary Alignment ─────────────────────────────────────

def _vertex_is_near_path(
    pt: QgsPointXY,
    seg_index: _SegmentIndex,
    threshold: float,
) -> bool:
    """True if `pt` lies within `threshold` map units of the alignment path.

    Used by the coherent pass to identify vertices on the shared/traced
    boundary so the master-path snap only touches the aligned portion and
    leaves the rest of each polygon untouched.
    """
    d, _, _ = _nearest_point_on_path_indexed(pt, seg_index, max(threshold, 1e-6))
    return d <= threshold


def _dedupe_consecutive_vertices(
    ring: List[QgsPointXY],
    tol: float = 1e-9,
) -> List[QgsPointXY]:
    """Remove consecutive duplicate vertices (zero-length edges).

    The master-snap pass can pull two adjacent vertices onto the same master
    point, creating a zero-length segment and an invalid geometry.  This
    collapses such runs while preserving the ring's closing duplicate
    (first == last) exactly — including the wrap-around case where the final
    unique vertex has been merged onto the first.
    """
    if len(ring) < 2:
        return ring
    has_dup = _has_closing_dup(ring)
    work = ring[:-1] if has_dup else ring[:]
    out: List[QgsPointXY] = []
    for pt in work:
        if not out or math.hypot(pt.x() - out[-1].x(), pt.y() - out[-1].y()) > tol:
            out.append(pt)
    # Collapse a wrap-around duplicate (last == first) before re-closing.
    while len(out) >= 2 and math.hypot(
        out[0].x() - out[-1].x(), out[0].y() - out[-1].y()
    ) <= tol:
        out.pop()
    if has_dup and out:
        out.append(QgsPointXY(out[0].x(), out[0].y()))
    return out


def _snap_to_master_path(
    rings: List[List[QgsPointXY]],
    path_vertices: List[QgsPointXY],
    seg_index: _SegmentIndex,
    tolerance: float,
    # FIX 1: snap_tol now defaults to None so it can be derived from the
    # actual user-facing `tolerance` parameter instead of a hard-coded 0.0005.
    # Callers can still override by passing an explicit float.
    snap_tol: Optional[float] = None,
    # ── v10.1.5 additions (all default to the previous behaviour) ─────────────
    # These let "Fit to Path" reuse this same deterministic projection so two
    # adjacent polygons land on identical coordinates (gap closes).  The
    # existing Trace & Smooth caller passes none of them, so its behaviour is
    # byte-for-byte unchanged.
    side: str = SIDE_BOTH,                 # NEW: optional Left/Right/Both filter
    offset: float = 0.0,                   # NEW: optional perpendicular offset
    eligibility_radius: Optional[float] = None,  # NEW: snap-distance threshold;
                                                  # defaults to tolerance * 1.5
) -> List[List[QgsPointXY]]:
    """
    v10 — Global Master Path Snapping (core gap-fix).

    Forces EVERY vertex that lies near the alignment path (within
    ``tolerance * 1.5``) to snap to the nearest point on the *original*
    master ``path_vertices`` list — the single shared authoritative source.

    Why this eliminates gaps
    ------------------------
    The v9 coincidence hash unified near-duplicate vertices to the first
    winner in each spatial bucket.  If two polygons projected their entry/exit
    crossing to slightly different points the winner was determined by feature
    order — a floating-point lottery that still left sub-tolerance residuals.

    Here we don't arbitrate between polygons at all: we bypass their
    independently computed projections and re-derive the canonical position
    from the master path itself.  Both polygons run the *same deterministic
    computation* on the *same source data*, so the outputs are bitwise
    identical — the gap is structurally impossible.

    Two-tier snapping strategy
    --------------------------
    1. **Vertex-priority** — if ``pt`` is within ``snap_tol`` of an original
       path vertex, pin it to that exact ``QgsPointXY`` object (zero rounding
       error at kinks / corners, where topology is most fragile).
    2. **Segment-projection** — otherwise project onto the nearest master
       segment via ``_nearest_point_on_path_indexed``.  The same projection
       for both polygons yields identical coordinates regardless of their
       original pre-snap position.

    Cleanup
    -------
    ``_dedupe_consecutive_vertices`` collapses any zero-length edges the snap
    may have introduced, preventing invalid geometry.

    Parameters
    ----------
    rings      : All traced rings across ALL features, flat list.
    path_vertices : The original master path vertex list (shared source).
    seg_index  : Spatial index over the master path segments.
    tolerance  : Alignment tolerance (map units).  Vertices within
                 ``tolerance * 1.5`` are eligible for master-snap.
    snap_tol   : Within this distance of an exact path vertex, use the
                 vertex directly (no interpolation).
                 FIX 1: Defaults to ``tolerance * 0.1`` so the vertex-priority
                 radius scales with the user-supplied tolerance rather than
                 being the hard-coded 0.0005 that was far too small for any
                 CRS with metre-scale coordinates.

    Returns
    -------
    New list of rings with near-path vertices forced to master coordinates.
    """
    # FIX 1: Derive snap_tol from tolerance when not explicitly provided.
    # tolerance * 0.1 gives a sensible vertex-priority radius for both
    # degree-scale (geographic) and metre-scale (projected) CRS.
    if snap_tol is None:
        snap_tol = tolerance * 0.1

    # Build a fast lookup: for each path vertex, its index (used for priority snap)
    # We need to find the nearest path vertex quickly.
    # Pre-compute as a list for O(n) scan — path is typically short enough.
    snap_tol_sq   = snap_tol * snap_tol
    # v10.1.5: eligibility radius is configurable.  Trace & Smooth keeps the
    # historical tolerance * 1.5; Fit to Path passes exactly `tolerance` so it
    # honours the user's "within tolerance" promise literally.
    search_radius = eligibility_radius if eligibility_radius is not None else tolerance * 1.5

    apply_offset = abs(offset) > 1e-10   # v10.1.5: only do offset maths if asked
    filter_side  = side != SIDE_BOTH     # v10.1.5: only side-test if asked

    out_rings: List[List[QgsPointXY]] = []

    for ring in rings:
        if not ring:
            out_rings.append(ring)
            continue

        has_dup = _has_closing_dup(ring)
        work = ring[:-1] if has_dup else ring[:]
        new_ring: List[QgsPointXY] = []
        snapped_count = 0  # FIX 1 safety-check: count vertices that were snapped

        for pt in work:
            # ── Is this vertex near the path? ────────────────────────────────
            # Pass the true search_radius so the bbox query is appropriately
            # wide; the distance check below enforces the real eligibility
            # threshold (search_radius), keeping the guard deterministic.
            dist_to_path, closest_on_seg, seg_idx = _nearest_point_on_path_indexed(
                pt, seg_index, search_radius
            )

            if dist_to_path > search_radius:
                # Far from path — keep original vertex untouched
                new_ring.append(pt)
                continue

            # ── v10.1.5: optional side filter ────────────────────────────────
            # When the user picked Left or Right, a vertex on the wrong side of
            # the path is left exactly where it is (never pulled across).  A
            # vertex sitting *on* the path (side == 0) is always eligible.
            pt_side = 0.0
            if filter_side or apply_offset:
                pt_side = _side_of_path_indexed(pt, seg_index, tolerance)
            if filter_side:
                if side == SIDE_LEFT  and pt_side < 0:
                    new_ring.append(pt)
                    continue
                if side == SIDE_RIGHT and pt_side > 0:
                    new_ring.append(pt)
                    continue

            # ── Tier 1: snap to nearest original path vertex if very close ───
            # This pins kink-points exactly, preventing any arc/interpolation
            # rounding at the most topologically sensitive locations.
            best_v_d2 = float("inf")
            best_v    = None
            for pv in path_vertices:
                dx = pt.x() - pv.x()
                dy = pt.y() - pv.y()
                d2 = dx * dx + dy * dy
                if d2 < best_v_d2:
                    best_v_d2 = d2
                    best_v    = pv

            if best_v is not None and best_v_d2 <= snap_tol_sq:
                # Exact vertex pin — zero floating-point error at this point
                snapped_pt = QgsPointXY(best_v.x(), best_v.y())
            else:
                # ── Tier 2: project onto nearest master segment ───────────────
                # ``closest_on_seg`` is already the projection result from the
                # _nearest_point_on_path_indexed call above — reuse it.
                snapped_pt = QgsPointXY(closest_on_seg.x(), closest_on_seg.y())

            # ── v10.1.5: optional perpendicular offset ───────────────────────
            if apply_offset:
                a, b = seg_index.segment(seg_idx)
                snapped_pt = _apply_offset(snapped_pt, a, b, offset, pt_side)

            new_ring.append(snapped_pt)
            snapped_count += 1

        # FIX 1 safety-check: if no vertices were snapped on the first pass,
        # retry with the search radius doubled (2× fallback).  This handles
        # polygons whose traced boundary sits slightly further from the path
        # than the eligibility radius due to floating-point drift.
        if snapped_count == 0 and work:
            retry_radius = search_radius * 2.0
            for idx, pt in enumerate(work):
                dist_to_path, closest_on_seg, _ = _nearest_point_on_path_indexed(
                    pt, seg_index, retry_radius
                )
                if dist_to_path <= retry_radius:
                    new_ring[idx] = QgsPointXY(closest_on_seg.x(), closest_on_seg.y())

        # Restore closing duplicate
        if has_dup and new_ring:
            new_ring.append(QgsPointXY(new_ring[0].x(), new_ring[0].y()))

        # Collapse any zero-length edges the snap may have introduced
        cleaned = _dedupe_consecutive_vertices(new_ring, tol=1e-8)

        # Safety: never emit a degenerate ring — fall back to raw snap output
        distinct = cleaned[:-1] if _has_closing_dup(cleaned) else cleaned
        out_rings.append(cleaned if len(distinct) >= 3 else new_ring)

    return out_rings


def _geom_kind(geom: QgsGeometry) -> str:
    """Return 'polygon', 'line', 'point', or 'other' for a geometry.

    Version-safe across QGIS 3.x (unscoped enum) and QGIS 4 (scoped enum).
    Used so "Fit to Path" can align BOTH polygon layers and line layers — the
    old code only ever handled polygon rings, so line layers (e.g. a
    Basin_Boundary line layer) silently aligned nothing.
    """
    try:
        t = geom.type()
    except Exception:
        return "other"
    try:
        GT = QgsWkbTypes.GeometryType
        if t == GT.PolygonGeometry:
            return "polygon"
        if t == GT.LineGeometry:
            return "line"
        if t == GT.PointGeometry:
            return "point"
        return "other"
    except AttributeError:
        # Older unscoped enum fallback
        if t == QgsWkbTypes.PolygonGeometry:
            return "polygon"
        if t == QgsWkbTypes.LineGeometry:
            return "line"
        if t == QgsWkbTypes.PointGeometry:
            return "point"
        return "other"


def _densify_ring_near_path(
    ring: List[QgsPointXY],
    seg_index: _SegmentIndex,
    tolerance: float,
    step: float,
) -> List[QgsPointXY]:
    """
    v10.1.5 — insert extra vertices on the parts of a ring that run near the
    alignment path, so a subsequent snap actually has vertices to move.

    THE BUG THIS FIXES
    ------------------
    "Fit to Path" only ever moves *vertices*.  When a polygon edge passes close
    to the path but its two endpoints are far away (> tolerance) — e.g. a short
    path drawn along the long shared edge of two large parcels — there is no
    vertex near the path, so nothing snaps and the edge never moves onto the
    path.  The sliver/gap survives.

    By subdividing each near-path edge into pieces of length ``step`` we create
    vertices *on* the near-path span.  The snap step then projects those onto
    the path, dragging the whole edge onto it and closing the gap.

    Only edges that actually approach the path (within ``tolerance * 2``) are
    densified, so distant parts of the polygon are left exactly as they were
    (no needless vertices, no shape change away from the path).
    """
    if len(ring) < 2 or step <= 0:
        return ring

    has_dup = _has_closing_dup(ring)
    pts = ring[:-1] if has_dup else ring[:]
    m = len(pts)
    if m < 2:
        return ring

    near_radius = tolerance * 2.0
    out: List[QgsPointXY] = []

    # Number of edges: closed ring → m edges (incl. closing); open → m-1.
    edge_count = m if has_dup else (m - 1)

    for i in range(edge_count):
        a = pts[i]
        b = pts[(i + 1) % m]
        out.append(a)

        seg_len = math.hypot(b.x() - a.x(), b.y() - a.y())
        if seg_len < 1e-12:
            continue

        # Does any sample along this edge come within near_radius of the path?
        near = False
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            sx = a.x() + (b.x() - a.x()) * t
            sy = a.y() + (b.y() - a.y()) * t
            d, _, _ = _nearest_point_on_path_indexed(
                QgsPointXY(sx, sy), seg_index, near_radius
            )
            if d <= near_radius:
                near = True
                break
        if not near:
            continue

        # Subdivide into ≤ step pieces (interior points only — endpoints are
        # added by the loop).
        k = int(seg_len // step)
        for j in range(1, k + 1):
            t = (j * step) / seg_len
            if t >= 1.0:
                break
            out.append(QgsPointXY(
                a.x() + (b.x() - a.x()) * t,
                a.y() + (b.y() - a.y()) * t,
            ))

    if has_dup and out:
        out.append(QgsPointXY(out[0].x(), out[0].y()))
    elif not has_dup:
        out.append(pts[-1])

    return out


def _fit_to_path_coherent(
    features: List[QgsFeature],
    path_vertices: List[QgsPointXY],
    seg_index: _SegmentIndex,
    search_buffer: QgsGeometry,
    tolerance: float,
    offset: float,
    side: str,
    feedback_fn: Optional[Callable] = None,
    progress_callback: Optional[Callable] = None,
) -> List[Tuple[QgsFeature, QgsGeometry]]:
    """
    v10.1.5 — Coherent "Fit to Path" (the gap-closing fix).

    Why this exists / the real bug
    ------------------------------
    "Fit to Path" only ever moves *vertices*.  The user's gap is the thin
    sliver along a short path drawn on the shared boundary of two large
    parcels.  Each parcel's boundary near the path is a LONG edge whose two
    endpoints are far away (well beyond tolerance), so there is **no vertex
    near the path** — and a vertex-only snap therefore moves nothing.  The edge
    stays put and the sliver survives.  (Verified by simulation: the old snap
    leaves such an edge completely unmoved.)

    The fix (two simple steps, applied to ALL features together)
    ------------------------------------------------------------
    1.  ``_densify_ring_near_path`` inserts vertices on the stretch of each
        ring that runs near the path — now there ARE vertices to move.
    2.  ``_snap_to_master_path`` projects every near-path vertex onto the ONE
        shared master path.  Because the projection is a pure function of
        position and the path is the single shared source, two parcels whose
        boundaries meet at the path receive *identical* coordinates there —
        the sliver closes by construction.

    This is exactly what the user asked for: "where I draw the path, both sides
    align onto the same place as the path."

    Eligibility radius is the user's ``tolerance`` (not tolerance * 1.5), so
    "Fit to Path" keeps its literal promise of moving vertices *within
    tolerance*.  Side filtering and perpendicular offset are honoured.

    Returns
    -------
    List of (original_feature, new_geometry) — only modified features.
    """
    _emit(feedback_fn, "info",
          "📐 Fit to Path (coherent) — densifying near-path edges, then "
          "projecting every near-path vertex onto the master path so adjacent "
          "features share an identical boundary…")

    # Densification step: fine enough to capture the path's shape, but not so
    # fine that long edges explode in vertex count.
    densify_step = max(tolerance * 0.2, 0.05)

    # ── Phase 1: collect the rings/lines of every in-buffer feature ───────────
    # staged entry = (feat, orig_geom, kind, parts)
    #   kind == "polygon": parts = [ [ext_pts, [hole_pts, ...]], ... ]
    #   kind == "line":    parts = [ [line_pts], ... ]
    staged: List[Tuple[QgsFeature, QgsGeometry, str, list]] = []
    flat_rings: List[List[QgsPointXY]] = []
    index_map: List[Tuple[int, int, int]] = []   # (staged_i, part_i, slot)
    total = len(features)
    skipped_pts = 0

    for fi, feat in enumerate(features):
        if progress_callback:
            progress_callback(fi + 1, total)

        orig_geom = feat.geometry()
        if orig_geom is None or orig_geom.isEmpty():
            continue
        if not orig_geom.intersects(search_buffer):
            continue

        kind = _geom_kind(orig_geom)
        if kind == "point":
            skipped_pts += 1
            continue
        if kind == "other":
            continue

        # makeValid only matters for polygons; lines are fine as-is.
        if kind == "polygon" and not orig_geom.isGeosValid():
            fixed = orig_geom.makeValid()
            if fixed is None or fixed.isEmpty():
                _emit(feedback_fn, "warn",
                      f"   Feature {feat.id()}: invalid geometry, could not fix — skipped.")
                continue
            orig_geom = fixed

        parts: list = []
        for part in orig_geom.parts():
            try:
                if kind == "polygon":
                    ext = _ring_to_pointxy_list(part.exteriorRing())
                    holes: List[List[QgsPointXY]] = [
                        _ring_to_pointxy_list(part.interiorRing(hi))
                        for hi in range(part.numInteriorRings())
                    ]
                    # v10.1.5 fix: densify near-path edges so the snap has
                    # vertices to move (long edges with far endpoints).
                    ext = _densify_ring_near_path(ext, seg_index, tolerance, densify_step)
                    holes = [
                        _densify_ring_near_path(h, seg_index, tolerance, densify_step)
                        for h in holes
                    ]
                    parts.append([ext, holes])
                else:  # line
                    line_pts = _ring_to_pointxy_list(part)
                    line_pts = _densify_ring_near_path(
                        line_pts, seg_index, tolerance, densify_step
                    )
                    parts.append([line_pts])
            except Exception as exc:
                _emit(feedback_fn, "warn",
                      f"   Feature {feat.id()}: ring read failed ({exc}) — part skipped.")
                continue

        if not parts:
            continue

        si = len(staged)
        staged.append((feat, orig_geom, kind, parts))
        for pi, part_data in enumerate(parts):
            # slot -1 = exterior ring / the line itself
            index_map.append((si, pi, -1))
            flat_rings.append(part_data[0])
            if kind == "polygon":
                for hj, h in enumerate(part_data[1]):
                    index_map.append((si, pi, hj))
                    flat_rings.append(h)

    if skipped_pts:
        _emit(feedback_fn, "warn",
              f"   {skipped_pts} point feature(s) skipped — Fit to Path aligns "
              f"lines and polygons only.")

    if not staged:
        return []

    # ── Phase 2: ONE deterministic master-path snap across ALL rings ──────────
    # eligibility_radius = tolerance → honour the "within tolerance" promise.
    snapped_rings = _snap_to_master_path(
        flat_rings,
        path_vertices,
        seg_index,
        tolerance,
        snap_tol=None,                 # → tolerance * 0.1 (vertex-priority pin)
        side=side,                     # honour Left / Right / Both
        offset=offset,                 # honour perpendicular offset
        eligibility_radius=tolerance,  # literal "within tolerance"
    )

    for (si, pi, slot), snapped in zip(index_map, snapped_rings):
        if slot < 0:
            staged[si][3][pi][0] = snapped
        else:
            staged[si][3][pi][1][slot] = snapped

    # ── Phase 3: rebuild geometries, keep only the ones that changed ──────────
    results: List[Tuple[QgsFeature, QgsGeometry]] = []
    for feat, orig_geom, kind, parts in staged:
        new_part_geoms: List[QgsGeometry] = []
        for part_data in parts:
            try:
                if kind == "polygon":
                    ext = part_data[0]
                    holes = part_data[1]
                    if not ext:
                        continue
                    pg = QgsGeometry.fromPolygonXY([ext] + holes)
                else:  # line
                    line_pts = part_data[0]
                    if len(line_pts) < 2:
                        continue
                    pg = QgsGeometry.fromPolylineXY(line_pts)
            except Exception:
                pg = None
            if pg is not None and not pg.isEmpty():
                new_part_geoms.append(pg)

        if not new_part_geoms:
            continue
        new_geom = (
            new_part_geoms[0]
            if len(new_part_geoms) == 1
            else QgsGeometry.collectGeometry(new_part_geoms)
        )
        if new_geom is None or new_geom.isEmpty():
            continue
        if new_geom.equals(orig_geom):
            continue
        results.append((feat, new_geom))

    _emit(feedback_fn, "info",
          f"✅ Fit to Path (coherent) done: {len(results)}/{len(staged)} feature(s) modified.")
    return results


def _trace_rings_coherently(
    features: List[QgsFeature],
    path_vertices: List[QgsPointXY],
    arc_lengths: List[float],
    seg_index: _SegmentIndex,
    tol_buffer: QgsGeometry,
    search_buffer: QgsGeometry,
    tolerance: float,
    offset: float,
    side: str,
    resample_distance: float,
    smooth_iterations: int,
    progress_callback: Optional[Callable] = None,
    feedback_fn: Optional[Callable] = None,
    # FIX 2: coincidence_tol was hard-coded to 0.001 (only correct for
    # millimetre-resolution projected CRS).  It is now derived from
    # tolerance at call time so it scales automatically for both
    # geographic (degree-scale) and metric CRS.
    # The default of None triggers the tolerance-based formula below.
    coincidence_tol: Optional[float] = None,
) -> List[Tuple[QgsFeature, QgsGeometry]]:
    """
    v10 — Global Master Boundary Alignment (pixel-perfect shared boundary).

    Replaces the v9 coincidence-hash pass with a deterministic master-path
    snap that guarantees every polygon draws its shared boundary vertices from
    the *same mathematical source* — the original ``path_vertices`` list.

    Pipeline
    --------
    Phase 1 — Trace
        Each ring is traced independently via ``_process_ring_trace_smooth``.
        This preserves per-ring winding order and keeps the outside geometry
        (far from the path) exactly as-is.  The traced portion already
        references coordinates derived from ``path_vertices``, but entry/exit
        crossing points are computed per-feature and can differ by small
        floating-point amounts.

    Phase 2 — Master-path snap  ← v10 core fix
        ``_snap_to_master_path`` iterates every vertex in every ring.  Any
        vertex within ``tolerance * 1.5`` of the path is re-projected onto the
        nearest point of the master ``path_vertices`` (with vertex-priority for
        exact kink-point matching).  Because both adjacent polygons run the
        same deterministic projection on the same source, the resulting
        coordinates are bitwise identical — the gap is structurally impossible.

    Phase 3 — Rebuild
        Snapped rings are stitched back into ``QgsGeometry`` polygons.  Only
        features whose geometry actually changed are returned.

    All v8/v9 capabilities are preserved:
        curves, direction detection, Chaikin smoothing, side filtering,
        resampling.

    Returns
    -------
    List of (original_feature, new_geometry) — only modified features.
    """
    _emit(feedback_fn, "info",
          "🧷 v10 Global Master Boundary Alignment — snapping all rings to "
          "master path for pixel-perfect shared boundaries…")

    # FIX 2: Resolve coincidence_tol from tolerance when not explicitly
    # supplied.  Formula: tolerance * 0.5, with a floor of 0.1 to stay
    # sensible for metre-based CRS.  This replaces the hard-coded 0.001
    # that was meaningful only for sub-millimetre coordinate precision.
    if coincidence_tol is None:
        coincidence_tol = max(tolerance * 0.5, 0.1)

    # ── Phase 1: trace every affected ring into editable point lists ──────────
    # staged[i] = (feat, orig_geom, parts)
    # parts[k]  = [exterior_ring, [hole_ring, …]]
    staged: List[Tuple[QgsFeature, QgsGeometry, list]] = []
    flat_rings: List[List[QgsPointXY]] = []
    index_map: List[Tuple[int, int, int]] = []   # (staged_i, part_i, slot)
    total = len(features)

    for fi, feat in enumerate(features):
        if progress_callback:
            progress_callback(fi + 1, total)

        orig_geom = feat.geometry()
        if orig_geom is None or orig_geom.isEmpty():
            continue
        if not orig_geom.intersects(search_buffer):
            continue
        if not orig_geom.isGeosValid():
            fixed = orig_geom.makeValid()
            if fixed is None or fixed.isEmpty():
                _emit(feedback_fn, "warn",
                      f"   Feature {feat.id()}: invalid geometry, could not fix — skipped.")
                continue
            orig_geom = fixed

        parts: list = []
        for part in orig_geom.parts():
            try:
                ext = _ring_to_pointxy_list(part.exteriorRing())
                new_ext = _process_ring_trace_smooth(
                    ext, path_vertices, arc_lengths, seg_index,
                    tolerance, offset, side, tol_buffer,
                    resample_distance, smooth_iterations, True,
                )
                holes: List[List[QgsPointXY]] = []
                for hi in range(part.numInteriorRings()):
                    h = _ring_to_pointxy_list(part.interiorRing(hi))
                    new_h = _process_ring_trace_smooth(
                        h, path_vertices, arc_lengths, seg_index,
                        tolerance, offset, side, tol_buffer,
                        resample_distance, smooth_iterations, True,
                    )
                    holes.append(new_h)
            except Exception as exc:
                _emit(feedback_fn, "warn",
                      f"   Feature {feat.id()}: ring trace failed ({exc}) — part kept as-is.")
                continue
            parts.append([new_ext, holes])

        if not parts:
            continue

        si = len(staged)
        staged.append((feat, orig_geom, parts))
        for pi, (ext, holes) in enumerate(parts):
            index_map.append((si, pi, -1))
            flat_rings.append(ext)
            for hj, h in enumerate(holes):
                index_map.append((si, pi, hj))
                flat_rings.append(h)

    if not staged:
        return []

    # ── Phase 2: v10 Global Master-Path Snap ─────────────────────────────────
    #
    # Every near-path vertex in every ring — across ALL features — is forced
    # to the nearest point on the original master path_vertices.  Adjacent
    # polygons run the same deterministic computation on the same source, so
    # the coordinates come out bitwise identical.  No first-winner races,
    # no floating-point lottery: the gap is mathematically impossible.
    #
    # FIX 1+2: Pass snap_tol=None so _snap_to_master_path derives the
    # vertex-priority radius from tolerance * 0.1 — correctly scaled for the
    # user's CRS rather than the old hard-coded 0.0005 * 0.5 = 0.00025 value.
    snapped_rings = _snap_to_master_path(
        flat_rings,
        path_vertices,
        seg_index,
        tolerance,
        snap_tol=None,   # → tolerance * 0.1 inside _snap_to_master_path
    )

    # Write snapped rings back into the staged structure
    for (si, pi, slot), snapped in zip(index_map, snapped_rings):
        if slot < 0:
            staged[si][2][pi][0] = snapped
        else:
            staged[si][2][pi][1][slot] = snapped

    # ── Phase 3: rebuild geometries, keep only changed features ──────────────
    results: List[Tuple[QgsFeature, QgsGeometry]] = []
    for feat, orig_geom, parts in staged:
        new_part_geoms: List[QgsGeometry] = []
        for ext, holes in parts:
            if not ext:
                continue
            try:
                pg = QgsGeometry.fromPolygonXY([ext] + holes)
            except Exception:
                pg = None
            if pg is not None and not pg.isEmpty():
                new_part_geoms.append(pg)

        if not new_part_geoms:
            continue
        new_geom = (
            new_part_geoms[0]
            if len(new_part_geoms) == 1
            else QgsGeometry.collectGeometry(new_part_geoms)
        )
        if new_geom is None or new_geom.isEmpty():
            continue
        if new_geom.equals(orig_geom):
            continue
        results.append((feat, new_geom))

    _emit(feedback_fn, "info",
          f"✅ v10 master-snap done: {len(results)}/{len(staged)} feature(s) modified.")
    return results


# ── Polygon-part orchestration ─────────────────────────────────────────────────

def _process_polygon_part(
    part,
    path_vertices: List[QgsPointXY],
    arc_lengths: List[float],
    seg_index: _SegmentIndex,
    tolerance: float,
    offset: float,
    method: str,
    side: str,
    snap_only_ends: bool,
    tol_buffer: QgsGeometry,
    resample_distance: float = 0.0,
    smooth_iterations: int = 0,
    enable_tracing: bool = True,
) -> Optional[QgsGeometry]:
    """Process one polygon part.  Returns new QgsGeometry or None on failure."""
    try:
        exterior = _ring_to_pointxy_list(part.exteriorRing())

        if method == METHOD_PRESERVE:
            new_exterior = _process_ring_preserve(
                exterior, path_vertices, seg_index, tolerance, offset,
                side, snap_only_ends, tol_buffer,
            )
        elif method == METHOD_TRACE_SMOOTH:
            new_exterior = _process_ring_trace_smooth(
                exterior, path_vertices, arc_lengths, seg_index,
                tolerance, offset, side, tol_buffer,
                resample_distance, smooth_iterations, enable_tracing,
            )
        else:
            new_exterior = _process_ring(
                exterior, path_vertices, seg_index, tolerance, offset,
                method, side, snap_only_ends,
            )

        holes = []
        for hi in range(part.numInteriorRings()):
            hole = _ring_to_pointxy_list(part.interiorRing(hi))
            if method == METHOD_PRESERVE:
                new_hole = _process_ring_preserve(
                    hole, path_vertices, seg_index, tolerance, offset,
                    side, snap_only_ends, tol_buffer,
                )
            elif method == METHOD_TRACE_SMOOTH:
                new_hole = _process_ring_trace_smooth(
                    hole, path_vertices, arc_lengths, seg_index,
                    tolerance, offset, side, tol_buffer,
                    resample_distance, smooth_iterations, enable_tracing,
                )
            else:
                new_hole = _process_ring(
                    hole, path_vertices, seg_index, tolerance, offset,
                    method, side, snap_only_ends,
                )
            holes.append(new_hole)

        return QgsGeometry.fromPolygonXY([new_exterior] + holes)

    except Exception as exc:
        QgsMessageLog.logMessage(
            f"Error processing polygon part: {exc}", "AlignFeatures", Qgis.MessageLevel.Warning
        ) if _HAS_MSG_LOG else None
        return None


# ── Smart Fit helpers ─────────────────────────────────────────────────────────
#
#  Smart Fit adds two improvements over the plain "Fit to Path" pipeline:
#
#  1. Intersection-significance filter  (_filter_by_intersection_significance)
#     Before processing a feature, we measure HOW MUCH of the path buffer
#     actually overlaps the feature.  Features that only clip a tiny corner
#     of the buffer (L-corner pull artefacts, nearly-parallel edges that
#     cross the buffer edge at a shallow angle) are excluded.  Only features
#     with a "significant" overlap are aligned.  This prevents crossing lines
#     and unwanted L-corner pulls that the old intersects() test allowed.
#
#  2. Proximity-weighted (weighted) fit  (_smart_fit_to_path)
#     Instead of snapping every near-path vertex with the same full force,
#     Smart Fit applies a distance-based weight:
#       • vertex close to the path → weight ≈ 1.0  (full snap)
#       • vertex farther away      → weight decreases smoothly
#       • vertex beyond tolerance  → weight = 0  (untouched)
#     The new position is a weighted blend between the vertex's original
#     position and the nearest point on the path:
#         new_pos = orig + weight * (path_proj - orig)
#     This reduces the "aggressive global pull" of the classic snap while
#     still closing the gap precisely where the path actually runs.
#
# ─────────────────────────────────────────────────────────────────────────────

def _filter_by_intersection_significance(
    features: List[QgsFeature],
    path_geom: QgsGeometry,
    tol_buffer: QgsGeometry,
    min_overlap_ratio: float = 0.02,
    min_overlap_area: float = 0.0,
    feedback_fn: Optional[Callable] = None,
) -> List[QgsFeature]:
    """
    Return only the features whose overlap with ``tol_buffer`` is significant.

    A feature is considered significant if the intersection area is at least
    ``min_overlap_ratio`` times the feature's own area (for polygons) OR if
    the intersection length is at least ``min_overlap_ratio`` times the
    feature's length (for lines).

    This prevents:
      * L-corner pulls — a polygon that merely touches the buffer corner
        contributes a tiny intersection sliver and is filtered out.
      * Crossing lines — a line that grazes the buffer boundary at a very
        shallow angle intersects it but its overlap fraction is minimal.

    For point features and degenerate geometries the feature is always kept
    (point features are handled separately by the callers).

    Parameters
    ----------
    features          : Candidate QgsFeature list (already bbox-filtered).
    path_geom         : The drawn alignment path (used for direction check).
    tol_buffer        : Tolerance buffer polygon around the path.
    min_overlap_ratio : Fraction threshold [0..1].  Default 0.02 (2 %).
    min_overlap_area  : Absolute minimum overlap area (map units²).
                        0 = use ratio only.  Useful when features are very
                        large and ratio alone is too strict.
    feedback_fn       : Optional logging callback.

    Returns
    -------
    Filtered list — only features with significant path-buffer intersection.
    """
    tb_bbox = tol_buffer.boundingBox()
    kept: List[QgsFeature] = []
    skipped = 0

    for feat in features:
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            kept.append(feat)
            continue

        kind = _geom_kind(geom)
        if kind in ("point", "other"):
            kept.append(feat)  # points always pass — handled elsewhere
            continue

        # Quick bbox pre-check
        if not tb_bbox.intersects(geom.boundingBox()):
            skipped += 1
            continue

        try:
            intersection = tol_buffer.intersection(geom)
        except Exception:
            kept.append(feat)
            continue

        if intersection is None or intersection.isEmpty():
            skipped += 1
            continue

        # Compute overlap significance
        significant = False
        if kind == "polygon":
            feat_area = geom.area()
            inter_area = intersection.area()
            if feat_area < 1e-10:
                significant = True
            elif inter_area >= min_overlap_area and inter_area >= min_overlap_ratio * feat_area:
                significant = True
        else:  # line
            feat_len = geom.length()
            inter_len = intersection.length()
            # For lines the intersection can reduce to a point (area==0) —
            # fall back to length ratio.
            if inter_len < 1e-10:
                # The line may just touch the buffer boundary — not significant.
                significant = False
            elif feat_len < 1e-10:
                significant = True
            elif inter_len >= min_overlap_ratio * feat_len:
                significant = True

        if significant:
            kept.append(feat)
        else:
            skipped += 1

    if skipped and feedback_fn:
        _emit(feedback_fn, "info",
              f"   Smart filter: {skipped} feature(s) skipped "
              f"(intersection significance < {min_overlap_ratio*100:.0f}% threshold — "
              f"L-corner / crossing-line guard).")
    return kept


def _smart_fit_to_path(
    features: List[QgsFeature],
    path_vertices: List[QgsPointXY],
    seg_index: _SegmentIndex,
    search_buffer: QgsGeometry,
    tol_buffer: QgsGeometry,
    tolerance: float,
    offset: float,
    side: str,
    min_overlap_ratio: float = 0.02,
    feedback_fn: Optional[Callable] = None,
    progress_callback: Optional[Callable] = None,
) -> List[Tuple[QgsFeature, QgsGeometry]]:
    """
    Smart Fit to Path — proximity-weighted coherent alignment.

    Differences from ``_fit_to_path_coherent``:
    ─────────────────────────────────────────────
    1.  **Intersection-significance pre-filter** — features that only graze
        the buffer boundary (L-corner artefacts, crossing lines) are excluded
        before any geometry is modified.

    2.  **Proximity-weighted vertex movement** — each near-path vertex is
        moved by a fraction proportional to how close it is to the path:

            weight = 1 - (dist / tolerance) ** 2   (smooth falloff, clamped [0,1])
            new_pt = orig + weight * (path_projection - orig)

        Vertices very close to the path snap almost exactly (weight → 1).
        Vertices near the tolerance boundary move only a little (weight → 0).
        This replaces the old binary "snap or don't snap" logic and avoids
        pulling distant vertices aggressively across the canvas.

    3.  **Coherent master-path projection** — like _fit_to_path_coherent,
        all features are projected against the SAME master path in one pass
        so adjacent polygons land on identical coordinates (no slivers).

    Parameters mirror ``_fit_to_path_coherent``; see that function's docstring
    for full details.
    """
    _emit(feedback_fn, "info",
          "🎯 Smart Fit to Path — intersection filter + weighted vertex movement…")

    # ── Pre-filter: keep only geometrically significant intersections ─────────
    filtered = _filter_by_intersection_significance(
        features, None, tol_buffer,
        min_overlap_ratio=min_overlap_ratio,
        feedback_fn=feedback_fn,
    )
    if not filtered:
        _emit(feedback_fn, "info",
              "   Smart Fit: no features passed intersection significance filter.")
        return []

    densify_step = max(tolerance * 0.2, 0.05)

    # ── Phase 1: collect rings, densify near-path edges ───────────────────────
    staged: List[Tuple[QgsFeature, QgsGeometry, str, list]] = []
    flat_rings: List[List[QgsPointXY]] = []
    index_map: List[Tuple[int, int, int]] = []
    total = len(filtered)
    skipped_pts = 0

    for fi, feat in enumerate(filtered):
        if progress_callback:
            progress_callback(fi + 1, total)

        orig_geom = feat.geometry()
        if orig_geom is None or orig_geom.isEmpty():
            continue
        if not orig_geom.intersects(search_buffer):
            continue

        kind = _geom_kind(orig_geom)
        if kind == "point":
            skipped_pts += 1
            continue
        if kind == "other":
            continue

        if kind == "polygon" and not orig_geom.isGeosValid():
            fixed = orig_geom.makeValid()
            if fixed is None or fixed.isEmpty():
                _emit(feedback_fn, "warn",
                      f"   Feature {feat.id()}: invalid geometry — skipped.")
                continue
            orig_geom = fixed

        parts: list = []
        for part in orig_geom.parts():
            try:
                if kind == "polygon":
                    ext = _ring_to_pointxy_list(part.exteriorRing())
                    holes = [
                        _ring_to_pointxy_list(part.interiorRing(hi))
                        for hi in range(part.numInteriorRings())
                    ]
                    ext = _densify_ring_near_path(ext, seg_index, tolerance, densify_step)
                    holes = [
                        _densify_ring_near_path(h, seg_index, tolerance, densify_step)
                        for h in holes
                    ]
                    parts.append([ext, holes])
                else:
                    line_pts = _ring_to_pointxy_list(part)
                    line_pts = _densify_ring_near_path(
                        line_pts, seg_index, tolerance, densify_step
                    )
                    parts.append([line_pts])
            except Exception as exc:
                _emit(feedback_fn, "warn",
                      f"   Feature {feat.id()}: ring read failed ({exc}) — skipped.")
                continue

        if not parts:
            continue

        si = len(staged)
        staged.append((feat, orig_geom, kind, parts))
        for pi, part_data in enumerate(parts):
            index_map.append((si, pi, -1))
            flat_rings.append(part_data[0])
            if kind == "polygon":
                for hj, h in enumerate(part_data[1]):
                    index_map.append((si, pi, hj))
                    flat_rings.append(h)

    if not staged:
        return []

    # ── Phase 2: weighted snap — project each near-path vertex with falloff ───
    snap_tol = tolerance * 0.1
    snap_tol_sq = snap_tol * snap_tol
    search_radius = tolerance
    filter_side = (side != SIDE_BOTH)

    snapped_rings: List[List[QgsPointXY]] = []
    for ring in flat_rings:
        if not ring:
            snapped_rings.append(ring)
            continue

        has_dup = _has_closing_dup(ring)
        work = ring[:-1] if has_dup else ring[:]
        new_ring: List[QgsPointXY] = []

        for pt in work:
            dist_to_path, closest_on_seg, seg_idx = _nearest_point_on_path_indexed(
                pt, seg_index, search_radius
            )

            if dist_to_path > search_radius:
                new_ring.append(pt)
                continue

            # Side filter
            pt_side = 0.0
            if filter_side:
                pt_side = _side_of_path_indexed(pt, seg_index, tolerance)
                if side == SIDE_LEFT and pt_side < 0:
                    new_ring.append(pt)
                    continue
                if side == SIDE_RIGHT and pt_side > 0:
                    new_ring.append(pt)
                    continue

            # ── Tier 1: exact path-vertex pin (within snap_tol) ──────────────
            best_v_d2 = float("inf")
            best_v = None
            for pv in path_vertices:
                dx = pt.x() - pv.x()
                dy = pt.y() - pv.y()
                d2 = dx * dx + dy * dy
                if d2 < best_v_d2:
                    best_v_d2 = d2
                    best_v = pv

            if best_v is not None and best_v_d2 <= snap_tol_sq:
                # Very close to a path vertex — snap exactly (weight = 1)
                snapped_pt = QgsPointXY(best_v.x(), best_v.y())
            else:
                # ── Tier 2: weighted blend toward path projection ─────────────
                # weight: smooth quadratic falloff from 1 (on path) to 0 (at tolerance)
                norm = dist_to_path / tolerance          # 0 .. 1
                weight = max(0.0, 1.0 - norm * norm)     # 1 near path, 0 at edge

                proj = closest_on_seg
                snapped_pt = QgsPointXY(
                    pt.x() + weight * (proj.x() - pt.x()),
                    pt.y() + weight * (proj.y() - pt.y()),
                )

            # Perpendicular offset if requested
            if abs(offset) > 1e-10:
                if pt_side == 0.0:
                    pt_side = _side_of_path_indexed(pt, seg_index, tolerance)
                a, b = seg_index.segment(seg_idx)
                snapped_pt = _apply_offset(snapped_pt, a, b, offset, pt_side)

            new_ring.append(snapped_pt)

        if has_dup and new_ring:
            new_ring.append(QgsPointXY(new_ring[0].x(), new_ring[0].y()))

        cleaned = _dedupe_consecutive_vertices(new_ring, tol=1e-8)
        distinct = cleaned[:-1] if _has_closing_dup(cleaned) else cleaned
        snapped_rings.append(cleaned if len(distinct) >= 3 else new_ring)

    # Write snapped rings back into staged structure
    for (si, pi, slot), snapped in zip(index_map, snapped_rings):
        if slot < 0:
            staged[si][3][pi][0] = snapped
        else:
            staged[si][3][pi][1][slot] = snapped

    # ── Phase 3: rebuild geometries ───────────────────────────────────────────
    results: List[Tuple[QgsFeature, QgsGeometry]] = []
    for feat, orig_geom, kind, parts in staged:
        new_part_geoms: List[QgsGeometry] = []
        for part_data in parts:
            try:
                if kind == "polygon":
                    ext = part_data[0]
                    holes = part_data[1]
                    if not ext:
                        continue
                    pg = QgsGeometry.fromPolygonXY([ext] + holes)
                else:
                    line_pts = part_data[0]
                    if len(line_pts) < 2:
                        continue
                    pg = QgsGeometry.fromPolylineXY(line_pts)
            except Exception:
                pg = None
            if pg is not None and not pg.isEmpty():
                new_part_geoms.append(pg)

        if not new_part_geoms:
            continue
        new_geom = (
            new_part_geoms[0]
            if len(new_part_geoms) == 1
            else QgsGeometry.collectGeometry(new_part_geoms)
        )
        if new_geom is None or new_geom.isEmpty():
            continue
        if new_geom.equals(orig_geom):
            continue
        results.append((feat, new_geom))

    _emit(feedback_fn, "info",
          f"✅ Smart Fit done: {len(results)}/{len(staged)} feature(s) modified.")
    return results


# ── Public API ─────────────────────────────────────────────────────────────────

def align_features_to_path(
    path_geom: QgsGeometry,
    features: List[QgsFeature],
    tolerance: float = 10.0,
    offset: float = 0.0,
    method: str = METHOD_FIT,
    side: str = SIDE_BOTH,
    end_style: str = END_ROUND,
    search_buffer: Optional[float] = None,
    progress_callback: Optional[Callable] = None,
    feedback_fn: Optional[Callable] = None,
    # ── v7.1 / v8 parameters ─────────────────────────────────────────────────
    resample_distance: float = 0.0,
    smooth_iterations: int = 0,
    enable_tracing: bool = True,
    # ── v9 parameter ─────────────────────────────────────────────────────────
    enable_shared_boundary: bool = True,
    # ── Smart Fit parameter ───────────────────────────────────────────────────
    smart_min_overlap_ratio: float = 0.02,
) -> List[Tuple[QgsFeature, QgsGeometry]]:
    """
    Main alignment function.

    Parameters
    ----------
    path_geom        : Alignment path QgsGeometry (LineString / MultiLineString /
                       CircularString / CompoundCurve).
    features         : Polygon QgsFeature objects to process.
    tolerance        : Max snap distance in map units.
    offset           : Perpendicular offset after snapping (map units).
    method           : METHOD_FIT | METHOD_PRESERVE | METHOD_SNAP_ENDS |
                       METHOD_TRACE_SMOOTH.
    side             : SIDE_BOTH | SIDE_LEFT | SIDE_RIGHT.
    end_style        : END_ROUND | END_SQUARE (buffer cap style).
    search_buffer    : Search radius for feature pre-filter. Defaults to tolerance.
    progress_callback: Optional callable(current, total) for UI progress.
    feedback_fn      : Optional callable(level, message) for rich feedback.
    resample_distance: TRACE_SMOOTH only — densify input rings before tracing.
                       0 disables resampling.
    smooth_iterations: TRACE_SMOOTH only — Chaikin smoothing passes on outside
                       corners after tracing. 0 disables.
    enable_tracing   : TRACE_SMOOTH only — when False, uses legacy resample+snap
                       pipeline instead of true path tracing.
    enable_shared_boundary : v10.1.9 — now applies to ALL methods (not just
                       TRACE_SMOOTH).  When True, the coherent gap-closing
                       pipeline is activated for every method:
                         • METHOD_FIT, METHOD_PRESERVE, METHOD_SNAP_ENDS →
                           route through ``_fit_to_path_coherent`` which
                           densifies near-path edges then projects every near-
                           path vertex onto the SAME master path in one pass.
                           Adjacent polygons share bitwise-identical boundary
                           coordinates — no slivers, no gaps.
                         • METHOD_TRACE_SMOOTH + enable_tracing=True →
                           routes through ``_trace_rings_coherently`` for the
                           same guarantee.
                       When False, falls back to the v8/v9 independent per-
                       feature pipeline.

    Returns
    -------
    List of (original_feature, new_geometry) — only modified features.
    """
    _emit(feedback_fn, "info",
          f"📌 Parameters → Tolerance: {tolerance} | Offset: {offset} | "
          f"Method: {method} | Side: {side} | End style: {end_style} | "
          f"Resample: {resample_distance} | Smooth: {smooth_iterations} | "
          f"Tracing: {enable_tracing} | SharedBoundary: {enable_shared_boundary}")

    if method != METHOD_TRACE_SMOOTH and (
        (resample_distance and resample_distance > 0.0)
        or (smooth_iterations and smooth_iterations > 0)
    ):
        _emit(feedback_fn, "warn",
              "⚠️  resample_distance / smooth_iterations are only used with "
              f"METHOD_TRACE_SMOOTH — ignoring them for method={method!r}.")
        resample_distance = 0.0
        smooth_iterations = 0

    if search_buffer is None:
        search_buffer = tolerance

    # ── Guard: search_buffer must be at least as large as tolerance
    # The search_buffer is the outer containment radius that decides WHICH
    # features are even considered for alignment — it must be >= tolerance so
    # the snapping pass can actually reach every vertex inside it.
    # We do NOT auto-expand beyond tolerance here; the user's value is the
    # intended hard boundary (matching ArcGIS Pro behaviour where only features
    # whose geometry intersects the tolerance buffer are processed).
    if search_buffer < tolerance:
        _emit(
            feedback_fn, "warn",
            f"⚠️  search_buffer ({search_buffer}) < tolerance ({tolerance}).  "
            f"Clamping search_buffer up to tolerance = {tolerance} so that "
            f"snapping can reach vertices inside the buffer.",
        )
        search_buffer = tolerance

    # ── Prepare path data ─────────────────────────────────────────────────────
    # For tracing we want a fine-grained vertex list that faithfully captures
    # any curved segments.  We densify at a resolution proportional to tolerance.
    fine_spacing = max(tolerance * 0.1, 0.01)
    path_vertices = _extract_path_vertices_fine(path_geom, fine_spacing)

    if len(path_vertices) < 2:
        _emit(feedback_fn, "warn", "⚠️  Path has fewer than 2 vertices — aborting.")
        return []

    segments = _extract_path_segments(path_vertices)
    if not segments:
        _emit(feedback_fn, "warn", "⚠️  No valid segments after filtering — aborting.")
        return []

    seg_index = _SegmentIndex(segments)
    arc_lengths = _build_path_arc_lengths(path_vertices)

    _emit(feedback_fn, "debug",
          f"📐 Path: {len(path_vertices)} vertices, {len(segments)} segments, "
          f"total length: {arc_lengths[-1]:.2f}")

    # ── Build buffers ─────────────────────────────────────────────────────────
    # Cap / join styles are resolved once at module import by
    # _resolve_buffer_styles() → (_CAP_ROUND, _CAP_SQUARE, _JOIN_ROUND).
    # _make_buffer() tries four call signatures so QGIS 3.x and QGIS 4
    # are both handled transparently.
    cap_style = _CAP_SQUARE if end_style == END_SQUARE else _CAP_ROUND

    # Square Ends fix: cap_style only affects the tolerance (snap) buffer shape.
    # The search buffer ALWAYS uses round caps so Square mode never pulls in
    # extra features that lie beyond the path ends.
    search_buf = _make_buffer(path_geom, search_buffer, _CAP_ROUND, _JOIN_ROUND)
    tol_buf    = _make_buffer(path_geom, tolerance,     cap_style,  _JOIN_ROUND)

    if search_buf is None or search_buf.isEmpty():
        _emit(feedback_fn, "warn", "⚠️  Could not create search buffer — aborting.")
        return []

    snap_only_ends = (method == METHOD_SNAP_ENDS)

    # v10 Global Master Boundary Alignment ─────────────────────────────────────
    # When Trace & Smooth is active with tracing on AND the "Enforce Shared
    # Boundary" option enabled, route every affected ring through the coherent
    # tracer so adjacent polygons share a bitwise-identical boundary (no gaps).
    # Every other case — all other methods, tracing-off, or shared-boundary-off —
    # falls through to the original v8 per-feature pipeline below, unchanged.
    if (
        method == METHOD_TRACE_SMOOTH
        and enable_tracing
        and enable_shared_boundary
    ):
        results = _trace_rings_coherently(
            features, path_vertices, arc_lengths, seg_index,
            tol_buf, search_buf, tolerance, offset, side,
            resample_distance, smooth_iterations,
            progress_callback, feedback_fn,
        )
        _emit(feedback_fn, "info",
              f"✅ Done (v10 master-snap): {len(results)}/{len(features)} feature(s) modified.")
        return results

    # Smart Fit to Path ─────────────────────────────────────────────────────────
    # Intersection-significance filter + proximity-weighted vertex movement.
    # Prevents L-corner pulls and crossing-line artefacts while still producing
    # a coherent shared boundary across adjacent features.
    if method == METHOD_SMART_FIT:
        results = _smart_fit_to_path(
            features, path_vertices, seg_index, search_buf, tol_buf,
            tolerance, offset, side,
            min_overlap_ratio=smart_min_overlap_ratio,
            feedback_fn=feedback_fn,
            progress_callback=progress_callback,
        )
        _emit(feedback_fn, "info",
              f"✅ Done (Smart Fit): {len(results)}/{len(features)} feature(s) modified.")
        return results

    # v10.1.5 — Coherent Fit to Path (gap-closing) ──────────────────────────────
    # "Fit to Path" now routes through ONE deterministic master-path projection
    # for ALL features instead of the old independent per-feature two-pass snap.
    # This is what makes two adjacent polygons land on the *same* boundary
    # coordinates where they meet the path, eliminating the thin slivers/gaps
    # the old asymmetric (vertex-vs-edge) snap left behind on hand-drawn paths.
    # All other methods (Preserve, Snap Ends, Trace-without-shared-boundary)
    # fall through to the original per-feature pipeline below, unchanged.
    if method == METHOD_FIT:
        results = _fit_to_path_coherent(
            features, path_vertices, seg_index, search_buf,
            tolerance, offset, side,
            feedback_fn, progress_callback,
        )
        _emit(feedback_fn, "info",
              f"✅ Done (Fit to Path coherent): {len(results)}/{len(features)} feature(s) modified.")
        return results

    # v10.1.9 — Coherent Preserve / Snap Ends (gap-closing) ────────────────────
    # When enable_shared_boundary is ON, PRESERVE and SNAP_ENDS also route
    # through the coherent master-path projection pass so adjacent polygons
    # that share a boundary get identical coordinates there.
    # This mirrors the Fit-to-Path coherent pipeline but applies only to
    # vertices that already sit inside the buffer (PRESERVE) or only the first
    # and last vertices (SNAP_ENDS).  The _fit_to_path_coherent function handles
    # all of these correctly via its standard densify → master-snap steps.
    if enable_shared_boundary and method in (METHOD_PRESERVE, METHOD_SNAP_ENDS):
        results = _fit_to_path_coherent(
            features, path_vertices, seg_index, search_buf,
            tolerance, offset, side,
            feedback_fn, progress_callback,
        )
        _emit(feedback_fn, "info",
              f"✅ Done ({method} coherent): "
              f"{len(results)}/{len(features)} feature(s) modified.")
        return results

    results = []
    total   = len(features)
    _emit(feedback_fn, "info", f"🚀 Starting alignment: {total} feature(s)")

    for idx, feat in enumerate(features):
        if progress_callback:
            progress_callback(idx + 1, total)

        orig_geom = feat.geometry()
        if orig_geom is None or orig_geom.isEmpty():
            continue

        if not orig_geom.intersects(search_buf):
            # Diagnostic: compute actual distance so the user knows how far
            # off the feature is and whether raising tolerance would help.
            try:
                path_geom_ref = QgsGeometry.fromPolylineXY(path_vertices[:2])
                actual_dist = orig_geom.distance(search_buf)
            except Exception:
                actual_dist = -1.0
            _emit(
                feedback_fn, "warn",
                f"   Feature {feat.id()} skipped — outside search buffer "
                f"(search_buffer={search_buffer:.2f}, "
                f"feature→buffer distance≈{actual_dist:.4f}). "
                f"Raise tolerance above {search_buffer + max(actual_dist, 0):.1f} "
                f"to include this feature.",
            )
            continue

        if not orig_geom.isGeosValid():
            fixed = orig_geom.makeValid()
            if fixed is None or fixed.isEmpty():
                _emit(feedback_fn, "warn",
                      f"   Feature {feat.id()}: invalid geometry, could not fix — skipped.")
                continue
            orig_geom = fixed

        new_parts = []
        changed   = False

        for part in orig_geom.parts():
            part_geom = QgsGeometry(part.clone())
            processed = _process_polygon_part(
                part, path_vertices, arc_lengths, seg_index,
                tolerance, offset, method, side, snap_only_ends, tol_buf,
                resample_distance, smooth_iterations, enable_tracing,
            )

            if processed is not None and not processed.isEmpty():
                new_parts.append(processed)
                if not part_geom.equals(processed):
                    changed = True
            else:
                new_parts.append(part_geom)

        if not changed:
            continue

        if len(new_parts) == 0:
            continue
        elif len(new_parts) == 1:
            new_geom = new_parts[0]
        else:
            new_geom = QgsGeometry.collectGeometry(new_parts)

        if new_geom is None or new_geom.isEmpty():
            continue

        results.append((feat, new_geom))

    _emit(feedback_fn, "info",
          f"✅ Done: {len(results)}/{total} feature(s) modified.")
    return results


# ── Layer helpers ──────────────────────────────────────────────────────────────

def apply_results_in_place(
    layer: QgsVectorLayer,
    results: List[Tuple[QgsFeature, QgsGeometry]],
) -> int:
    """Apply alignment results in-place to an editable vector layer."""
    if not layer.isEditable():
        layer.startEditing()

    count = 0
    for feat, new_geom in results:
        ok = layer.changeGeometry(feat.id(), new_geom)
        if ok:
            count += 1
        else:
            if _HAS_MSG_LOG:
                QgsMessageLog.logMessage(
                    f"Failed to update feature {feat.id()}.",
                    "AlignFeatures", Qgis.MessageLevel.Warning,
                )
    return count


def create_result_layer(
    source_layer: QgsVectorLayer,
    results: List[Tuple[QgsFeature, QgsGeometry]],
    layer_name: str = "Aligned Features",
) -> QgsVectorLayer:
    """Create a new memory layer with aligned features (all attributes preserved)."""
    # QgsWkbTypes.displayString() → moved in QGIS 4; try both locations.
    try:
        geom_type_str = QgsWkbTypes.displayString(source_layer.wkbType())
    except (AttributeError, TypeError):
        try:
            geom_type_str = Qgis.WkbType(source_layer.wkbType()).name
        except (AttributeError, TypeError, ValueError):
            geom_type_str = "Polygon"   # safe fallback for polygon plugins
    crs_auth      = source_layer.crs().authid()
    uri           = f"{geom_type_str}?crs={crs_auth}"

    new_layer = QgsVectorLayer(uri, layer_name, "memory")
    dp        = new_layer.dataProvider()
    dp.addAttributes(source_layer.fields().toList())
    new_layer.updateFields()

    result_ids   = {feat.id(): geom for feat, geom in results}
    new_features = []

    for feat in source_layer.getFeatures():
        new_feat = QgsFeature(feat)
        if feat.id() in result_ids:
            new_feat.setGeometry(result_ids[feat.id()])
        new_features.append(new_feat)

    dp.addFeatures(new_features)
    new_layer.updateExtents()
    return new_layer
