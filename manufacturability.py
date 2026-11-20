"""Optional manufacturability constraints on native Isogrid cut shapes.

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
    omitted: int = 0
    unmachinable_corners: int = 0
    narrow_web_count: int = 0
    web_shapes: tuple = ()  # Indexes into retained list, for preview highlighting.
    minimum_web_cm: float | None = None


def effective(settings):
    """Return geometry generation dimensions after optional constraints.

    Rib and boundary margin are minimum *material* widths. Cutter diameter
    dictates a minimum internal corner radius for machinable pockets.
    """
    minimum=max(0.,settings.get('min_web',0.))
    cutter=max(0.,settings.get('tool_diameter',0.))
    return (max(settings['rib'],minimum),
            max(settings['perimeter'],minimum),
            max(settings['holeclear'],minimum),
            max(settings['corner'],cutter/2.))


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
    """Apply opt-in minimum usable pocket diameter and report web violations.

    Cutter clearance and min usable-pocket size suppress entire unusable cut
    islands. Existing sketch entities are untouched; reports refer to the
    retained native shapes and can be overlaid in Fusion's preview.
    """
    diameter=max(settings.get('tool_diameter',0.),settings.get('min_pocket',0.))
    retained=[];omitted=0;unmachinable_corners=0
    for shape in shapes:
        if settings.get('tool_diameter',0.)>0 and shape.fillet_warnings:
            # The exact geometry engine left one or more corners sharp
            # because the requested radius could not fit. That is acceptable
            # for general patterning, but not for an explicitly sized mill.
            # Affected source cells are omitted instead of emitting a pocket
            # which the named cutter could never machine.
            omitted+=1
            unmachinable_corners+=1
            continue
        if not diameter:
            retained.append(shape);continue
        if shape.circle:
            # Junction holes can be drilled independently of the pocket
            # milling cutter. A pocket-width limit must not delete them.
            retained.append(shape);continue
        keep_loops=[];keep_curves=[]
        for i,loop in enumerate(shape.loops):
            if geometry.area(loop)<=0:
                # Attached hole contours remain with their enclosing island;
                # they are accounted for in the cutter-centre test below.
                continue
            holes=[h for h in shape.loops if geometry.area(h)<0 and
                   geometry.in_poly(h[0],loop,False)]
            if _can_fit_disk([loop]+holes,diameter/2):
                keep_loops.append(loop)
                if shape.curve_loops:keep_curves.append(shape.curve_loops[i])
                for h in holes:
                    keep_loops.append(h)
                    if shape.curve_loops:
                        j=next((j for j,other in enumerate(shape.loops) if other is h),None)
                        if j is not None:keep_curves.append(shape.curve_loops[j])
            else:omitted+=1
        if keep_loops:
            if len(keep_loops)==len(shape.loops):
                retained.append(shape)
            else:
                retained.append(geometry.CutShape(shape.outline,keep_loops,
                       fillet_warnings=shape.fillet_warnings,
                       curve_loops=keep_curves if shape.curve_loops else None))
    minimum=settings.get('min_web',0.)
    if not minimum:return retained,Report(
        omitted=omitted,unmachinable_corners=unmachinable_corners)
    indexes=set();best=math.inf;violations=0
    boxes=[geometry.bounds([p for loop in s.loops for p in loop]) for s in retained]
    # Group-wide distance includes both adjacent pockets and vertex-hole cuts.
    for i,shape in enumerate(retained):
        for j in range(i+1,len(retained)):
            if not geometry.boxes_overlap(boxes[i],boxes[j],minimum):continue
            dist=_closest_loops(shape.loops,retained[j].loops,minimum)
            best=min(best,dist)
            if dist+2e-5<minimum:  # Sampling tolerance: 0.0002 mm.
                indexes.update((i,j));violations+=1
        # Outer face boundary and existing voids are also material interfaces.
        for region in regions:
            for boundary,_ in region.loops:
                if not geometry.boxes_overlap(boxes[i],geometry.bounds(boundary),minimum):continue
                dist=_closest_loops(shape.loops,[boundary],minimum)
                best=min(best,dist)
                if dist+2e-5<minimum:
                    indexes.add(i);violations+=1
    return retained,Report(omitted=omitted,
                      unmachinable_corners=unmachinable_corners,
                      narrow_web_count=violations,
                      web_shapes=tuple(sorted(indexes)),
                      minimum_web_cm=best if math.isfinite(best) else None)
