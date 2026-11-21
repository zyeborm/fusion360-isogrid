"""Non-destructive manufacturability diagnostics for native Isogrid cuts.

Only the generated *view polygons* are used for the clearance screening; the
original native Fusion curves remain the source of truth for sketch output.
Everything is in Fusion's internal centimetres. No external dependencies.
"""
from dataclasses import dataclass
import heapq
import math
import geometry


@dataclass(frozen=True)
class Report:
    unmachinable_corners: int = 0
    inaccessible_pockets: int = 0
    narrow_web_count: int = 0
    web_shapes: tuple = ()  # Original shape indexes for preview highlighting.
    cutter_shapes: tuple = ()
    minimum_web_cm: float | None = None


def _segment_distance(a,b,c,d):
    # Segment-segment intersection first, then endpoint-to-segment distances.
    ab=geometry.sub(b,a);cd=geometry.sub(d,c)
    den=geometry.cross(ab,cd)
    if abs(den)>1e-14:
        ac=geometry.sub(c,a)
        t=geometry.cross(ac,cd)/den
        u=geometry.cross(ac,ab)/den
        if 0<=t<=1 and 0<=u<=1:return 0.
    def point_line(p,x,y):
        v=geometry.sub(y,x);vv=geometry.dot(v,v)
        t=max(0.,min(1.,geometry.dot(geometry.sub(p,x),v)/vv)) if vv>1e-20 else 0.
        q=geometry.add(x,geometry.mul(v,t))
        return geometry.norm(geometry.sub(p,q))
    return min(point_line(a,c,d),point_line(b,c,d),
               point_line(c,a,b),point_line(d,a,b))


def _segments(poly):
    return list(zip(poly,poly[1:]+poly[:1]))


def _signed_clearance(x,y,loops):
    p=(x,y)
    inside=False
    best=math.inf
    for loop in loops:
        if len(loop)<3:continue
        if geometry.in_poly(p,loop,False):
            inside=(geometry.area(loop)>0) if not inside else False
        for a,b in _segments(loop):
            v=geometry.sub(b,a);vv=geometry.dot(v,v)
            t=max(0.,min(1.,geometry.dot(geometry.sub(p,a),v)/vv)) if vv>1e-20 else 0.
            q=geometry.add(a,geometry.mul(v,t))
            best=min(best,geometry.norm(geometry.sub(p,q)))
    return best if inside else -best


def _can_fit_disk(loops,radius):
    """Adaptive polygonal inscribed-disk test (early-out if a disk fits).

    Uses a conservative sampling tolerance; the result is a manufacturability
    screen for the *sampled* contour, not an exact clearance certificate.
    """
    if radius<=0:return True
    outers=[poly for poly in loops if geometry.area(poly)>0]
    if not outers:return False
    for poly in outers:
        x0,y0,x1,y1=geometry.bounds(poly)
        if min(x1-x0,y1-y0)+1e-12 < 2*radius:continue
        for x,y in [geometry.polygon_centroid(poly),((x0+x1)/2,(y0+y1)/2)]:
            if _signed_clearance(x,y,loops)>=radius+1e-5:return True
        size=max(x1-x0,y1-y0)
        if size<=0:continue
        # Best-first upper-bounded search over possible cutter centres.
        # Stop when potential centre clearance cannot reach radius.
        heap=[];serial=0
        def push(x,y,h):
            nonlocal serial
            d=_signed_clearance(x,y,loops)
            bound=d+h*math.sqrt(2.)
            if bound>=radius:
                serial+=1
                heapq.heappush(heap,(-bound,serial,x,y,h,d))
        # Start with a bounding square so even skinny polygons are explored.
        h=size/2
        push((x0+x1)/2,(y0+y1)/2,h)
        iterations=0
        while heap and iterations<1500:
            _,_,x,y,h,d=heapq.heappop(heap)
            iterations+=1
            if d>=radius+1e-5:return True
            if h<.0005:continue  # 0.005 mm spatial sampling tolerance
            half=h/2
            for dx in (-half,half):
                for dy in (-half,half):push(x+dx,y+dy,half)
    return False


