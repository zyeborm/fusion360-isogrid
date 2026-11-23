"""Prepare self-intersecting curve offsets while retaining parametric spans.

A source boundary is walked in its original direction (permitted side on
left). An inward parallel can self-intersect and produce inward-turning lobes
that are closer to the original curve than the requested clearance.

Find those crossings once, split at their *curve parameters*, and retain only
sections whose source clearance and original inside/outside classification are
valid. The split sections are still the original Offset geometry, not chords.

For now this deliberately accepts smooth, single-segment closed loops. Other
boundary topologies remain with the original prepared-curve method.
"""
import math
from dataclasses import dataclass
import curves2d as c
import geometry as g
import exact_clipper as exact


@dataclass(frozen=True)
class OffsetInterval:
    """Exact parameter trim of the original evaluated offset.

    Rebuilding an Offset from base.section() changes its finite-difference
    tangent evaluation at the trim endpoint (a few micrometres on sharp NURBS
    joins). This wrapper preserves a single original parameterisation and
    therefore agrees exactly at every crossing shared by adjacent spans.
    """
    source: c.Offset
    u0: float
    u1: float

    @property
    def start(self):return self.point(0.)
    @property
    def end(self):return self.point(1.)
    @property
    def middle(self):return self.point(.5)
    def point(self,t):return self.source.point(self.u0+(self.u1-self.u0)*t)
    def tangent(self,t=0.):
        v=self.source.tangent(self.u0+(self.u1-self.u0)*t)
        return v if self.u1>=self.u0 else c.mul(v,-1.)
    def reverse(self):return OffsetInterval(self.source,self.u1,self.u0)
    def section(self,t0,t1):
        d=self.u1-self.u0
        return OffsetInterval(self.source,self.u0+d*t0,self.u0+d*t1)


def _derivative(seg,t):
    dt=1e-5
    lo=max(0.,t-dt);hi=min(1.,t+dt)
    return c.mul(c.sub(seg.point(hi),seg.point(lo)),1./(hi-lo))


def _refine_crossing(seg,t,u):
    """Refine two crossings of the same curve, not just crossing chords."""
    for _ in range(12):
        p=seg.point(t);q=seg.point(u)
        f=c.sub(p,q)
        if c.length(f)<2e-8:return t,u
        a=_derivative(seg,t);b=_derivative(seg,u)
        det=c.cross(a,b)
        if abs(det)<1e-12:return None
        dt=-c.cross(f,b)/det
        du=-c.cross(f,a)/det
        if max(abs(dt),abs(du))>.05:return None
        t+=dt;u+=du
        if not (0<=t<=1 and 0<=u<=1):return None
    if c.near(seg.point(t),seg.point(u),2e-6):return t,u
    return None


def self_crossings(seg,chord_tolerance=2e-4):
    """Return (parameter A, parameter B) for genuine self crossings.

    Chords only provide isolated candidate pairs. The returned parameters are
    refined on the actual analytic/parametric offset curve.
    """
    path=c._flatten(seg,chord_tolerance,15)
    pieces=list(zip(path,path[1:]))
    boxes=[g.bounds([a[1],b[1]]) for a,b in pieces]
    crosses=[]
    n=len(pieces)
    for i,((t0,p0),(t1,p1)) in enumerate(pieces):
        for j in range(i+2,n):
            if i==0 and j==n-1:continue
            if not g.boxes_overlap(boxes[i],boxes[j],1e-10):continue
            (u0,q0),(u1,q1)=pieces[j]
            for f,h in g.intersections(p0,p1,q0,q1):
                t=t0+(t1-t0)*f
                u=u0+(u1-u0)*h
                if min(abs(t-u),1.-abs(t-u))<1e-4:continue
                precise=_refine_crossing(seg,t,u)
                if precise is None:continue
                a,b=sorted(precise)
                if not any(abs(a-x)<2e-6 and abs(b-y)<2e-6 for x,y in crosses):
                    crosses.append((a,b))
    return sorted(crosses)


