"""Pure Python 2D isogrid clipping against native line and circular-arc loops.

The Boolean is evaluated by a split-edge arrangement. Each source edge retains
its analytic shape; the boundary of the intersection is selected using a pair
of strict inside/outside tests at segment midpoints. Boundary margins are a
union of exact line/arc tubular neighbourhoods, rather than tessellated boxes.

Other curve families can extend the curve protocol (point/tangent/section,
intersections, bounds, distance) without changing the arrangement algorithm.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict
import math
import curves2d as c


@dataclass
class CurveRegion:
    loops: list  # [(list[Line|Arc], is_outer)]
    def __post_init__(self):
        for loop,outer in self.loops:
            if not c.close_loop(loop):raise ValueError('Open curve boundary loop')
            if outer and c.loop_area(loop)<0:
                loop[:]=c.reverse_loop(loop)
            if not outer and c.loop_area(loop)>0:
                loop[:]=c.reverse_loop(loop)
        if not any(outer for _,outer in self.loops):raise ValueError('Missing exterior boundary')
    def contains(self,p):
        return any(outer and c.loop_contains(loop,p) for loop,outer in self.loops) and not any(
            not outer and c.loop_contains(loop,p) for loop,outer in self.loops)
    def bounds(self):
        boxes=[c.bounds(s) for loop,outer in self.loops if outer for s in loop]
        return (min(b[0] for b in boxes),min(b[1] for b in boxes),
                max(b[2] for b in boxes),max(b[3] for b in boxes))


@dataclass
class _Edge:
    segment: c.Line|c.Arc
    bbox: tuple


def _signature(seg,tol=1e-6):
    def pt(p):return (round(p[0]/tol),round(p[1]/tol))
    return (('L',pt(seg.start),pt(seg.end)) if isinstance(seg,c.Line) else
            ('A',pt(seg.start),pt(seg.end),pt(seg.center),round(seg.sweep,6)))


def _key(p,tol=1e-6):return (round(p[0]/tol),round(p[1]/tol))


def _split_edges(edges):
    cuts=[[0.,1.] for _ in edges]
    for i,a in enumerate(edges):
        ba=c.bounds(a)
        for j in range(i+1,len(edges)):
            b=edges[j]
            if not c.overlaps(ba,c.bounds(b),2e-7):continue
            for p in c.intersections(a,b):
                t=c.parameter(a,p);u=c.parameter(b,p)
                if t is not None and u is not None:
                    cuts[i].append(t);cuts[j].append(u)
    for seg,times in zip(edges,cuts):
        ordered=sorted(times)
        uniq=[ordered[0]]
        for t in ordered[1:]:
            if t-uniq[-1]>1e-8:uniq.append(t)
        for a,b in zip(uniq,uniq[1:]):
            # An unsplit full circle starts and ends at the same point, yet
            # contributes an entire closed boundary to the result.
            if b-a>1e-8 and (isinstance(seg,c.Arc) and
                             abs(seg.sweep*(b-a))>1e-7 or
                             c.length(c.sub(seg.point(a),seg.point(b)))>1e-8):
                yield seg.section(a,b)


def _assemble(directed):
    outgoing=defaultdict(list)
    for i,seg in enumerate(directed):outgoing[_key(seg.start)].append(i)
    unused=set(range(len(directed)))
    loops=[]
    while unused:
        idx=next(iter(unused));start=directed[idx].start;path=[]
        for _ in range(len(directed)+1):
            if idx not in unused:break
            unused.remove(idx);segment=directed[idx];path.append(segment)
            if c.near(segment.end,start,2e-5):break
            nexts=[j for j in outgoing[_key(segment.end)] if j in unused]
            if not nexts:
                # Occasionally a nearly coincident intersection falls on the
                # adjoining bucket boundary; locate the neighbour geometrically.
                nexts=[j for j in unused if c.near(directed[j].start,segment.end,2e-5)]
            if not nexts:raise ValueError('Clipped exact contour has an open edge')
            if len(nexts)==1:idx=nexts[0];continue
            tangent=segment.tangent(1)
            def turn(j):
                t=directed[j].tangent(0)
                return math.atan2(c.cross(tangent,t),c.dot(tangent,t))%math.tau
            # With valid region to the left, take the first CCW successor.
            idx=min(nexts,key=turn)
        if not c.close_loop(path,2e-5):raise ValueError('Clipped exact contour is not closed')
        if abs(c.loop_area(path))>1e-9:
            loops.append(merge_curves(path))
    return loops


def merge_curves(loop,tolerance=1e-7):
    """Join adjacent collinear lines or co-circular arcs without approximation."""
    result=[]
    for seg in loop:
        if result:
            prev=result[-1]
            if isinstance(prev,c.Line) and isinstance(seg,c.Line):
                a=c.sub(prev.end,prev.start);b=c.sub(seg.end,seg.start)
                if c.near(prev.end,seg.start,tolerance) and c.cross(a,b)**2 <=1e-14*c.dot(a,a)*c.dot(b,b) and c.dot(a,b)>0:
                    result[-1]=c.Line(prev.start,seg.end);continue
            if isinstance(prev,c.Arc) and isinstance(seg,c.Arc) and c.near(prev.end,seg.start,tolerance) and c.near(prev.center,seg.center,tolerance) and abs(prev.radius-seg.radius)<tolerance and prev.sweep*seg.sweep>0:
                if abs(prev.sweep+seg.sweep)<math.tau+1e-6:
                    result[-1]=c.Arc(prev.center,prev.start,seg.end,prev.sweep+seg.sweep);continue
        result.append(seg)
    if len(result)>1:
        a,b=result[-1],result[0]
        if isinstance(a,c.Line) and isinstance(b,c.Line) and c.near(a.end,b.start,tolerance):
            u=c.sub(a.end,a.start);v=c.sub(b.end,b.start)
            if c.cross(u,v)**2 <=1e-14*c.dot(u,u)*c.dot(v,v) and c.dot(u,v)>0:
                result[0]=c.Line(a.start,b.end);result.pop()
        elif isinstance(a,c.Arc) and isinstance(b,c.Arc) and c.near(a.end,b.start,tolerance) and c.near(a.center,b.center,tolerance) and abs(a.radius-b.radius)<tolerance and a.sweep*b.sweep>0 and abs(a.sweep+b.sweep)<math.tau+1e-6:
            result[0]=c.Arc(a.center,a.start,b.end,a.sweep+b.sweep);result.pop()
    return result


class PreparedCurves:
    """Reusable exact face representation; all geometry remains plain Python."""
    def __init__(self,regions,perimeter,void_clearance):
        self.regions=regions
        self.perimeter=perimeter
        self.void_clearance=void_clearance
        self.edges=[];self.source=[]
        for region in regions:
            for loop,is_outer in region.loops:
                margin=perimeter if is_outer else void_clearance
                for seg in loop:
                    self.source.append((seg,margin))
                    for piece in (c.capsule(seg,margin) if margin>1e-9 else [seg]):
                        self.edges.append(_Edge(piece,c.bounds(piece)))

    def inside(self,p):
        for region in self.regions:
            if not region.contains(p):return False
        for segment,margin in self.source:
            if margin>1e-9 and c.point_distance(segment,p)<margin-2e-9:
                return False
        return True

    def circle_fits(self,p,r):
        if not all(region.contains(p) for region in self.regions):return False
        return all(c.point_distance(seg,p)>=r+margin-1e-8 for seg,margin in self.source)

    def clip(self,pocket):
        if isinstance(pocket[0],tuple):
            pocket=[c.Line(a,b) for a,b in zip(pocket,pocket[1:]+pocket[:1])]
        pb=(min(c.bounds(s)[0] for s in pocket),min(c.bounds(s)[1] for s in pocket),
            max(c.bounds(s)[2] for s in pocket),max(c.bounds(s)[3] for s in pocket))
        nearby=[e.segment for e in self.edges if c.overlaps(pb,e.bbox,1e-7)]
        if not nearby:
            return [pocket] if self.inside(pocket[0].point(.5)) else []
        polygon=pocket
        def valid(p):return c.loop_contains(polygon,p) and self.inside(p)
        directed=[];seen=set()
        for s in _split_edges(pocket+nearby):
            mid=s.point(.5);tan=s.tangent(.5);n=c.normal(tan)
            epsilon=2e-6
            left=valid(c.add(mid,c.mul(n,epsilon)))
            right=valid(c.add(mid,c.mul(n,-epsilon)))
            if left==right:continue
            seg=s if left else s.reverse()
            key=_signature(seg)
            if key not in seen:
                seen.add(key);directed.append(seg)
        if not directed:return []
        return _assemble(directed)

    def clip_many(self,pockets):return [self.clip(p) for p in pockets]


# --- Exact tangent fillets --------------------------------------------------

def _offset_support(seg,r):
    if isinstance(seg,c.Line):
        n=c.normal(seg.tangent())
        return c.Line(c.add(seg.start,c.mul(n,r)),c.add(seg.end,c.mul(n,r)))
    offset_radius=seg.radius-(r if seg.sweep>0 else -r)
    if offset_radius<=1e-9:return None
    return (seg.center,offset_radius)


def _support_crossings(a,b):
    if isinstance(a,c.Line) and isinstance(b,c.Line):return c.line_line(a,b,True)
    if isinstance(a,c.Line):return c.line_circle(a,b[0],b[1],True)
    if isinstance(b,c.Line):return c.line_circle(b,a[0],a[1],True)
    return c.circle_circle(a[0],a[1],b[0],b[1])


def _contact(seg,center):
    if isinstance(seg,c.Line):
        u=c.sub(seg.end,seg.start)
        t=c.dot(c.sub(center,seg.start),u)/c.dot(u,u)
        return seg.point(t)
    v=c.sub(center,seg.center)
    if c.length(v)<c.EPS:return None
    return c.add(seg.center,c.mul(c.unit(v),seg.radius))


def _fillet_at(prev,nxt,r):
    """Find fillet tangent to both curves at a CCW convex corner."""
    if r<=0 or not c.near(prev.end,nxt.start,1e-6):return None
    left=_offset_support(prev,r);right=_offset_support(nxt,r)
    if left is None or right is None:return None
    joint=prev.end
    candidates=[]
    for center in _support_crossings(left,right):
        a=_contact(prev,center);b=_contact(nxt,center)
        if a is None or b is None:continue
        t0=c.parameter(prev,a,1e-6);t1=c.parameter(nxt,b,1e-6)
        if t0 is None or t1 is None or not (-1e-8<=t0<=1) or not (0<=t1<=1+1e-8):continue
        va=c.sub(a,center);vb=c.sub(b,center)
        sweep=c.angular_delta(math.atan2(va[1],va[0]),math.atan2(vb[1],vb[0]),1)
        if sweep<=1e-5 or sweep>=math.pi+1e-5:continue
        arc=c.Arc(center,a,b,sweep)
        if c.dot(prev.tangent(t0),arc.tangent(0))<.99998:continue
        if c.dot(nxt.tangent(t1),arc.tangent(1))<.99998:continue
        # A full-radius fillet must trim *into* the arriving/departing edges.
        if t0>1-1e-8 or t1<1e-8:continue
        candidates.append((c.length(c.sub(center,joint)),t0,t1,arc))
    return min(candidates,key=lambda x:x[0])[1:] if candidates else None


def fillet_loop(loop,radius,warnings=None):
    """Fillet convex joints using exact line/arc tangent-circle intersections.

    Input is a closed oriented contour of *analytic* segments. Existing
    tangencies are preserved; CW void contours are left unchanged. A corner
    whose requested fillet is infeasible is retained and reported.
    """
    loop=merge_curves(loop)
    if radius<=1e-9 or len(loop)<2 or c.loop_area(loop)<0:return loop
    n=len(loop)
    choices=[None]*n
    for i in range(n):
        a=loop[i];b=loop[(i+1)%n]
        u=a.tangent(1);v=b.tangent(0)
        turn=math.atan2(c.cross(u,v),c.dot(u,v))
        if turn<=math.radians(2) or turn>=math.pi-1e-7:continue
        result=_fillet_at(a,b,radius)
        if result is None:
            if warnings is not None:warnings.append(i)
            continue
        choices[i]=result
    # Adjacent fillets may consume more than the shared segment.
    for _ in range(n+1):
        conflicts=[]
        for i,seg in enumerate(loop):
            start=choices[(i-1)%n][1] if choices[(i-1)%n] is not None else 0
            end=choices[i][0] if choices[i] is not None else 1
            if start>=end-1e-8:conflicts.append(i)
        if not conflicts:break
        for i in conflicts:
            left=(i-1)%n;right=i
            victim=right if choices[right] is not None else left
            if choices[victim] is not None:
                choices[victim]=None
                if warnings is not None:warnings.append(victim)
    result=[]
    for i,seg in enumerate(loop):
        lo=choices[(i-1)%n][1] if choices[(i-1)%n] else 0
        hi=choices[i][0] if choices[i] else 1
        if hi-lo>1e-8:result.append(seg.section(lo,hi))
        if choices[i] is not None:result.append(choices[i][2])
    if not c.close_loop(result,2e-5):raise ValueError('Fillet contour failed to close')
    return merge_curves(result)
