"""Pure-Python oriented, exact planar line and circular-arc primitives.

All distances use Fusion's internal centimetres. Arcs retain their centre,
endpoints and *signed* sweep. Sampling is strictly an optional view/diagnostic
operation; predicates, intersections, contour areas and clipping use curves.
"""
from __future__ import annotations
from dataclasses import dataclass
import math

TAU=math.tau
EPS=1e-9
Pt=tuple[float,float]


def add(a,b): return (a[0]+b[0],a[1]+b[1])
def sub(a,b): return (a[0]-b[0],a[1]-b[1])
def mul(a,s): return (a[0]*s,a[1]*s)
def dot(a,b): return a[0]*b[0]+a[1]*b[1]
def cross(a,b): return a[0]*b[1]-a[1]*b[0]
def length(a): return math.hypot(*a)
def normal(a): return (-a[1],a[0])
def unit(a):
    n=length(a)
    if n<EPS: raise ValueError('Zero-length vector')
    return mul(a,1/n)
def near(a,b,tol=2e-7):return length(sub(a,b))<=tol


@dataclass(frozen=True)
class Line:
    start: Pt
    end: Pt
    def point(self,t):return add(self.start,mul(sub(self.end,self.start),t))
    def tangent(self,t=0):return unit(sub(self.end,self.start))
    def reverse(self):return Line(self.end,self.start)
    def section(self,t0,t1):return Line(self.point(t0),self.point(t1))
    @property
    def radius(self):return math.inf


@dataclass(frozen=True)
class Arc:
    center: Pt
    start: Pt
    end: Pt
    sweep: float
    @property
    def radius(self):return length(sub(self.start,self.center))
    @property
    def start_angle(self):return math.atan2(self.start[1]-self.center[1],self.start[0]-self.center[0])
    @property
    def middle(self):return self.point(.5)
    def point(self,t):
        theta=self.start_angle+self.sweep*t
        return (self.center[0]+self.radius*math.cos(theta),self.center[1]+self.radius*math.sin(theta))
    def tangent(self,t=0):
        r=unit(sub(self.point(t),self.center))
        return mul(normal(r),1 if self.sweep>0 else -1)
    def reverse(self):return Arc(self.center,self.end,self.start,-self.sweep)
    def section(self,t0,t1):return Arc(self.center,self.point(t0),self.point(t1),self.sweep*(t1-t0))


def circle(center,radius,ccw=True):
    if radius<=0:raise ValueError('Circle radius must be positive')
    start=add(center,(radius,0))
    return Arc(center,start,start,TAU if ccw else -TAU)


def angular_delta(start,end,sign):
    return (end-start)%TAU if sign>0 else (start-end)%TAU


def parameter(seg,p,tol=1e-7):
    if isinstance(seg,Line):
        u=sub(seg.end,seg.start); d=dot(u,u)
        if d<EPS: return None
        t=dot(sub(p,seg.start),u)/d
        return min(1.,max(0.,t)) if -tol<=t<=1+tol and length(sub(p,seg.point(t)))<=tol else None
    d=length(sub(p,seg.center))
    if abs(d-seg.radius)>tol:return None
    theta=math.atan2(p[1]-seg.center[1],p[0]-seg.center[0])
    sweep=abs(seg.sweep)
    a=angular_delta(seg.start_angle,theta,1 if seg.sweep>0 else -1)
    if a>sweep+tol/max(seg.radius,1e-6):return None
    return max(0.,min(1.,a/sweep))


def bounds(seg):
    if isinstance(seg,Line):
        return (min(seg.start[0],seg.end[0]),min(seg.start[1],seg.end[1]),
                max(seg.start[0],seg.end[0]),max(seg.start[1],seg.end[1]))
    pts=[seg.start,seg.end]
    for k in range(4):
        p=add(seg.center,(seg.radius*math.cos(k*math.pi/2),seg.radius*math.sin(k*math.pi/2)))
        if parameter(seg,p) is not None:pts.append(p)
    return (min(p[0] for p in pts),min(p[1] for p in pts),
            max(p[0] for p in pts),max(p[1] for p in pts))


def overlaps(a,b,margin=0):
    return not (a[2]<b[0]-margin or b[2]<a[0]-margin or a[3]<b[1]-margin or b[3]<a[1]-margin)