def _valid_interval(offset,base,clearance,is_outer,a,b):
    # All three probes must agree. A disagreement indicates an unlocated cusp
    # or tangency and should be handled by the general exact geometry engine.
    answers=[]
    for t in (.2,.5,.8):
        p=offset.point(a+(b-a)*t)
        interior=c.loop_contains([base],p)
        valid_side=interior if is_outer else not interior
        distance=c.point_distance(base,p)
        answers.append(valid_side and distance>=clearance-1e-5)
    if not (all(answers) or not any(answers)):
        raise ValueError('Unresolved offset cusp or tangent contact')
    return answers[0]


def clean_closed_offset(base,clearance,is_outer):
    """Clean the parallel of one smooth closed source curve.

    Returns oriented closed loops composed of original parametric Offset spans.
    Empty output means the inward erosion has eliminated the permitted region.
    """
    if clearance<=0:
        return [[base]]
    if not c.near(base.start,base.end,1e-7) or \
       c.dot(base.tangent(0.),base.tangent(1.))<.9999:
        raise ValueError('Only smooth closed source curves are supported')
    if not isinstance(base,(c.Ellipse,c.Nurbs,c.Arc)):
        raise ValueError('Unsupported source curve')
    offset=c.Offset(base,clearance)
    hits=self_crossings(offset)
    cuts=sorted([0.,1.]+[v for ab in hits for v in ab])
    unique=[cuts[0]]
    for value in cuts[1:]:
        if value-unique[-1]>2e-8:unique.append(value)
    retained=[]
    for a,b in zip(unique,unique[1:]):
        if b-a<2e-8:continue
        if _valid_interval(offset,base,clearance,is_outer,a,b):
            retained.append(OffsetInterval(offset,a,b))
    if not retained:return []
    if len(retained)==1 and c.near(retained[0].start,retained[0].end,2e-5):
        return [retained]
    loops=exact._assemble(retained)
    if not all(c.close_loop(loop,2e-5) for loop in loops):
        raise ValueError('Clean offset did not form closed loops')
    # The result must have the same orientation as the original source loop.
    # Multiple disjoint loops are allowed (e.g. a neck eroded into two lobes).
    if any((c.loop_area(loop)>0)!=is_outer for loop in loops):
        raise ValueError('Clean offset loop orientation mismatch')
    return loops


def clean_open_offset(base,clearance):
    """Delete self-crossing lobes from the offset of one open source curve.

    A lobe is invalid when another part of the source is closer than the
    requested clearance. Its two crossing parameters coincide geometrically,
    so deleting the interval joins the surviving parts directly. Return an
    ordered list of parametric Offset pieces, ready for further trimming.
    """
    if c.near(base.start,base.end,1e-7):
        raise ValueError('Use clean_closed_offset for closed curves')
    offset=c.Offset(base,clearance)
    hits=self_crossings(offset)
    if not hits:
        # A cusp need not produce a crossing within a *trimmed* source arc.
        # Flag that case rather than returning an offset known to violate the
        # requested clearance.
        if any(c.point_distance(base,offset.point(i/16))<clearance-1e-5
               for i in range(17)):
            raise ValueError('Offset has an unresolved cusp without a crossing')
        return [offset]
    cuts=sorted([0.,1.]+[v for ab in hits for v in ab])
    unique=[cuts[0]]
    for value in cuts[1:]:
        if value-unique[-1]>2e-8:unique.append(value)
    pieces=[]
    for a,b in zip(unique,unique[1:]):
        if b-a<2e-8:continue
        samples=[c.point_distance(base,offset.point(a+(b-a)*f))>=clearance-1e-5
                 for f in (.2,.5,.8)]
        if not(all(samples) or not any(samples)):
            raise ValueError('Unresolved open offset cusp or contact')
        if all(samples):pieces.append(OffsetInterval(offset,a,b))
    if not pieces:return []
    # Trimming a loop makes adjacent retained sections meet at precisely the
    # same crossing point. For general paths, topology must remain continuous.
    for a,b in zip(pieces,pieces[1:]):
        if not c.near(a.end,b.start,2e-5):
            raise ValueError('Offset cleanup produced disconnected paths')
    return pieces
