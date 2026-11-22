"""Experimental Python-only isogrid direct offset-boundary clipper.

Construct the *full* inset region exactly once via PreparedCurves on a bounding
rectangle. Then clip individual triangles using only 3 straight edges versus
already prepared shared boundary segments. No per-triangle region arrangement.
Fusion export is unchanged. The source curve intervals are preserved.
"""
import math
from dataclasses import dataclass
import geometry as g
import curves2d as c
import exact_clipper as exact

@dataclass(frozen=True)
class Hit:
    line_t: float
    curve_t: float
    point: tuple


def _tri_contains(p,poly):
    return g._point_in_ccw_triangle(p,poly)

class Boundary:
    def __init__(self, regions, perimeter, void_clearance, flatten_tolerance=0.00025):
        self.prep=g.PreparedGeometry(regions,perimeter,void_clearance)
        if self.prep.exact is None:
            raise ValueError('Native curved boundary required for benchmark')
        bb=g.expand_box(g.face_bounds(regions),max(perimeter,void_clearance,1.))
        box=[(bb[0],bb[1]),(bb[2],bb[1]),(bb[2],bb[3]),(bb[0],bb[3])]
        self.loops=self.prep.exact.clip(box)
        expected_voids=sum(not outer for region in regions for _,outer in region.loops)
        recognised_voids=sum(c.loop_area(loop)<0 for loop in self.loops)
        if recognised_voids<expected_voids:
            # Some complex source curve families are not reliably represented
            # by a single enclosing-rectangle Boolean. Stay on the original
            # exact clipper instead of silently losing protected islands.
            raise ValueError('Global prepared boundary lost a protected void')
        self.polys=[c.sample(l,flatten_tolerance) for l in self.loops]
        self.edges=[]
        for loop_idx,loop in enumerate(self.loops):
            for seg in loop:
                bb=c.bounds(seg)
                # Narrow the bbox of trimmed curves from their sampled path.
                if not isinstance(seg,(c.Line,c.Arc)):
                    path=c._flatten(seg,flatten_tolerance,15)
                    bb=g.expand_box(g.bounds([p for _,p in path]),flatten_tolerance)
                else:
                    path=None
                self.edges.append((loop_idx,seg,bb,path))
        self._outer=[(poly,positive) for poly,positive in zip(self.polys,
            [c.loop_area(loop)>0 for loop in self.loops])]
        self.count_intersections=0
        self.rounded_accepted=0
        self.rounded_rejected=0
        self._poly_indices=[g._LoopYIndex(poly) if len(poly)>=24 else None
                            for poly in self.polys]
        chords=[]
        for poly in self.polys:
            for a,b in zip(poly,poly[1:]+poly[:1]):
                if c.length(c.sub(a,b))>1e-9:
                    chords.append((g.bounds([a,b]),a,b))
        self._chord_index=g._BoxIndex(chords,g.face_bounds(regions))
    def inside(self,p):
        return (any(g.in_poly(p,poly,False) for poly,pos in self._outer if pos)
                and not any(g.in_poly(p,poly,False) for poly,pos in self._outer if not pos))

    def accepted_rounded(self, triangle, radius):
        """Return a whole pre-rounded triangle if the finished contour fits.

        Many raw triangles touch the source margin only at their sharp tips.
        The final rounded triangle may fit wholly within the permitted mask;
        no clipped corner geometry is needed for these cells. Test once using
        sampled broad-phase chords; output remains native lines/circular arcs.
        """
        curved=g.fillet_curve_loop(triangle,radius)
        poly=c.sample(curved,.0002)
        if not poly or not self.inside(poly[0]):
            self.rounded_rejected+=1
            return None
        # A protected island completely inside the rounded contour produces
        # no boundary crossing, but still means the full pocket is invalid.
        for outline,positive in self._outer:
            if not positive and g.in_poly(outline[0],poly,False):
                self.rounded_rejected+=1
                return None
        for a,b in zip(poly,poly[1:]+poly[:1]):
            bb=g.expand_box(g.bounds([a,b]),.0006)
            for _,u,v in self._chord_index.query(bb):
                if g.intersections(a,b,u,v):
                    self.rounded_rejected+=1
                    return None
        self.rounded_accepted+=1
        return curved

    def intersections(self,line,seg,flat=None):
        if flat is None:
            points=c.intersections(line,seg)
            res=[]
            for p in points:
                tl=c.parameter(line,p,tol=2e-6)
                ts=c.parameter(seg,p,tol=2e-6)
                if tl is not None and ts is not None:res.append(Hit(tl,ts,p))
            return res
        v=c.sub(line.end,line.start)
        scale=c.length(v)
        v2=c.dot(v,v)
        linebox=c.bounds(line)
        res=[]
        for (a,p),(b,q) in zip(flat,flat[1:]):
            if not g.boxes_overlap(linebox,g.bounds([p,q]),1e-4):continue
            y0=c.cross(v,c.sub(p,line.start))/scale
            y1=c.cross(v,c.sub(q,line.start))/scale
            if y0*y1>0 and min(abs(y0),abs(y1))>1e-5:continue
            if y0*y1>0:
                t=a if abs(y0)<abs(y1) else b
            else:
                low=a;high=b;sign=y0
                for _ in range(27):
                    t=(low+high)*0.5
                    v0=c.cross(v,c.sub(seg.point(t),line.start))/scale
                    if abs(v0)<2e-9:break
                    if sign*v0>0:low=t;sign=v0
                    else:high=t
            pt=seg.point(t)
            tl=c.dot(c.sub(pt,line.start),v)/v2
            err=abs(c.cross(v,c.sub(pt,line.start)))/scale
            if -2e-7<=tl<=1+2e-7 and err<2e-6 and all(c.length(c.sub(pt,h.point))>1e-5 for h in res):
                res.append(Hit(max(0.,min(1.,tl)),t,pt))
        return res

    def clip(self, triangle):
        if g.area(triangle)<0:triangle=list(reversed(triangle))
        bb=g.bounds(triangle)
        nearby=[(loop_idx,seg,sb,flat) for loop_idx,seg,sb,flat in self.edges
                if g.boxes_overlap(bb,sb,1e-6)]
        if not nearby:
            return [[c.Line(p,q) for p,q in zip(triangle,triangle[1:]+triangle[:1])]] if self.inside(g.polygon_centroid(triangle)) else []
        lines=[c.Line(p,q) for p,q in zip(triangle,triangle[1:]+triangle[:1])]
        line_hits=[[] for _ in lines]
        curve_hits=[[] for _ in nearby]
        for i,line in enumerate(lines):
            for j,(_,seg,sb,flat) in enumerate(nearby):
                if not g.boxes_overlap(c.bounds(line),sb,1e-6):continue
                hits=self.intersections(line,seg,flat)
                line_hits[i].extend(hits)
                curve_hits[j].extend(hits)
                self.count_intersections+=len(hits)
        directed=[]
        for i,line in enumerate(lines):
            cuts=sorted([0.,1.]+[hit.line_t for hit in line_hits[i]])
            unique=[cuts[0]]
            for t in cuts[1:]:
                if t-unique[-1]>1e-8:unique.append(t)
            for a,b in zip(unique,unique[1:]):
                if b-a<1e-8:continue
                piece=line.section(a,b)
                if self.inside(piece.point(.5)):directed.append(piece)
        # Only 3 x shared boundary intersections; every retained boundary
        # segment is already oriented with permitted pocket on its left.
        for j,(_,seg,bb,flat) in enumerate(nearby):
            cuts=sorted([0.,1.]+[h.curve_t for h in curve_hits[j]])
            unique=[cuts[0]]
            for t in cuts[1:]:
                if t-unique[-1]>1e-8:unique.append(t)
            for a,b in zip(unique,unique[1:]):
                if b-a<1e-8:continue
                piece=seg.section(a,b)
                if _tri_contains(piece.point(.5),triangle):directed.append(piece)
        if not directed:return []
        return exact._assemble(directed)

class PreparedDirect(g.PreparedGeometry):
    def __init__(self, regions,perimeter,void_clearance,corner_radius):
        self.corner_radius=corner_radius
        self.used=0
        self.fallback=0
        try:
            self.direct=Boundary(regions,perimeter,void_clearance)
            self.region=self.direct.prep
        except ValueError:
            self.direct=None
            self.region=g.PreparedGeometry(regions,perimeter,void_clearance)
        self.exact=self.region.exact
    def clip(self,pocket):
        self.used+=1
        if self.direct is None:
            self.fallback+=1
            return self.region.clip(pocket)
        return self.direct.clip(pocket)
    def clip_many(self,pockets,check_cancel=None):
        out=[]
        for p in pockets:
            if check_cancel:check_cancel()
            rounded=(self.direct.accepted_rounded(p,self.corner_radius)
                     if self.direct is not None and self.corner_radius>0 else None)
            out.append([rounded] if rounded is not None else self.clip(p))
        return out
    def circle_fits(self,center,radius):
        return self.region.circle_fits(center,radius)