def line_line(a,b,infinite=False):
    u=sub(a.end,a.start);v=sub(b.end,b.start);w=sub(b.start,a.start)
    det=cross(u,v)
    if abs(det)<1e-11*max(length(u)*length(v),1e-8):
        if abs(cross(w,u))>1e-8*max(length(u),1):return []
        # Coincident segments: include overlap endpoints for split points.
        if infinite:return []
        return [p for p in (a.start,a.end,b.start,b.end)
                if parameter(a,p) is not None and parameter(b,p) is not None]
    t=cross(w,v)/det;s=cross(w,u)/det
    if infinite or (-1e-9<=t<=1+1e-9 and -1e-9<=s<=1+1e-9):
        return [a.point(t)]
    return []


def line_circle(line,center,radius,infinite=False):
    d=sub(line.end,line.start);f=sub(line.start,center)
    A=dot(d,d);B=2*dot(d,f);C=dot(f,f)-radius**2
    disc=B*B-4*A*C
    if disc < -1e-9*max(B*B,4*A*abs(C),1):return []
    disc=max(0.,disc)
    return [line.point(t) for t in ((-B-math.sqrt(disc))/(2*A),(-B+math.sqrt(disc))/(2*A))
            if infinite or -1e-9<=t<=1+1e-9]


def circle_circle(a,ra,b,rb):
    v=sub(b,a);d=length(v)
    if d<1e-10 or d>ra+rb+1e-8 or d<abs(ra-rb)-1e-8:return []
    x=(ra*ra-rb*rb+d*d)/(2*d)
    h2=ra*ra-x*x
    if h2 < -1e-8:return []
    foot=add(a,mul(v,x/d)); perp=mul(normal(v),math.sqrt(max(0,h2))/d)
    return [add(foot,perp),sub(foot,perp)]


def intersections(a,b):
    if isinstance(a,Line) and isinstance(b,Line):raw=line_line(a,b)
    elif isinstance(a,Line) and isinstance(b,Arc):raw=line_circle(a,b.center,b.radius)
    elif isinstance(a,Arc) and isinstance(b,Line):raw=line_circle(b,a.center,a.radius)
    else:raw=circle_circle(a.center,a.radius,b.center,b.radius)
    out=[]
    for p in raw:
        if parameter(a,p) is not None and parameter(b,p) is not None and not any(near(p,q) for q in out):
            out.append(p)
    # Co-circular overlap: both arcs share circle and potentially endpoint pairs.
    if isinstance(a,Arc) and isinstance(b,Arc) and near(a.center,b.center) and abs(a.radius-b.radius)<1e-8:
        for p in (a.start,a.end,b.start,b.end):
            if parameter(a,p) is not None and parameter(b,p) is not None and not any(near(p,q) for q in out):out.append(p)
    return out


def segment_area(seg):
    if isinstance(seg,Line):return cross(seg.start,seg.end)/2
    c=seg.center;s=seg.start;e=seg.end
    return (seg.radius**2*seg.sweep+c[0]*(e[1]-s[1])-c[1]*(e[0]-s[0]))/2


def loop_area(loop):return sum(segment_area(s) for s in loop)


def loop_centroid(loop):
    """Exact signed area centroid by Green's theorem; no tessellation."""
    area=loop_area(loop)
    if abs(area)<1e-12:raise ValueError('Zero-area curve loop')
    mx=my=0.
    for s in loop:
        if isinstance(s,Line):
            x0,y0=s.start;x1,y1=s.end
            cr=x0*y1-x1*y0
            mx+=(x0+x1)*cr/6
            my+=(y0+y1)*cr/6
        else:
            cx,cy=s.center;R=s.radius
            a=s.start_angle;b=a+s.sweep
            ds=math.sin(b)-math.sin(a)
            dc=math.cos(b)-math.cos(a)
            d2=math.sin(2*b)-math.sin(2*a)
            mx+=R/2*(cx**2*ds+2*cx*R*(s.sweep/2+d2/4)+
                     R**2*(ds-(math.sin(b)**3-math.sin(a)**3)/3))
            my+=R/2*(-cy**2*dc+2*cy*R*(s.sweep/2-d2/4)+
                     R**2*(-dc+(math.cos(b)**3-math.cos(a)**3)/3))
    return mx/area,my/area


def point_distance(seg,p):
    if isinstance(seg,Line):
        u=sub(seg.end,seg.start);t=max(0.,min(1.,dot(sub(p,seg.start),u)/dot(u,u)))
        return length(sub(p,seg.point(t)))
    radial=sub(p,seg.center)
    if length(radial)>EPS:
        proj=add(seg.center,mul(radial,seg.radius/length(radial)))
        if parameter(seg,proj) is not None:return abs(length(radial)-seg.radius)
    return min(length(sub(p,seg.start)),length(sub(p,seg.end)))