def _closest_loops(a,b,limit):
    """Distance between sampled closed boundaries; early stop on collision."""
    best=math.inf
    for pa in a:
        ba=geometry.bounds(pa)
        for pb in b:
            bb=geometry.bounds(pb)
            if not geometry.boxes_overlap(ba,bb,limit):continue
            for x,y in _segments(pa):
                b0=(min(x[0],y[0]),min(x[1],y[1]),
                    max(x[0],y[0]),max(x[1],y[1]))
                for u,v in _segments(pb):
                    b1=(min(u[0],v[0]),min(u[1],v[1]),
                        max(u[0],v[0]),max(u[1],v[1]))
                    if not geometry.boxes_overlap(b0,b1,limit):continue
                    dist=_segment_distance(x,y,u,v)
                    if dist<best:best=dist
                    if best<limit:return best
    return best


def screen(shapes, regions, settings):
    """Check existing geometry, never change or omit a shape.

    Tool diameter 0 disables all cutter checks (e.g. for printed parts).
    The baseline geometric web check uses each user-specified dimension:
    rib width between cuts, perimeter margin at exterior edges and void
    clearance at holes. All measurements use sampled outline polygons.
    """
    cutter=settings.get('tool_diameter',0.)
    cutter_indexes=set()
    sharp=blocked=0
    if cutter>0:
        for i,shape in enumerate(shapes):
            if shape.circle:continue  # Vertex holes can be drilled independently.
            if shape.fillet_warnings:
                sharp+=1
                cutter_indexes.add(i)
            for loop in shape.loops:
                if geometry.area(loop)<=0:continue
                holes=[h for h in shape.loops if geometry.area(h)<0 and
                       geometry.in_poly(h[0],loop,False)]
                if not _can_fit_disk([loop]+holes,cutter/2.):
                    blocked+=1
                    cutter_indexes.add(i)

    rib=settings['rib']
    perimeter=settings['perimeter']
    void=settings['holeclear']
    indexes=set();best=math.inf;violations=0
    # Normal vertex-hole shapes have a sampled circle in `loops`, but preserve
    # native-circle-only shapes supplied by upstream callers or test fixtures.
    loops_by_shape=[s.loops if s.loops else
                    [geometry.circle_polygon(*s.circle)] if s.circle else []
                    for s in shapes]
    boxes=[geometry.bounds([p for loop in loops for p in loop]) if loops else None
           for loops in loops_by_shape]
    for i,shape in enumerate(shapes):
        if boxes[i] is None:continue
        # Between cuts the specified rib width is the intended material web.
        for j in range(i+1,len(shapes)):
            if boxes[j] is None or not geometry.boxes_overlap(boxes[i],boxes[j],rib):continue
            dist=_closest_loops(loops_by_shape[i],loops_by_shape[j],rib)
            best=min(best,dist)
            if dist+2e-5<rib:  # Sampling tolerance: 0.0002 mm.
                indexes.update((i,j));violations+=1
        # Preserve independently entered perimeter / cutout clearances.
        for region in regions:
            for boundary,outer in region.loops:
                clearance=perimeter if outer else void
                if clearance<=0:continue
                if not geometry.boxes_overlap(boxes[i],geometry.bounds(boundary),clearance):continue
                dist=_closest_loops(loops_by_shape[i],[boundary],clearance)
                best=min(best,dist)
                if dist+2e-5<clearance:
                    indexes.add(i);violations+=1
    return shapes,Report(unmachinable_corners=sharp,
                      inaccessible_pockets=blocked,
                      narrow_web_count=violations,
                      web_shapes=tuple(sorted(indexes)),
                      cutter_shapes=tuple(sorted(cutter_indexes)),
                      minimum_web_cm=best if math.isfinite(best) else None)
