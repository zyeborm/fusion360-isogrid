"""Experimental local convex fillet/short-edge collapse.

Avoid full disk-opening Boolean for impossible slivers and try a direct
radius bridge over a microscopic edge. Fall back to the original method when
local construction cannot be proven valid.
"""
import math
import exact_clipper as e
import curves2d as c

def _convex_polygon(loop):
    # Only use the cheap area/perimeter disk bound on smoothly convex loops.
    # The offset may bend; sample the tangent along each segment, and reject
    # concave vertices or interior inflections from this conservative test.
    tans=[]
    for seg in loop:
        tans.extend(seg.tangent(t) for t in (0.,.25,.5,.75,1.))
    if len(tans)<3:return False
    turns=[math.atan2(c.cross(a,b),c.dot(a,b)) for a,b in zip(tans,tans[1:]+tans[:1])]
    return all(v>=-1e-5 for v in turns) and sum(turns)>5.

def _cheap_impossible(loop,r):
    if not _convex_polygon(loop):return False
    area=c.loop_area(loop)
    if area<=0:return True
    perimeter=0.
    for seg in loop:
        if isinstance(seg,c.Line):perimeter+=c.length(c.sub(seg.end,seg.start))
        elif isinstance(seg,c.Arc):perimeter+=seg.radius*abs(seg.sweep)
        else:
            flat=c._flatten(seg,5e-4,10)
            perimeter+=sum(c.length(c.sub(a[1],b[1])) for a,b in zip(flat,flat[1:]))
    return 2*area/perimeter < r-1e-4

def _bridge_fillet(prev,nxt,r):
    """Circle tangent to both edge supports, even across a short edge."""
    a=e._offset_support(prev,r);b=e._offset_support(nxt,r)
    if a is None or b is None:return None
    candidates=[]
    for center in e._support_crossings(a,b):
        p=e._contact(prev,center);q=e._contact(nxt,center)
        if p is None or q is None:continue
        tp=c.parameter(prev,p,1e-5);tq=c.parameter(nxt,q,1e-5)
        if tp is None or tq is None or not(0<=tp<=1 and 0<=tq<=1):continue
        va=c.sub(p,center);vb=c.sub(q,center)
        sweep=c.angular_delta(math.atan2(va[1],va[0]),math.atan2(vb[1],vb[0]),1)
        if sweep<=1e-5 or sweep>=math.pi+1e-4:continue
        arc=c.Arc(center,p,q,sweep)
        if c.dot(prev.tangent(tp),arc.tangent(0))<.99998:continue
        if c.dot(nxt.tangent(tq),arc.tangent(1))<.99998:continue
        candidates.append((c.length(c.sub(prev.end,center)),tp,tq,arc))
    return min(candidates,key=lambda x:x[0])[1:] if candidates else None

def _collapse_short_edge(loop,r):
    if not 3<=len(loop)<=6:return None
    lengths=[c.length(c.sub(seg.start,seg.end)) for seg in loop]
    candidates=[i for i,seg in enumerate(loop) if isinstance(seg,c.Line) and lengths[i]<2*r]
    # The shortcut assumes a convex clipped pocket; a concave source offset
    # can require multiple disconnected disk-centre regions. Let the general
    # evaluator handle that case rather than bridging across excluded material.
    if any(isinstance(seg,c.Offset) for seg in loop) and not _convex_polygon(loop):
        return None
    for omit in sorted(candidates,key=lambda i:lengths[i]):
        remaining=loop[:omit]+loop[omit+1:]
        n=len(remaining)
        choices=[]
        for i,a in enumerate(remaining):
            b=remaining[(i+1)%n]
            choice=_bridge_fillet(a,b,r)
            if choice is None:break
            choices.append(choice)
        if len(choices)!=n:continue
        out=[]
        for i,seg in enumerate(remaining):
            lo=choices[(i-1)%n][1];hi=choices[i][0]
            if hi-lo<=1e-8:break
            out.append(seg.section(lo,hi));out.append(choices[i][2])
        else:
            if not c.close_loop(out,2e-5):continue
            if c.loop_area(out)>c.loop_area(loop)+1e-6:continue
            # Check the entire emitted contour follows the original cut.
            if all(c.loop_contains(loop,seg.point(t)) or
                   min(c.point_distance(src,seg.point(t)) for src in loop)<2e-5
                   for seg in out for t in (.1,.5,.9)):
                return e.merge_curves(out)
    return None

SAVED=e.rounded_pocket

def rounded_pocket(loop,radius,warnings=None):
    issues=[]
    filleted=e.fillet_loop(loop,radius,issues)
    if not issues:return filleted
    if _cheap_impossible(loop,radius):
        if warnings is not None:warnings.extend(issues)
        return filleted
    local=_collapse_short_edge(loop,radius)
    if local is not None:return local
    repaired=e._round_by_opening(loop,radius)
    if repaired is not None:return repaired
    if warnings is not None:warnings.extend(issues)
    return filleted