def loop_contains(loop,p):
    """Nonzero-winding ray predicate, with true circular arc crossings."""
    px,py=p;winding=0
    for s in loop:
        if isinstance(s,Line):
            ay=s.start[1];by=s.end[1]
            if ay<=py<by or by<=py<ay:
                x=s.start[0]+(py-ay)*(s.end[0]-s.start[0])/(by-ay)
                if x>px:winding+=1 if by>ay else -1
        else:
            dy=py-s.center[1]
            if abs(dy)>=s.radius:continue
            root=math.sqrt(max(0.,s.radius*s.radius-dy*dy))
            for x in (s.center[0]-root,s.center[0]+root):
                if x<=px:continue
                t=parameter(s,(x,py),1e-7)
                if t is None or t>=1-1e-10:continue
                ty=s.tangent(t)[1]
                if abs(ty)<1e-10:continue
                # Arc endpoints follow the same half-open convention as lines.
                if t<=1e-10 and ty<0 and s.start[1]>py+1e-9:continue
                winding+=1 if ty>0 else -1
    return winding!=0


def sample(loop,chord_tolerance=.001):
    out=[]
    for s in loop:
        if isinstance(s,Line):out.append(s.start);continue
        if chord_tolerance<=0:raise ValueError('Chord tolerance must be positive')
        step=2*math.acos(max(-1.,1.-min(chord_tolerance/s.radius,1.999999)))
        n=max(2,min(1000,math.ceil(abs(s.sweep)/step)))
        out.extend(s.point(i/n) for i in range(n))
    return out


def reverse_loop(loop):return [s.reverse() for s in reversed(loop)]


def close_loop(loop,tol=1e-6):
    return bool(loop) and all(near(s.end,loop[(i+1)%len(loop)].start,tol) for i,s in enumerate(loop))


def capsule(seg,r):
    """Exact closed curved boundary of the radius-r tube around a segment."""
    if r<=EPS:return [seg]
    if isinstance(seg,Line):
        t=seg.tangent();n=normal(t)
        ar=add(seg.start,mul(n,-r));br=add(seg.end,mul(n,-r))
        bl=add(seg.end,mul(n,r));al=add(seg.start,mul(n,r))
        return [Line(ar,br),Arc(seg.end,br,bl,math.pi),Line(bl,al),Arc(seg.start,al,ar,math.pi)]
    radius=seg.radius; ccw=seg.sweep>0
    if abs(seg.sweep)>=TAU-1e-8:
        if r>=radius-1e-9:return [circle(seg.center,radius+r)]
        return [circle(seg.center,radius+r),circle(seg.center,radius-r,False)]
    if r>=radius-1e-9:
        # The inner parallel arc collapses, so the true buffer boundary is
        # the outer parallel arc joined by parts of the endpoint circles.
        # These endpoint circles meet beyond the *missing* arc sector.
        joins=circle_circle(seg.start,r,seg.end,r)
        if not joins:
            # A nearly zero-length arc is effectively a single disk.
            return [circle(seg.start,r)]
        join=max(joins,key=lambda p:length(sub(p,seg.middle)))
        outer_start=add(seg.center,mul(sub(seg.start,seg.center),1+r/radius))
        outer_end=add(seg.center,mul(sub(seg.end,seg.center),1+r/radius))
        direction=1 if ccw else -1
        def cap_sweep(center,first,last):
            a=math.atan2(first[1]-center[1],first[0]-center[0])
            b=math.atan2(last[1]-center[1],last[0]-center[0])
            return direction*angular_delta(a,b,direction)
        return [Arc(seg.center,outer_start,outer_end,seg.sweep),
                Arc(seg.end,outer_end,join,cap_sweep(seg.end,outer_end,join)),
                Arc(seg.start,join,outer_start,cap_sweep(seg.start,join,outer_start))]
    def radial(p,factor):return add(seg.center,mul(sub(p,seg.center),factor/radius))
    sign=1 if ccw else -1
    outer_r=radius+sign*r;inner_r=radius-sign*r
    start_right=radial(seg.start,outer_r);end_right=radial(seg.end,outer_r)
    start_left=radial(seg.start,inner_r);end_left=radial(seg.end,inner_r)
    return [Arc(seg.center,start_right,end_right,seg.sweep),
            Arc(seg.end,end_right,end_left,math.pi),
            Arc(seg.center,end_left,start_left,-seg.sweep),
            Arc(seg.start,start_left,start_right,math.pi)]
