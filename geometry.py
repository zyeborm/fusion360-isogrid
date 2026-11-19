"""Dependency-free planar isogrid geometry (all distances in Fusion database cm).

Regions contain oriented contours: exterior loops CCW, void loops CW.
For a given triangular pocket, an oriented segment arrangement computes its
intersection with one or more regions. This permits both face and sketch masks.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
import curves2d as _curves
import exact_clipper as _exact

# GEOS/Shapely support is deliberately disabled for now. An incompatible native
# wheel can terminate Fusion outright during import. Keep this integration for
# reconsideration later, but never load the compiled modules in this release.
# import os
# import sys
# _vendor = os.path.join(os.path.dirname(__file__), 'vendor')
# if os.path.isdir(_vendor) and _vendor not in sys.path:
#     sys.path.insert(0, _vendor)
# try:
#     from geometry_compiled import PreparedArea as _CompiledArea
# except (ImportError, OSError):
#     _CompiledArea = None
_CompiledArea = None


def geometry_backend(backend="auto"):
    if backend == "python":
        return "Python (prepared)"
    if backend == "geos" and _CompiledArea is None:
        return "GEOS (unavailable)"
    return "GEOS (accelerated)" if _CompiledArea is not None else "Python (prepared)"

EPS = 1e-8
SQRT3 = math.sqrt(3.0)


def maximum_vertex_hole_diameter(rib_width, corner_radius):
    """Nominal hole clearance between equilateral rounded pocket corners.

    The inset triangular pocket vertex lies `rib_width` from its original
    lattice junction (two edges each offset by rib_width/2). A 60-degree
    internal fillet moves the nearest point of the pocket boundary away from
    that junction by an additional `corner_radius`. Thus the largest circle
    centred on an interior junction, tangent to six pockets, has diameter
    2 * (rib_width + corner_radius). This assumes a feasible full-cell fillet;
    margins and local trimming can only remove pocket material.
    """
    return 2.0 * (rib_width + max(0.0, corner_radius))


def sub(a, b): return (a[0] - b[0], a[1] - b[1])
def add(a, b): return (a[0] + b[0], a[1] + b[1])
def mul(a, s): return (a[0] * s, a[1] * s)
def cross(a, b): return a[0]*b[1] - a[1]*b[0]
def dot(a, b): return a[0]*b[0] + a[1]*b[1]
def norm(a): return math.hypot(*a)
def area(poly): return 0.5 * sum(cross(p, q) for p, q in zip(poly, poly[1:] + poly[:1]))


def polygon_centroid(poly):
    """Signed-area polygon centroid (same winding convention as area())."""
    twice_area = 0.0
    mx = my = 0.0
    for a,b in zip(poly,poly[1:]+poly[:1]):
        c = cross(a,b)
        twice_area += c
        mx += (a[0]+b[0])*c
        my += (a[1]+b[1])*c
    if abs(twice_area)<EPS:
        return (sum(p[0] for p in poly)/len(poly),
                sum(p[1] for p in poly)/len(poly))
    return (mx/(3*twice_area),my/(3*twice_area))


def clean(poly, eps=EPS):
    out = []
    for p in poly:
        p = (float(p[0]), float(p[1]))
        if not out or norm(sub(p, out[-1])) > eps:
            out.append(p)
    if len(out) > 1 and norm(sub(out[0], out[-1])) <= eps:
        out.pop()
    return out


def bounds(poly):
    return (min(p[0] for p in poly), min(p[1] for p in poly),
            max(p[0] for p in poly), max(p[1] for p in poly))


def boxes_overlap(a, b, margin=0):
    return not (a[2] < b[0]-margin or b[2] < a[0]-margin or
                a[3] < b[1]-margin or b[3] < a[1]-margin)


def expand_box(box, margin):
    return (box[0]-margin, box[1]-margin,
            box[2]+margin, box[3]+margin)


def on_segment(p, a, b, tol=1e-7):
    v = sub(b, a)
    if norm(v) < EPS: return norm(sub(p,a)) < tol
    return abs(cross(v, sub(p,a))) / norm(v) <= tol and -tol <= dot(sub(p,a),v)/dot(v,v) <= 1+tol


def in_poly(p, poly, boundary=True):
    """Ray-crossing predicate with cheap AABB rejection for edge tolerance.

    Most calls test points far from a polygon edge. The legacy code computed
    a square root and projected onto *every* segment just to rule out an
    on-edge result; bounding checks remove nearly all of that work.
    """
    px,py=p
    inside=False
    n=len(poly)
    for i in range(n):
        ax,ay=poly[i];bx,by=poly[(i+1)%n]
        if (ay>py)!=(by>py):
            x=ax+(py-ay)*(bx-ax)/(by-ay)
            if x>px:inside=not inside
        tol=1e-7
        dx=bx-ax;dy=by-ay
        if (min(ax,bx)-tol <= px <= max(ax,bx)+tol and
            min(ay,by)-tol <= py <= max(ay,by)+tol):
            length=math.hypot(dx,dy)
            if length<EPS:
                if math.hypot(px-ax,py-ay)<tol:return boundary
            elif abs(dx*(py-ay)-dy*(px-ax))<=tol*length:
                t=((px-ax)*dx+(py-ay)*dy)/(length*length)
                if -tol<=t<=1+tol:return boundary
    return inside


class _LoopYIndex:
    """Cache edges by scanline so containment avoids full polygon walks."""
    def __init__(self, poly):
        self.edges=[(a[0],a[1],b[0],b[1]) for a,b in _segments(poly)]
        self.lo=min(p[1] for p in poly)
        hi=max(p[1] for p in poly)
        self.hi=hi
        self.n=min(96,max(8,len(poly)//3))
        self.step=max((hi-self.lo)/self.n,1e-8)
        self.bins=[[] for _ in range(self.n)]
        for i,(_,ay,_,by) in enumerate(self.edges):
            first=max(0,min(self.n-1,int(math.floor((min(ay,by)-self.lo)/self.step))))
            last=max(0,min(self.n-1,int(math.floor((max(ay,by)-self.lo)/self.step))))
            for j in range(first,last+1):self.bins[j].append(i)

    def contains(self,p,boundary=True):
        px,py=p
        i=int(math.floor((py-self.lo)/self.step))
        if i==self.n and py<=self.hi+1e-7:i=self.n-1
        if i<0 or i>=self.n:return False
        inside=False;tol=1e-7
        for edge in self.bins[i]:
            ax,ay,bx,by=self.edges[edge]
            if (ay>py)!=(by>py):
                if ax+(py-ay)*(bx-ax)/(by-ay)>px:inside=not inside
            dx=bx-ax;dy=by-ay
            if (min(ax,bx)-tol<=px<=max(ax,bx)+tol and
                min(ay,by)-tol<=py<=max(ay,by)+tol):
                length=math.hypot(dx,dy)
                if length<EPS:
                    if math.hypot(px-ax,py-ay)<tol:return boundary
                elif abs(dx*(py-ay)-dy*(px-ax))<=tol*length:
                    t=((px-ax)*dx+(py-ay)*dy)/(length*length)
                    if -tol<=t<=1+tol:return boundary
        return inside


@dataclass
class Region:
    # One or several face boundary loops; each boolean represents outer boundary.
    loops: list[tuple[list[tuple[float, float]], bool]]
    # Optional exact source geometry, one loop per polygon above.  Fusion
    # supplies line and arc segments; the polygon is only for broad-phase
    # bounds, sketch profile picking and legacy tests.
    curve_loops: list | None = None

    def __post_init__(self):
        canonical = []
        retained_curves=[]
        for i,(poly, outer) in enumerate(self.loops):
            poly = clean(poly)
            if len(poly) < 3 or abs(area(poly)) < EPS: continue
            flipped=(area(poly)>0)!=outer
            if flipped: poly.reverse()
            if self.curve_loops is not None:
                curves=self.curve_loops[i]
                if flipped:curves=_curves.reverse_loop(curves)
                retained_curves.append(curves)
            canonical.append((poly, outer))
        if not any(o for _, o in canonical):
            raise ValueError('The region has no exterior boundary.')
        self.loops = canonical
        if self.curve_loops is not None:self.curve_loops=retained_curves
        self._exact_region=None
        self.boxes = [bounds(p) for p, _ in canonical]
        self._point_indices = [_LoopYIndex(p) if len(p)>=24 else None
                               for p,_ in canonical]

    def contains(self, p, boundary=True):
        if self.curve_loops is not None:
            if self._exact_region is None:
                self._exact_region = _exact.CurveRegion([
                    (list(path), outer) for path, (_, outer)
                    in zip(self.curve_loops, self.loops)])
            return self._exact_region.contains(p)
        ptbox=(p[0],p[1],p[0],p[1])
        def inside(i,edge_boundary):
            poly,_=self.loops[i]
            index=self._point_indices[i]
            return (index.contains(p,edge_boundary) if index else
                    in_poly(p,poly,edge_boundary))
        if not any(outer and boxes_overlap(box,ptbox) and inside(i,boundary)
                   for i,((_,outer),box) in enumerate(zip(self.loops,self.boxes))):
            return False
        return not any(not outer and boxes_overlap(box,ptbox) and inside(i,not boundary)
                       for i,((_,outer),box) in enumerate(zip(self.loops,self.boxes)))

    def inset(self, perimeter, void_clearance):
        """Shift each loop toward its valid side; reject degenerate offsets.

        Miter offsets are appropriate for polygonal outlines and sampled curves.
        Very large offsets and self-intersections fail closed.
        """
        loops = []
        for (poly,outer) in self.loops:
            d = perimeter if outer else void_clearance
            result = offset_valid_side(poly,d)
            if len(result) < 3:
                raise ValueError('A margin collapsed a boundary.')
            if area(result)*area(poly) <= 0 or self_intersects(result):
                raise ValueError('Margin is too large for this boundary; reduce it.')
            loops.append((result,outer))
        return Region(loops)


@dataclass
class CutShape:
    """One finished cut island. Circle metadata permits native Fusion circles."""
    outline: list[tuple[float,float]]
    loops: list[list[tuple[float,float]]]
    circle: tuple | None = None  # (center_xy, radius), if completely untrimmed
    fillet_warnings: int = 0  # Convex corners where the requested radius cannot fit
    # Exact sketch geometry.  Polygons above are tessellated derivatives used
    # for clipping, preview and candidate scoring, never to reconstruct arcs.
    curve_loops: list | None = None


# Shared canonical line/arc primitives.  Native sketch arcs and exact clipping
# use these same objects; tessellated display polygons are derived from them.
Line2D = _curves.Line
Arc2D = _curves.Arc


def polyline_curves(poly):
    """An unfilleted polygon, retained as exact straight sketch segments."""
    return [Line2D(a, b) for a, b in _segments(poly)
            if norm(sub(a, b)) > EPS]


def sample_curve_loop(curves, segments_per_corner=3):
    """Sample canonical arcs *only* for polygon operations and display."""
    points = []
    for segment in curves:
        if isinstance(segment, Line2D):
            points.append(segment.start)
            continue
        radius=norm(sub(segment.start,segment.center))
        steps=max(2, math.ceil(segments_per_corner*abs(segment.sweep)/(math.pi/3)))
        alpha=math.atan2(segment.start[1]-segment.center[1],
                         segment.start[0]-segment.center[0])
        for i in range(steps):
            angle=alpha+segment.sweep*i/steps
            points.append((segment.center[0]+radius*math.cos(angle),
                           segment.center[1]+radius*math.sin(angle)))
    return clean(points)


def transform_curve_loop(curves, cos_angle, sin_angle, translation):
    def moved(p):
        return (translation[0]+cos_angle*p[0]-sin_angle*p[1],
                translation[1]+sin_angle*p[0]+cos_angle*p[1])
    return ([Line2D(moved(s.start), moved(s.end)) if isinstance(s, Line2D)
             else Arc2D(moved(s.center), moved(s.start), moved(s.end),s.sweep)
             for s in curves])


def offset_valid_side(poly, distance):
    if distance < 0: raise ValueError('Margins must be non-negative.')
    if distance < EPS: return list(poly)
    out=[]
    count = len(poly)
    for i in range(count):
        prev, p, nxt = poly[i-1], poly[i], poly[(i+1)%count]
        u = sub(p,prev); v = sub(nxt,p)
        l1,l2=norm(u),norm(v)
        if min(l1,l2) <= EPS: raise ValueError('Degenerate contour.')
        u,v=mul(u,1/l1),mul(v,1/l2)
        nu, nv = (-u[1],u[0]),(-v[1],v[0])
        a=add(p,mul(nu,distance)); b=add(p,mul(nv,distance))
        den=cross(u,v)
        if abs(den)<1e-9:
            if dot(u,v) < 0: raise ValueError('Contour contains a reversal.')
            out.append(add(p,mul(add(nu,nv),distance/2)))
            continue
        t=cross(sub(b,a),v)/den
        q=add(a,mul(u,t))
        if norm(sub(q,p)) > 10*distance + 1e-7:
            raise ValueError('Contour has a near-cusp; margin cannot be mitred reliably.')
        out.append(q)
    return clean(out)


def self_intersects(poly):
    n=len(poly)
    for i in range(n):
        a,b=poly[i],poly[(i+1)%n]
        for j in range(i+2,n):
            if i==0 and j==n-1: continue
            c,d=poly[j],poly[(j+1)%n]
            for t,u in intersections(a,b,c,d):
                if EPS < t < 1-EPS and EPS < u < 1-EPS:
                    return True
    return False


def intersections(a,b,c,d):
    """Return segment intersections as (fraction on ab, fraction on cd).

    For collinear overlap, split at the endpoints of the overlap too.
    """
    r=sub(b,a); s=sub(d,c); den=cross(r,s); ca=sub(c,a)
    if abs(den)>EPS*max(norm(r)*norm(s),EPS):
        t=cross(ca,s)/den; u=cross(ca,r)/den
        if -EPS <= t <= 1+EPS and -EPS <= u <= 1+EPS:
            return [(min(1,max(0,t)),min(1,max(0,u)))]
        return []
    if abs(cross(ca,r))>EPS*max(norm(r),1): return []
    rr=dot(r,r); ss=dot(s,s)
    if rr<EPS*EPS or ss<EPS*EPS: return []
    ts=[dot(sub(q,a),r)/rr for q in (c,d)]
    lo,hi=max(0,min(ts)),min(1,max(ts))
    if lo>hi+EPS: return []
    return [(t,dot(sub(add(a,mul(r,t)),c),s)/ss) for t in (lo,hi)]


def _split_all(segments, targets):
    """Return subsegments split wherever they cross target segments."""
    out=[]
    for a,b in segments:
        box=bounds([a,b]); params=[0.0,1.0]
        for c,d in targets:
            if boxes_overlap(box,bounds([c,d])):
                params.extend(t for t,_ in intersections(a,b,c,d))
        params=sorted(set(round(t,11) for t in params))
        for t,u in zip(params,params[1:]):
            if u-t>1e-9:
                p=add(a,mul(sub(b,a),t));q=add(a,mul(sub(b,a),u))
                if norm(sub(q,p))>1e-7: out.append((p,q))
    return out


def _segments(poly):
    return list(zip(poly,poly[1:]+poly[:1]))


def _key(p):
    return (round(p[0],6),round(p[1],6)) # 0.01 um in Fusion cm units.


def _clip_pocket_unbuffered(pocket, regions):
    """Intersect one CCW pocket with an arbitrary number of mask regions.

    Returns closed, oriented contours. May include CW void boundaries; the
    Fusion adapter must classify sketch profiles rather than extrude every loop.
    """
    pocket=clean(pocket)
    if area(pocket)<0: pocket.reverse()
    pb=bounds(pocket)
    sources=[('pocket',0,pocket)]
    for ri,region in enumerate(regions):
        for loop, _ in region.loops:
            if boxes_overlap(pb,bounds(loop)):
                sources.append(('mask',ri,loop))
    all_segments=[]
    for kind,ri,poly in sources:
        all_segments.extend((kind,ri,a,b) for a,b in _segments(poly))
    edges=[]
    for kind,ri,poly in sources:
        segs=_segments(poly)
        other=[(a,b) for k,r,a,b in all_segments if k!=kind or (kind=='mask' and r!=ri)]
        # Same-region boundary crossings should never occur for valid contours.
        for a,b in _split_all(segs,other):
            mid=mul(add(a,b),0.5)
            if kind=='pocket':
                valid=all(r.contains(mid,True) for r in regions)
            else:
                valid=in_poly(mid,pocket,False) and all(
                    other_region.contains(mid,True)
                    for idx,other_region in enumerate(regions) if idx!=ri)
            if valid: edges.append((a,b))
    # Same-direction duplicates arise for coincident mask and pocket edges.
    unique={}
    for a,b in edges:
        ka,kb=_key(a),_key(b)
        if ka!=kb: unique[(ka,kb)]=(a,b)
    edges=list(unique.values())
    starts={}
    for idx,(a,b) in enumerate(edges): starts.setdefault(_key(a),[]).append(idx)
    loops=[]; used=set()
    for start in range(len(edges)):
        if start in used: continue
        loop=[]; idx=start; first=_key(edges[idx][0]); guard=0
        while idx is not None and idx not in used:
            used.add(idx);a,b=edges[idx];loop.append(a)
            endpoint=_key(b);guard+=1
            if endpoint==first:
                poly=clean(loop)
                if len(poly)>=3 and abs(area(poly))>1e-9: loops.append(poly)
                break
            candidates=[j for j in starts.get(endpoint,[]) if j not in used]
            if not candidates:
                # Numeric/topology mismatch. Abort rather than produce an open cut.
                raise ValueError('Unclosed intersection at boundary; try a small offset change.')
            if len(candidates)==1: idx=candidates[0]
            else:
                # Keep the material to the left by selecting the most clockwise
                # continuation when several contours touch at one vertex.
                v=sub(b,a)
                idx=min(candidates,key=lambda j:
                    (math.atan2(cross(v,sub(edges[j][1],edges[j][0])),
                                 dot(v,sub(edges[j][1],edges[j][0]))) + 2*math.pi)%(2*math.pi))
            if guard>len(edges)+1: raise ValueError('Intersection graph did not close.')
    return loops


def _capsule(a, b, radius, semicircle_steps=10):
    """Polygonal, slightly conservative distance buffer for a line segment.

    The outward radial correction bounds the actual circular capsule instead
    of inscribing it; the error at a 3 mm margin is under 0.04 mm.
    """
    u=sub(b,a); length=norm(u)
    if length<EPS:return []
    theta=math.atan2(u[1],u[0])
    step=math.pi/semicircle_steps
    r=radius / math.cos(step/2)
    result=[]
    # Arc at the trailing endpoint, then the leading endpoint. CCW winding.
    for i in range(semicircle_steps+1):
        ang=theta-math.pi/2+i*step
        result.append((b[0]+r*math.cos(ang),b[1]+r*math.sin(ang)))
    for i in range(semicircle_steps+1):
        ang=theta+math.pi/2+i*step
        result.append((a[0]+r*math.cos(ang),a[1]+r*math.sin(ang)))
    if area(result)<0:result.reverse()
    return result


def _buffer_edges(regions, exterior_margin, hole_margin):
    """A spatially-filterable collection of boundary distance exclusion bands.

    Representing margins as a UNION of segment capsules handles cusps,
    overlapping edges and the disappearance/splitting of narrow regions.
    In particular, an inward contour mitre is never required.
    """
    result=[]
    for region in regions:
        for poly,outer in region.loops:
            r=exterior_margin if outer else hole_margin
            if r<EPS:continue
            for a,b in _segments(poly):
                if norm(sub(a,b)) > EPS:
                    result.append((expand_box(bounds([a,b]),r*1.02),a,b,r))
    return result


def _clip_with_exclusions(pocket, regions, obstacles):
    """Boolean intersection against masks, minus overlapping buffered edges.

    All segments are split at every crossing. Edges are kept only where the
    target region is on exactly one side, so intersecting exclusion capsules
    are unioned without needing an external polygon-Boolean dependency.
    """
    pocket=clean(pocket)
    if area(pocket)<0:pocket.reverse()
    pb=bounds(pocket)
    sources=[pocket]
    for region in regions:
        for poly,_ in region.loops:
            if boxes_overlap(pb,bounds(poly)):
                sources.append(poly)
    sources += [poly for poly,box in obstacles if boxes_overlap(pb,box)]
    segments=[(a,b) for poly in sources for a,b in _segments(poly)]
    segment_boxes=[bounds([a,b]) for a,b in segments]
    edges=[]
    def allowed(pt):
        if not in_poly(pt,pocket,False):return False
        if not all(r.contains(pt,False) for r in regions):return False
        return not any(boxes_overlap(box,(pt[0],pt[1],pt[0],pt[1])) and
                       in_poly(pt,poly,True) for poly,box in obstacles)
    for i,(a,b) in enumerate(segments):
        segbox=segment_boxes[i]; cuts=[0.0,1.0]
        for j,(c,d) in enumerate(segments):
            if i!=j and boxes_overlap(segbox,segment_boxes[j]):
                cuts.extend(t for t,_ in intersections(a,b,c,d))
        cuts=sorted(set(round(t,11) for t in cuts))
        delta=sub(b,a);length=norm(delta)
        if length<EPS:continue
        # An approximately 0.01 um lateral sample, sufficiently outside
        # the on-edge tolerance but tiny relative to ordinary design units.
        lateral=(-delta[1]*2e-6/length,delta[0]*2e-6/length)
        for t,u in zip(cuts,cuts[1:]):
            if u-t<1e-9:continue
            p=add(a,mul(delta,t));q=add(a,mul(delta,u))
            if norm(sub(p,q))<1e-7:continue
            mid=mul(add(p,q),.5)
            left=allowed(add(mid,lateral))
            right=allowed(sub(mid,lateral))
            if left!=right:edges.append((p,q) if left else (q,p))

    unique={}
    for a,b in edges:
        ka,kb=_key(a),_key(b)
        if ka!=kb:unique[(ka,kb)]=(a,b)
    edges=list(unique.values())
    starts={}
    for i,(a,b) in enumerate(edges):starts.setdefault(_key(a),[]).append(i)
    loops=[];used=set()
    for start in range(len(edges)):
        if start in used:continue
        first=_key(edges[start][0]);idx=start;out=[]
        while idx not in used:
            used.add(idx);a,b=edges[idx];out.append(a)
            if _key(b)==first:
                out=clean(out)
                if len(out)>=3 and abs(area(out))>1e-9:loops.append(out)
                break
            nexts=[k for k in starts.get(_key(b),[]) if k not in used]
            if not nexts:
                raise ValueError('A margin clipping contour did not close.')
            if len(nexts)==1:idx=nexts[0]
            else:
                v=sub(b,a)
                idx=min(nexts,key=lambda k:(math.atan2(
                    cross(v,sub(edges[k][1],edges[k][0])),
                    dot(v,sub(edges[k][1],edges[k][0])))+2*math.pi)%(2*math.pi))
        else:
            raise ValueError('A margin intersection graph contained a cycle.')
    return loops


def clip_pocket(pocket, regions, exclusion_edges=None):
    """Clip a prospective cut to one or more regions with optional margins.

    Fast path: ordinary face/profile clipping. Margin path: subtract the
    exact (polygonally sampled) distance bands, including at sharp cusps.
    """
    if not exclusion_edges:
        return _clip_pocket_unbuffered(pocket,regions)
    pb=bounds(pocket)
    local=[]
    for box,a,b,r in exclusion_edges:
        if boxes_overlap(pb,box):
            poly=_capsule(a,b,r)
            local.append((poly,bounds(poly)))
    if not local:
        return _clip_pocket_unbuffered(pocket,regions)
    return _clip_with_exclusions(pocket,regions,local)


def rounded_triangle(vertices, inset, corner_radius, segments_per_corner=5):
    """Inset every triangle edge by rib/2; optional polygonal corner rounds.
    Pitch is the node spacing and inset is the half rib width.
    """
    poly=list(vertices)
    if area(poly)<0:poly.reverse()
    centroid=(sum(p[0] for p in poly)/3,sum(p[1] for p in poly)/3)
    pitch=norm(sub(poly[0],poly[1]))
    scale=1 - 2*SQRT3*inset/pitch
    if scale <= 0: return []
    core=[add(centroid,mul(sub(p,centroid),scale)) for p in poly]
    s=norm(sub(core[0],core[1]))
    r=max(0,corner_radius)
    if not r: return core
    if 2*SQRT3*r >= s-1e-7:
        raise ValueError('Corner radius is too large for the pocket.')
    # 60-degree interior vertices. Tangency points lie sqrt(3)*r along edges.
    t=SQRT3*r/s
    pts=[]
    for i in range(3):
        prev,p,nxt=core[i-1],core[i],core[(i+1)%3]
        before=add(p,mul(sub(prev,p),t))
        after=add(p,mul(sub(nxt,p),t))
        toward=mul(sub(centroid,p),1/norm(sub(centroid,p)))
        center=add(p,mul(toward,2*r))
        v0=sub(before,center);v1=sub(after,center)
        theta=math.atan2(cross(v0,v1),dot(v0,v1))
        # A convex CCW corner follows the positive, minor tangent arc.
        if theta < 0: theta += 2*math.pi
        for j in range(segments_per_corner+1):
            q=j/segments_per_corner
            ang=theta*q
            pts.append(add(center,(v0[0]*math.cos(ang)-v0[1]*math.sin(ang),
                                   v0[0]*math.sin(ang)+v0[1]*math.cos(ang))))
    # Exact arc orientation is checked by tests; external poly follows CCW vertices.
    return clean(pts)


def fillet_curve_loop(poly, radius, threshold_degrees=5, warnings=None):
    """Build an exact line/arc loop from a clipped pocket contour.

    Clipping can introduce new acute corners at the perimeter, or where a
    protected void meets a triangle. A fillet applied only to the original
    triangle is therefore insufficient. This routine runs after clipping.

    The fillet removes material from the cut region (never crosses into a
    protected margin). CW loops describe protected islands and are untouched:
    their corners are exterior to the cut, so they are already machinable.
    If a requested fillet cannot fit beside another corner, preserve the
    material-removal contour, omit the conflicting fillet and report that
    corner. This avoids losing an entire usable pocket around a small void.
    The caller can warn about the resulting sharp corners so the user may
    change dimensions or finish them manually.
    Near-tangent vertices on sampled arcs are left alone.
    """
    poly=clean(poly)
    if radius<=EPS or len(poly)<3 or area(poly)<=0:
        return polyline_curves(poly)
    n=len(poly)
    threshold=math.radians(threshold_degrees)
    tangent=[0.0]*n
    angles=[0.0]*n
    for i in range(n):
        prev,p,nxt=poly[i-1],poly[i],poly[(i+1)%n]
        u=sub(prev,p);v=sub(nxt,p)
        length_u=norm(u);length_v=norm(v)
        if min(length_u,length_v)<EPS:continue
        incoming=mul(u,-1)
        turn=math.atan2(cross(incoming,v),dot(incoming,v))
        if turn<=threshold or turn>math.pi-1e-5:
            continue  # tangent on an arc, or concave (machinable) corner
        interior=math.pi-turn
        tan_half=math.tan(interior/2)
        if tan_half<=EPS:continue
        angles[i]=interior
        tangent[i]=radius/tan_half
    # A small edge created by subtracting a hole can conflict with the two
    # adjacent fillets. Remove only conflicting fillets, keeping the pocket.
    # Prefer the corner with the smaller tangent demand (more affordable arc).
    while True:
        conflicts=[]
        for i in range(n):
            j=(i+1)%n
            length=norm(sub(poly[j],poly[i]))
            if tangent[i]+tangent[j]>length-1e-7:
                conflicts.append((i,j))
        if not conflicts:
            break
        i,j=conflicts[0]
        if tangent[i]<=EPS and tangent[j]<=EPS:
            break
        victim=i if tangent[i]>=tangent[j] else j
        tangent[victim]=0.0
        if warnings is not None:
            warnings.append(victim)
    incoming=[]
    outgoing=[]
    fillets=[]
    for i,p in enumerate(poly):
        t=tangent[i]
        if t<=EPS:
            incoming.append(p)
            outgoing.append(p)
            fillets.append(None)
            continue
        prev,nxt=poly[i-1],poly[(i+1)%n]
        u=mul(sub(prev,p),1/norm(sub(prev,p)))
        v=mul(sub(nxt,p),1/norm(sub(nxt,p)))
        alpha=angles[i]
        bisector=add(u,v)
        bisector=mul(bisector,1/norm(bisector))
        center=add(p,mul(bisector,radius/math.sin(alpha/2)))
        a=add(p,mul(u,t));b=add(p,mul(v,t))
        va=sub(a,center);vb=sub(b,center)
        sweep=math.atan2(cross(va,vb),dot(va,vb))
        if sweep<0:sweep+=math.tau
        incoming.append(a)
        outgoing.append(b)
        fillets.append(Arc2D(center, a, b, sweep))
    result=[]
    for i in range(n):
        # Walk in the original CCW contour direction. Each straight segment
        # joins the previous fillet's exit to this fillet's entry.
        a=outgoing[i-1]
        b=incoming[i]
        if norm(sub(a,b))>1e-8:
            result.append(Line2D(a,b))
        if fillets[i] is not None:
            result.append(fillets[i])
    return result


def round_clipped_contour(poly, radius, segments_per_corner=3,
                          threshold_degrees=5, warnings=None):
    """Polygonal derivative of the canonical circular fillet geometry."""
    return sample_curve_loop(
        fillet_curve_loop(poly, radius, threshold_degrees, warnings),
        segments_per_corner)


def face_bounds(regions):
    """Axis-aligned bounding box of exterior face loops."""
    exterior=[bounds(poly) for poly,outer in regions[0].loops if outer]
    return (min(b[0] for b in exterior),min(b[1] for b in exterior),
            max(b[2] for b in exterior),max(b[3] for b in exterior))


def lattice_origin(box,pitch,rotation,dx,dy,base_origin=None,anchor='vertex'):
    """Place a lattice vertex or the centre of an up-triangle on an anchor."""
    if base_origin is None:
        base_origin=((box[0]+box[2])/2,(box[1]+box[3])/2)
    point=(base_origin[0]+dx,base_origin[1]+dy)
    if anchor=='vertex':return point
    if anchor!='triangle':raise ValueError('Unknown lattice anchor.')
    theta=math.radians(rotation)
    shift=(pitch/2,SQRT3*pitch/6)
    return (point[0]-math.cos(theta)*shift[0]+math.sin(theta)*shift[1],
            point[1]-math.sin(theta)*shift[0]-math.cos(theta)*shift[1])


def lattice_pockets(box, pitch, rib, origin, rotation_degrees, corner_radius=0,
                    max_cells=2500):
    """Enumerate only grid cells intersecting an AABB, at a stable 2D origin."""
    if pitch<=0 or rib<=0 or rib>=pitch/SQRT3:
        raise ValueError('Pitch must exceed sqrt(3) × rib width.')
    theta=math.radians(rotation_degrees);ct,st=math.cos(theta),math.sin(theta)
    def forward(p):
        return (origin[0]+ct*p[0]-st*p[1],origin[1]+st*p[0]+ct*p[1])
    def inverse(p):
        x,y=sub(p,origin); return (ct*x+st*y,-st*x+ct*y)
    x0,y0,x1,y1=box
    corners=[inverse((x,y)) for x in (x0,x1) for y in (y0,y1)]
    lo_x=min(p[0] for p in corners)-pitch
    hi_x=max(p[0] for p in corners)+pitch
    lo_y=min(p[1] for p in corners)-pitch
    hi_y=max(p[1] for p in corners)+pitch
    h=SQRT3*pitch/2
    j0=math.floor(lo_y/h);j1=math.ceil(hi_y/h)
    i0=math.floor(lo_x/pitch)-2;i1=math.ceil(hi_x/pitch)+2
    count=2*(i1-i0+1)*(j1-j0+1)
    if count>max_cells*4:
        raise ValueError(f'Pattern too dense: {count} candidate cells; increase pitch.')
    for j in range(j0,j1+1):
        y=j*h;shift=(j%2)*pitch/2;next_shift=((j+1)%2)*pitch/2
        for i in range(i0,i1+1):
            a=(i*pitch+shift,y);b=((i+1)*pitch+shift,y)
            c=(i*pitch+next_shift,y+h);d=((i+1)*pitch+next_shift,y+h)
            if j%2==0: candidates=((a,b,c),(b,d,c))
            else: candidates=((a,b,d),(a,d,c))
            for triangle in candidates:
                outer=[forward(p) for p in triangle]
                if not boxes_overlap(bounds(outer),box): continue
                pocket=rounded_triangle(outer,rib/2,corner_radius)
                if pocket:yield pocket


def lattice_vertices(box,pitch,origin,rotation_degrees,limit=8000):
    """Every unique lattice junction; aligns exactly with lattice_pockets."""
    theta=math.radians(rotation_degrees)
    ct,st=math.cos(theta),math.sin(theta)
    def forward(p):
        return (origin[0]+ct*p[0]-st*p[1],origin[1]+st*p[0]+ct*p[1])
    def inverse(p):
        x,y=sub(p,origin);return (ct*x+st*y,-st*x+ct*y)
    x0,y0,x1,y1=box
    corners=[inverse((x,y)) for x in (x0,x1) for y in (y0,y1)]
    h=SQRT3*pitch/2
    j0=math.floor(min(p[1] for p in corners)/h)-2
    j1=math.ceil(max(p[1] for p in corners)/h)+2
    i0=math.floor(min(p[0] for p in corners)/pitch)-3
    i1=math.ceil(max(p[0] for p in corners)/pitch)+3
    if (i1-i0+1)*(j1-j0+1)>limit*4:
        raise ValueError('Too many grid vertices; increase cell pitch.')
    for j in range(j0,j1+1):
        shift=(j%2)*pitch/2
        for i in range(i0,i1+1):
            p=forward((i*pitch+shift,j*h))
            if boxes_overlap(box,(p[0],p[1],p[0],p[1])):
                yield p


def circle_polygon(center,radius,sides=32):
    return [(center[0]+radius*math.cos(2*math.pi*i/sides),
             center[1]+radius*math.sin(2*math.pi*i/sides))
            for i in range(sides)]


def _distance_to_segment(p,a,b):
    ab=sub(b,a)
    t=max(0,min(1,dot(sub(p,a),ab)/dot(ab,ab)))
    return norm(sub(p,add(a,mul(ab,t))))



def _point_in_ccw_triangle(p, tri):
    """Interior test for the convex CCW triangular unrounded cell."""
    for a,b in _segments(tri):
        if cross(sub(b,a),sub(p,a)) < -2e-8:
            return False
    return True


def _segment_touches_triangle(a, b, tri):
    """Does the segment enter or touch a CCW triangle?"""
    if _point_in_ccw_triangle(a,tri) or _point_in_ccw_triangle(b,tri):
        return True
    seg_box=bounds([a,b])
    for c,d in _segments(tri):
        if boxes_overlap(seg_box,bounds([c,d])) and intersections(a,b,c,d):
            return True
    return False


class _BoxIndex:
    """Small dependency-free uniform-grid AABB index, built once per face.

    Handles clustered boundaries (e.g. many tessellated points on a circular
    hole) without a full scan of every capsule/segment for each trial cell.
    The grid is only a broad-phase filter; predicates retain full precision.
    """
    def __init__(self, records, face_box):
        self.records = records  # records have AABB in position zero
        self.bounds = face_box
        count = len(records)
        self.n = min(56, max(8, round(math.sqrt(max(count, 1)) / 1.6)))
        x0, y0, x1, y1 = face_box
        self.x0, self.y0 = x0, y0
        self.step_x = max((x1-x0)/self.n, 1e-7)
        self.step_y = max((y1-y0)/self.n, 1e-7)
        self.bins = {}
        for i, (box, *_) in enumerate(records):
            ix0, iy0, ix1, iy1 = self._cells(box)
            for ix in range(ix0, ix1+1):
                for iy in range(iy0, iy1+1):
                    self.bins.setdefault((ix,iy), []).append(i)

    def _cells(self, box):
        # Out-of-region queries can be clipped to the nearest edge bin. The
        # final AABB test ensures those candidates are rejected accurately.
        return (max(0, min(self.n-1, int(math.floor((box[0]-self.x0)/self.step_x)))),
                max(0, min(self.n-1, int(math.floor((box[1]-self.y0)/self.step_y)))),
                max(0, min(self.n-1, int(math.floor((box[2]-self.x0)/self.step_x)))),
                max(0, min(self.n-1, int(math.floor((box[3]-self.y0)/self.step_y)))))

    def query(self, box):
        if not self.records:
            return []
        x0,y0,x1,y1 = self.bounds
        if not boxes_overlap(box, (x0,y0,x1,y1)):
            return []
        ix0,iy0,ix1,iy1 = self._cells(box)
        found=set()
        for ix in range(ix0,ix1+1):
            for iy in range(iy0,iy1+1):
                found.update(self.bins.get((ix,iy),()))
        return [self.records[i] for i in sorted(found)
                if boxes_overlap(box,self.records[i][0])]


def _clip_prepared_python(pocket, regions, boundary_segments, capsules):
    """Exact segment-arrangement clipping with spatially selected segments.

    The same allowed-region/overlapping-capsule Boolean as the legacy
    fallback, but segment operations are spatially indexed. At preparation
    time this constructs the complete permitted region, including margins.
    At evaluation time it clips only triangles crossing that prepared mask.
    """
    pocket=clean(pocket)
    if area(pocket)<0:pocket.reverse()
    parts=[]
    for a,b in _segments(pocket):
        parts.append((a,b,bounds([a,b])))
    parts.extend((a,b,box) for box,a,b in boundary_segments)
    parts.extend((a,b,box) for box,a,b in capsules[1])
    # The candidate can be entirely inside/outside a large region/capsule.
    # Segment intersections alone cannot classify this case; the predicate
    # handles it identically to the original Boolean arrangement.
    local_caps=capsules[0]
    # Large global-mask preparations need indices for both the arrangement
    # and the union-of-capsules point test. Local individual cells are small
    # enough for direct iteration.
    shared_box=bounds([q for _,_,box in parts for q in
                       ((box[0],box[1]),(box[2],box[3]))])
    segment_index = (_BoxIndex([(box,a,b,i) for i,(a,b,box) in enumerate(parts)],shared_box)
                     if len(parts)>150 else None)
    cap_index = (_BoxIndex(local_caps,shared_box)
                 if len(local_caps)>20 else None)
    def allowed(pt):
        if not in_poly(pt,pocket,False):return False
        if not all(region.contains(pt,False) for region in regions):return False
        candidates = (cap_index.query((pt[0],pt[1],pt[0],pt[1]))
                      if cap_index else local_caps)
        return not any(in_poly(pt,poly,True) for _,poly in candidates)
    edges=[]
    for i,(a,b,segbox) in enumerate(parts):
        cuts=[0.0,1.0]
        other_parts = (([(c,d,bb,j) for bb,c,d,j in segment_index.query(segbox)])
                       if segment_index else
                       ((c,d,bb,j) for j,(c,d,bb) in enumerate(parts)))
        for c,d,otherbox,j in other_parts:
            if i!=j and boxes_overlap(segbox,otherbox):
                cuts.extend(t for t,_ in intersections(a,b,c,d))
        cuts=sorted(set(round(t,11) for t in cuts))
        delta=sub(b,a)
        length=norm(delta)
        if length<EPS:continue
        lateral=(-delta[1]*2e-6/length,delta[0]*2e-6/length)
        for t,u in zip(cuts,cuts[1:]):
            if u-t<1e-9:continue
            p=add(a,mul(delta,t));q=add(a,mul(delta,u))
            if norm(sub(p,q))<1e-7:continue
            mid=mul(add(p,q),.5)
            left=allowed(add(mid,lateral))
            right=allowed(sub(mid,lateral))
            if left!=right:edges.append((p,q) if left else (q,p))
    unique={}
    for a,b in edges:
        ka,kb=_key(a),_key(b)
        if ka!=kb:unique[(ka,kb)]=(a,b)
    edges=list(unique.values())
    starts={}
    for i,(a,b) in enumerate(edges):starts.setdefault(_key(a),[]).append(i)
    loops=[];used=set()
    for start in range(len(edges)):
        if start in used:continue
        first=_key(edges[start][0]);idx=start;out=[]
        while idx not in used:
            used.add(idx);a,b=edges[idx];out.append(a)
            if _key(b)==first:
                out=clean(out)
                if len(out)>=3 and abs(area(out))>1e-9:loops.append(out)
                break
            nexts=[k for k in starts.get(_key(b),[]) if k not in used]
            if not nexts:
                raise ValueError('A margin clipping contour did not close.')
            if len(nexts)==1:idx=nexts[0]
            else:
                v=sub(b,a)
                idx=min(nexts,key=lambda k:(math.atan2(
                    cross(v,sub(edges[k][1],edges[k][0])),
                    dot(v,sub(edges[k][1],edges[k][0])))+2*math.pi)%(2*math.pi))
        else:
            raise ValueError('A margin intersection graph contained a cycle.')
    return loops


class PreparedGeometry:
    """Reusable geometry with interchangeable pure-Python and GEOS backends.

    Both use identical 2-D pocket generation, post-clipping corner rounding,
    final cut shapes and fit metrics.  Backends differ only in the exact
    implementation of region/buffer Boolean clipping.
    """
    def __init__(self, regions, perimeter, void_clearance, backend='auto'):
        if backend not in ('auto','python','geos'):
            raise ValueError('Geometry backend must be auto, python or geos.')
        if backend == 'geos' and _CompiledArea is None:
            raise RuntimeError('GEOS backend unavailable; install Shapely/NumPy or select Python.')
        self.regions=regions
        self.perimeter=perimeter
        self.void_clearance=void_clearance
        # Production face/profile boundaries carry native curves.  Run the
        # exact analytic intersection path; synthetic polygon-only fixtures
        # retain the previous engine until their migration is complete.
        self.exact = None
        if backend != 'geos' and all(region.curve_loops is not None
                                     for region in regions):
            self.exact = _exact.PreparedCurves([
                _exact.CurveRegion([(list(path),outer)
                                    for path,(_,outer) in zip(region.curve_loops,region.loops)])
                for region in regions],perimeter,void_clearance)
            self.backend='exact'
            self.compiled=None
            self.exclusions=[]
            return
        self.backend = ('geos' if backend=='geos' or
                        (backend=='auto' and _CompiledArea is not None)
                        else 'python')
        self.compiled = (_CompiledArea(regions,perimeter,void_clearance)
                         if self.backend == 'geos' else None)
        self.exclusions = _buffer_edges(regions,perimeter,void_clearance)
        if self.compiled is None:
            # Prepare *one* unioned polygonal region from the original face,
            # sketch restrictions, and conservative circular edge margins.
            # This is identical to the legacy Boolean result, but is done
            # ONCE per pattern/fit search instead of once per triangle.
            face_box=face_bounds(regions)
            radius=max(perimeter,void_clearance)
            preparation_box=expand_box(face_box,max(1.0,2*radius+1e-4))
            raw_edges=[]
            for region in regions:
                for poly,_ in region.loops:
                    for a,b in _segments(poly):
                        raw_edges.append((bounds([a,b]),a,b))
            capsule_records=[]
            capsule_segments=[]
            for _,a,b,r in self.exclusions:
                poly=_capsule(a,b,r)
                cb=bounds(poly)
                capsule_records.append((cb,poly))
                capsule_segments.extend((bounds([c,d]),c,d)
                                        for c,d in _segments(poly))
            x0,y0,x1,y1=preparation_box
            enclosing=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
            contours=_clip_prepared_python(enclosing,regions,raw_edges,
                                             (capsule_records,capsule_segments))
            if not any(area(poly)>1e-9 for poly in contours):
                raise ValueError('Margins leave no usable isogrid area.')
            self._mask_region=Region([(poly,area(poly)>0) for poly in contours])
            mask_segments=[]
            for poly,_ in self._mask_region.loops:
                mask_segments.extend((bounds([a,b]),a,b) for a,b in _segments(poly))
            self._mask_boundary_index=_BoxIndex(mask_segments,preparation_box)
        else:
            self._mask_region=None
            self._mask_boundary_index=None

    def clip(self, pocket):
        if self.exact is not None:return self.exact.clip(pocket)
        if self.compiled is not None:
            return self.compiled.clip(pocket)
        local_edges=self._mask_boundary_index.query(bounds(pocket))
        if not any(_segment_touches_triangle(a,b,pocket)
                   for _,a,b in local_edges):
            # No margin/void/face boundary crosses this triangular pocket:
            # it is either fully valid or entirely excluded.
            if self._mask_region.contains(polygon_centroid(pocket),False):
                return [pocket]
            return []
        return _clip_prepared_python(pocket,[self._mask_region],
                                     local_edges,([],[]))

    def clip_many(self, pockets):
        if self.exact is not None:return self.exact.clip_many(pockets)
        if self.compiled is not None:
            return self.compiled.clip_many(pockets)
        return [self.clip(pocket) for pocket in pockets]

    def circle_fits(self, center, radius):
        if self.exact is not None:return self.exact.circle_fits(center,radius)
        if self.compiled is not None:
            return self.compiled.circle_fits(center, radius)
        if not all(reg.contains(center,False) for reg in self.regions):
            return False
        cb=expand_box((center[0],center[1],center[0],center[1]),radius)
        for box,a,b,margin in self.exclusions:
            if boxes_overlap(cb,box) and _distance_to_segment(center,a,b)<radius+margin+2e-6:
                return False
        for region in self.regions:
            for poly,_ in region.loops:
                for a,b in _segments(poly):
                    if boxes_overlap(bounds([a,b]),cb) and _distance_to_segment(center,a,b)<radius+2e-6:
                        return False
        return True


def make_pockets(regions,pitch,rib,perimeter,void_clearance,offset_x,offset_y,
                 rotation,corner_radius=0,min_area_fraction=0.05,max_cells=2500,
                 vertex_hole_diameter=0,base_origin=None,anchor='vertex',
                 prepared=None, backend='auto', trim_boundary=True):
    if not regions:raise ValueError('No selected area.')
    if vertex_hole_diameter<0:
        raise ValueError('Vertex hole diameter must be non-negative.')
    # Distance-to-boundary exclusion bands, rather than miter offsets. They
    # handle the zero-angle cusp shown by the test panel and narrow necks.
    if trim_boundary and prepared is None:
        prepared=PreparedGeometry(regions,perimeter,void_clearance,backend=backend)
    box=face_bounds(regions)
    # In sketch-bounded mode, the optional profile restricts the extent of an
    # untrimmed grid too, even though we leave its individual pockets intact.
    for region in regions[1:]:
        rbox=face_bounds([region])
        box=(max(box[0],rbox[0]),max(box[1],rbox[1]),
             min(box[2],rbox[2]),min(box[3],rbox[3]))
    if box[0]>=box[2] or box[1]>=box[3]:
        return []
    origin=lattice_origin(box,pitch,rotation,offset_x,offset_y,base_origin,anchor)
    results=[];total=0
    min_area=SQRT3/4*(pitch-SQRT3*rib)**2*min_area_fraction
    # Interior pockets are congruent. Fillet their canonical triangle once
    # per pitch and transform it, instead of recomputing 3 arcs per cell.
    side=pitch-SQRT3*rib
    reference=[(0.0,0.0),(side,0.0),(side/2,SQRT3*side/2)]
    template_warnings=[]
    # Exact arcs are the source of truth. Their polygonal samples serve the
    # intersection/scoring algorithm and the custom-graphics preview only.
    template_curves=fillet_curve_loop(reference,corner_radius,
                                     warnings=template_warnings)
    full_template=sample_curve_loop(template_curves)
    pockets=list(lattice_pockets(box,pitch,rib,origin,rotation,0,max_cells))
    if len(pockets)>max_cells:
        raise ValueError(f'Pattern exceeds {max_cells} cells; increase pitch.')
    clippings=(prepared.clip_many(pockets) if trim_boundary else
               [[p] for p in pockets])
    for pocket,clipped in zip(pockets,clippings):
        if not clipped:continue
        if trim_boundary and prepared.exact is not None:
            # Curves are the source of truth.  Clipping and corner fillets use
            # analytic line/arc intersections; sampled polygons exist only for
            # preview, scoring, and Fusion's profile-selection convenience.
            outers=[];curve_loops=[];pending_holes=[];fillet_warnings=0
            for raw_loop in clipped:
                signed=_curves.loop_area(raw_loop)
                if signed<0:
                    pending_holes.append(raw_loop)
                    continue
                if signed<=min_area:continue
                issues=[]
                curves=_exact.fillet_loop(raw_loop,corner_radius,issues)
                fillet_warnings+=len(issues)
                poly=_curves.sample(curves,chord_tolerance=.0004)
                if len(poly)>=3 and _curves.loop_area(curves)>min_area:
                    outers.append(poly)
                    curve_loops.append(curves)
            if outers:
                for hole in pending_holes:
                    # A negative loop fully enclosed by a retained positive
                    # contour represents a protected island in the pocket.
                    if any(_curves.loop_contains(outer,hole[0].start)
                           for outer in curve_loops):
                        curve_loops.append(hole)
                        outers.append(_curves.sample(hole,chord_tolerance=.0004))
                results.append(CutShape(pocket,outers,fillet_warnings=fillet_warnings,
                                        curve_loops=curve_loops))
            continue
        if len(clipped)==1 and clipped[0] is pocket:
            if full_template:
                u=sub(pocket[1],pocket[0])
                ct,st=u[0]/side,u[1]/side
                x0,y0=pocket[0]
                contour=[(x0+ct*x-st*y,y0+st*x+ct*y)
                         for x,y in full_template]
                if area(contour)>min_area:
                    curves=transform_curve_loop(template_curves,ct,st,(x0,y0))
                    results.append(CutShape(pocket,[contour],
                                            fillet_warnings=len(template_warnings),
                                            curve_loops=[curves]))
            continue
        # Keep holes associated with large valid pocket islands; remove tiny
        # outer slivers, then only include void loops that lie inside kept islands.
        rounded=[]
        curve_loops=[]
        fillet_warnings=0
        for p in clipped:
            if area(p)<=min_area:continue
            local_warnings=[]
            curves=fillet_curve_loop(p,corner_radius,warnings=local_warnings)
            contour=sample_curve_loop(curves)
            fillet_warnings+=len(local_warnings)
            if len(contour)>=3 and area(contour)>min_area:
                rounded.append(contour)
                curve_loops.append(curves)
        outers=rounded
        holes=[p for p in clipped if area(p)<0 and any(in_poly(p[0],o,False) for o in outers)]
        if outers:
            curve_loops.extend(polyline_curves(p) for p in holes)
            results.append(CutShape(pocket,outers+holes,
                                    fillet_warnings=fillet_warnings,
                                    curve_loops=curve_loops))
    if vertex_hole_diameter>EPS:
        r=vertex_hole_diameter/2
        for center in lattice_vertices(box,pitch,origin,rotation):
            # A junction hole is cut only if its entire circular profile fits
            # inside the allowed area. Partial holes at an edge are undesirable.
            if trim_boundary and not prepared.circle_fits(center,r):continue
            circle=circle_polygon(center,r)
            results.append(CutShape(circle,[circle],(center,r)))
    return results
