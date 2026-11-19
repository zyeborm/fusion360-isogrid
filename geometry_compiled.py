"""Optional GEOS/Shapely implementation of the same 2-D pocket intersections.

The geometry.py public interface and CutShape output remain authoritative.  In
particular, Auto Fit and the final Fusion sketch call the *same* make_pockets.

This module is deliberately separate so a Fusion installation without Shapely
can still load the add-in and use the pure-Python fallback.
"""
from __future__ import annotations

from shapely.geometry import Polygon, LineString, Point
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from shapely.prepared import prep
import numpy as np
import shapely


def _poly(seq):
    p = Polygon(seq)
    if not p.is_valid:
        # A zero-width cusp is valid as a boundary of the *buffered* area,
        # but an explicitly self-intersecting source loop needs repair.
        p = p.buffer(0)
    return p


def _region(region):
    outer = [_poly(poly) for poly, is_outer in region.loops if is_outer]
    holes = [_poly(poly) for poly, is_outer in region.loops if not is_outer]
    shape = unary_union(outer)
    if holes:
        shape = shape.difference(unary_union(holes))
    return shape


def _extract_loops(geom):
    """Return CCW exterior / CW holes for a final sketch CutShape."""
    if geom.is_empty:
        return []
    if geom.geom_type == 'Polygon':
        polygons = [geom]
    elif geom.geom_type in ('MultiPolygon', 'GeometryCollection'):
        polygons = [g for g in geom.geoms if g.geom_type == 'Polygon']
    else:
        return []
    loops = []
    for polygon in polygons:
        if polygon.area < 1e-9:
            continue
        p = orient(polygon, sign=1)
        loops.append([(float(x), float(y)) for x,y in list(p.exterior.coords)[:-1]])
        loops.extend([[(float(x),float(y)) for x,y in list(ring.coords)[:-1]]
                      for ring in p.interiors])
    return loops


class PreparedArea:
    """Prepare all source boundaries/margins once for many lattice phases.

    GEOS performs boundary buffering and union only once.  A prepared geometry
    provides indexed intersects/covers checks; only partially covered pockets
    require the slower polygon intersection operation.
    """
    backend = 'Shapely/GEOS'

    def __init__(self, regions, perimeter, void_clearance):
        mask = None
        for region in regions:
            shape = _region(region)
            bands = []
            for loop, outer in region.loops:
                radius = perimeter if outer else void_clearance
                if radius > 1e-9:
                    # Closed loop stroke == the union of circular distance
                    # bands around its edges. Round joins handle zero-angle
                    # cusps, disappearing necks, and overlapping boundaries.
                    band = LineString(loop + [loop[0]]).buffer(
                        radius, quad_segs=8, cap_style='round',
                        join_style='round')
                    bands.append(band)
            if bands:
                shape = shape.difference(unary_union(bands))
            mask = shape if mask is None else mask.intersection(shape)
        self.allowed = mask
        self.prepared = prep(mask)
        self._circle_masks = {}

    def clip(self, pocket):
        candidate = Polygon(pocket)
        if self.prepared.covers(candidate):
            return [pocket]
        if not self.prepared.intersects(candidate):
            return []
        return _extract_loops(self.allowed.intersection(candidate))

    def clip_many(self, pockets):
        """Batch GEOS predicates/intersections for all cells of one layout.

        The C-backed vector API avoids thousands of Python -> GEOS crossings,
        while retaining the same containment and intersection semantics as
        clip(). Full cells retain their original Python list object so the
        shared make_pockets function can use a pre-rounded template.
        """
        if not pockets:
            return []
        candidate=np.array([Polygon(poly) for poly in pockets], dtype=object)
        covered=shapely.covers(self.allowed,candidate)
        hits=shapely.intersects(self.allowed,candidate)
        partial=np.flatnonzero(hits & ~covered)
        intersections=shapely.intersection(candidate[partial],self.allowed)
        outputs=[[] for _ in pockets]
        for i,inside in enumerate(covered):
            if inside:outputs[i]=[pockets[i]]
        for index,polygon in zip(partial,intersections):
            outputs[int(index)]=_extract_loops(polygon)
        return outputs

    def circle_fits(self, center, radius):
        # The erosion is computed once per requested hole diameter, not once
        # per grid junction. Checking against the actual allowed pocket region
        # respects *all* face and sketch exclusions, including their margins.
        key = round(radius, 10)
        prepared = self._circle_masks.get(key)
        if prepared is None:
            reduced = self.allowed.buffer(-radius - 2e-6, quad_segs=8)
            prepared = prep(reduced)
            self._circle_masks[key] = prepared
        return prepared.covers(Point(center))