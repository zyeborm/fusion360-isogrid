"""Pure-Python oriented, exact planar line and circular-arc primitives.

All distances use Fusion's internal centimetres. Arcs retain their centre,
endpoints and *signed* sweep. Sampling is strictly an optional view/diagnostic
operation; predicates, intersections, contour areas and clipping use curves.
"""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
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



@dataclass(frozen=True)
class Ellipse:
    """Trimmed ellipse. Axis vectors include radii; sweep is signed in radians.

    The representation retains the analytic conic, including a full ellipse
    (abs(sweep)==2*pi) and reversed or greater-than-half elliptical arcs.
    """
    center: Pt
    major: Pt
    minor: Pt
    angle: float = 0.
    sweep: float = TAU
    @property
    def start(self):return self.point(0.)
    @property
    def end(self):return self.point(1.)
    @property
    def middle(self):return self.point(.5)
    def point(self,t):
        a=self.angle+self.sweep*t
        return add(self.center,add(mul(self.major,math.cos(a)),mul(self.minor,math.sin(a))))
    def tangent(self,t=0.):
        a=self.angle+self.sweep*t
        v=add(mul(self.major,-math.sin(a)),mul(self.minor,math.cos(a)))
        return mul(unit(v),1 if self.sweep>0 else -1)
    def reverse(self):return Ellipse(self.center,self.major,self.minor,self.angle+self.sweep,-self.sweep)
    def section(self,t0,t1):return Ellipse(self.center,self.major,self.minor,self.angle+self.sweep*t0,self.sweep*(t1-t0))
    @property
    def radius(self):return max(length(self.major),length(self.minor))


def _de_boor(controls,degree,knots,u):
    """Homogeneous de Boor evaluation of a rational B-spline, pure Python."""
    n=len(controls)-1;p=degree
    if u>=knots[n+1]:k=n
    elif u<=knots[p]:k=p
    else:
        lo=p;hi=n+1
        while lo+1<hi:
            mid=(lo+hi)//2
            if u<knots[mid]:hi=mid
            else:lo=mid
        k=lo
    # Work on three fixed homogeneous coordinates. The previous generic
    # list/zip interpolation allocated two intermediate lists per control
    # update, which dominates when solving thousands of spline intersections.
    d=list(controls[k-p:k+1])
    for r in range(1,p+1):
        for j in range(p,r-1,-1):
            left=knots[j+k-p];right=knots[j+1+k-r]
            alpha=(u-left)/(right-left) if right>left else 0.
            a=d[j-1];b=d[j];beta=1.-alpha
            d[j]=(beta*a[0]+alpha*b[0],
                  beta*a[1]+alpha*b[1],
                  beta*a[2]+alpha*b[2])
    return d[p]


@lru_cache(maxsize=2048)
def _homogeneous_controls(controls,weights):
    return tuple((p[0]*w,p[1]*w,w) for p,w in zip(controls,weights))


@dataclass(frozen=True)
class Nurbs:
    """Bounded rational NURBS with preserved knots/weights and trim domain.

    No Autodesk objects are retained, so this is safe for the worker thread.
    """
    controls: tuple
    degree: int
    knots: tuple
    weights: tuple
    u0: float
    u1: float
    periodic: bool = False
    def __post_init__(self):
        n=len(self.controls)
        if not 1<=self.degree<n or len(self.weights)!=n or len(self.knots)!=n+self.degree+1:
            raise ValueError('Invalid NURBS control points, degree or knot vector')
        if any(w<=0 for w in self.weights):raise ValueError('NURBS weights must be positive')
        if not self.knots[self.degree]-1e-9 <= min(self.u0,self.u1) <= max(self.u0,self.u1) <= self.knots[n]+1e-9:
            raise ValueError('NURBS trim exceeds knot domain')
    @property
    def start(self):return self.point(0.)
    @property
    def end(self):return self.point(1.)
    @property
    def middle(self):return self.point(.5)
    def point(self,t):
        u=self.u0+(self.u1-self.u0)*t
        ctrl=_homogeneous_controls(self.controls,self.weights)
        x,y,w=_de_boor(ctrl,self.degree,self.knots,u)
        return (x/w,y/w)
    def tangent(self,t=0.):
        # Cheap finite difference for well-conditioned ordinary trims. Use
        # the analytic derivative only when both evaluations coincide, which
        # occurs for microscopic segments from Boolean intersections.
        a=self.point(max(0.,t-1e-5))
        b=self.point(min(1.,t+1e-5))
        secant=sub(b,a)
        if length(secant)>=EPS:
            return unit(secant)
        # Differentiate the original rational B-spline analytically in its
        # knot domain. Tiny trims (generated by Boolean intersections) can
        # have indistinguishable endpoints, so finite differences in [0,1]
        # are an unreliable way to obtain a tangent.
        u=self.u0+(self.u1-self.u0)*t
        controls=_homogeneous_controls(self.controls,self.weights)
        x,y,w=_de_boor(controls,self.degree,self.knots,u)
        p=self.degree
        U=self.knots
        derivative=[]
        for i in range(len(controls)-1):
            span=U[i+p+1]-U[i+1]
            if span>0:
                derivative.append(tuple(p*(b-a)/span
                    for a,b in zip(controls[i],controls[i+1])))
            else:
                derivative.append((0.,0.,0.))
        dx,dy,dw=_de_boor(derivative,p-1,U[1:-1],u)
        tangent=((dx*w-x*dw)/(w*w),(dy*w-y*dw)/(w*w))
        if self.u1<self.u0:
            tangent=mul(tangent,-1.)
        if length(tangent)>=EPS:
            return unit(tangent)
        # A genuine stationary control-point cusp requires a local secant.
        for dt in (1e-5,1e-3,.1,1.):
            delta=sub(self.point(min(1.,t+dt)),self.point(max(0.,t-dt)))
            if length(delta)>=EPS:return unit(delta)
        raise ValueError('Degenerate NURBS segment: no measurable tangent')
    def reverse(self):return Nurbs(self.controls,self.degree,self.knots,self.weights,self.u1,self.u0,self.periodic)
    def section(self,t0,t1):
        du=self.u1-self.u0
        return Nurbs(self.controls,self.degree,self.knots,self.weights,
                     self.u0+du*t0,self.u0+du*t1,self.periodic)


@dataclass(frozen=True)
class Offset:
    """Signed parallel of a curve (+ is its left normal), kept parametric.

    General spline/ellipse offsets are *not* NURBS or ellipses in general.
    They are only approximated when exported to Fusion sketch entities.
    """
    base: object
    distance: float
    @property
    def start(self):return self.point(0.)
    @property
    def end(self):return self.point(1.)
    @property
    def middle(self):return self.point(.5)
    def point(self,t):return add(self.base.point(t),mul(normal(self.base.tangent(t)),self.distance))
    def tangent(self,t=0.):
        # The derivative of a general offset may vanish at its evolute
        # cusp. Numerically, adjacent evaluations can also coincide near
        # extremely short trims. Use a wider secant before falling back to
        # the base curve's limiting direction at a stationary point.
        for dt in (1e-5, 1e-4, 1e-3, 1e-2, .1, .5, 1.):
            delta=sub(self.point(min(1.,t+dt)),
                      self.point(max(0.,t-dt)))
            if length(delta)>=EPS:
                return unit(delta)
        return self.base.tangent(t)
    def reverse(self):return Offset(self.base.reverse(),-self.distance)
    def section(self,t0,t1):return Offset(self.base.section(t0,t1),self.distance)


@lru_cache(maxsize=2048)
def _flatten(seg,tol=2e-5,max_depth=13):
    """Adaptive chords solely for numerical root isolation and preview."""
    out=[(0.,seg.start)]
    def step(t0,p0,t1,p1,depth):
        tm=(t0+t1)/2;pm=seg.point(tm)
        q0=seg.point((3*t0+t1)/4);q1=seg.point((t0+3*t1)/4)
        mid=mul(add(p0,p1),.5)
        err=max(length(sub(pm,mid)),
                length(sub(q0,add(mul(p0,.75),mul(p1,.25)))),
                length(sub(q1,add(mul(p0,.25),mul(p1,.75)))))
        if err>tol and depth<max_depth:
            step(t0,p0,tm,pm,depth+1);step(tm,pm,t1,p1,depth+1)
        else:out.append((t1,p1))
    step(0.,seg.start,1.,seg.end,0)
    return out


def _derivative(seg,t):
    h=1e-5
    low=max(0.,t-h);high=min(1.,t+h)
    if high==low:return (0.,0.)
    return mul(sub(seg.point(high),seg.point(low)),1/(high-low))


def _closest_parameter(seg,p):
    """Closest parameter with bracketed minimisation around neighbouring chords."""
    points=_flatten(seg,1e-3,10)
    candidates=[]
    for i,((a,pa),(b,pb)) in enumerate(zip(points,points[1:])):
        v=sub(pb,pa);d=dot(v,v)
        q=max(0.,min(1.,dot(sub(p,pa),v)/d)) if d>EPS else 0.
        # The adaptive chord already bounds the curve locally. Use its
        # projected distance for the search, and evaluate the actual spline
        # only in the selected interval. This avoids one (expensive) de Boor
        # evaluation for every chord on every closest-point query.
        projected=add(pa,mul(v,q))
        candidates.append((length(sub(projected,p)),i))
    if not candidates:return 0.
    _,i=min(candidates)
    # Include adjacent chords; a projection near a segment endpoint can have
    # its true smooth-curve minimum in the neighbouring chord.
    lo=points[max(0,i-1)][0];hi=points[min(len(points)-1,i+2)][0]
    phi=(math.sqrt(5)-1)/2
    x=hi-phi*(hi-lo);y=lo+phi*(hi-lo)
    dx=length(sub(seg.point(x),p))
    dy=length(sub(seg.point(y),p))
    for _ in range(45):
        if dx<dy:
            hi=y;y=x;dy=dx;x=hi-phi*(hi-lo)
            dx=length(sub(seg.point(x),p))
        else:
            lo=x;x=y;dx=dy;y=lo+phi*(hi-lo)
            dy=length(sub(seg.point(y),p))
    return (lo+hi)/2


def _numeric_intersections(a,b):
    """Spatially indexed curve intersections with local Newton refinement."""
    fa=_flatten(a,5e-4,12) if not isinstance(a,Line) else [(0.,a.start),(1.,a.end)]
    fb=_flatten(b,5e-4,12) if not isinstance(b,Line) else [(0.,b.start),(1.,b.end)]
    from collections import defaultdict
    # The x-axis bucket index avoids quadratic testing of every pair of
    # chords for two curved segments with overlapping overall bounding boxes.
    xlo=min(p[0] for _,p in fb);xhi=max(p[0] for _,p in fb)
    step=max((xhi-xlo)/max(8,min(128,len(fb)//2)),1e-4)
    def idx(x):return math.floor((x-xlo)/step)
    buckets=defaultdict(list)
    B=[]
    for j,((ua,qa),(ub,qb)) in enumerate(zip(fb,fb[1:])):
        box=(min(qa[0],qb[0]),min(qa[1],qb[1]),max(qa[0],qb[0]),max(qa[1],qb[1]))
        B.append((ua,qa,ub,qb,box))
        for k in range(idx(box[0]-6e-4),idx(box[2]+6e-4)+1):buckets[k].append(j)
    out=[]
    for (ta,pa),(tb,pb) in zip(fa,fa[1:]):
        ax=(min(pa[0],pb[0])-6e-4,min(pa[1],pb[1])-6e-4,
            max(pa[0],pb[0])+6e-4,max(pa[1],pb[1])+6e-4)
        candidates=set()
        for k in range(idx(ax[0]),idx(ax[2])+1):candidates.update(buckets[k])
        for j in candidates:
            ua,qa,ub,qb,bx=B[j]
            if not overlaps(ax,bx):continue
            u=sub(pb,pa);v=sub(qb,qa)
            det=cross(u,v)
            if abs(det)>1e-15:
                w=sub(qa,pa);sa=cross(w,v)/det;sb=cross(w,u)/det
                if not (-.01<=sa<=1.01 and -.01<=sb<=1.01):continue
            else:
                sa=sb=.5
                if point_distance(Line(pa,pb),qa)>6e-4 and point_distance(Line(pa,pb),qb)>6e-4:continue
            t=ta+(tb-ta)*max(0.,min(1.,sa));z=ua+(ub-ua)*max(0.,min(1.,sb))
            for _ in range(18):
                p=a.point(t);q=b.point(z);delta=sub(q,p)
                if length(delta)<2e-9:break
                da=_derivative(a,t);db=_derivative(b,z)
                d=cross(da,db)
                if abs(d)<1e-13:break
                dt=cross(delta,db)/d;dz=cross(delta,da)/d
                nt=t+dt;nz=z+dz
                if not (-.00001<=nt<=1.00001 and -.00001<=nz<=1.00001):break
                t=max(0.,min(1.,nt));z=max(0.,min(1.,nz))
            p=a.point(t);q=b.point(z)
            if length(sub(p,q))<=2e-6 and not any(near(p,v,1e-5) for v in out):out.append(mul(add(p,q),.5))
    # Include shared endpoints only when they are geometrically close.
    ba=bounds(a);bb=bounds(b)
    for p in (a.start,a.end,b.start,b.end):
        pb=(p[0],p[1],p[0],p[1])
        if overlaps(ba,pb,2e-6) and overlaps(bb,pb,2e-6):
            if point_distance(a,p)<2e-7 and point_distance(b,p)<2e-7:
                if not any(near(p,q,1e-5) for q in out):out.append(p)
    return out


def _ellipse_parameter(seg,p,tol=1e-7):
    x=sub(p,seg.center);det=cross(seg.major,seg.minor)
    if abs(det)<1e-14:return None
    co=cross(x,seg.minor)/det;si=cross(seg.major,x)/det
    if abs(co*co+si*si-1)>max(tol,1e-7)*2/max(min(length(seg.major),length(seg.minor)),1e-6):return None
    theta=math.atan2(si,co)
    a=angular_delta(seg.angle,theta,1 if seg.sweep>0 else -1)
    if a>abs(seg.sweep)+tol/max(seg.radius,1e-6):return None
    return max(0.,min(1.,a/abs(seg.sweep)))

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
    if isinstance(seg,Ellipse):return _ellipse_parameter(seg,p,tol)
    if not isinstance(seg,Arc):
        t=_closest_parameter(seg,p)
        return t if length(sub(seg.point(t),p))<=tol else None
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
    if isinstance(seg,Offset):
        b=bounds(seg.base);r=abs(seg.distance)
        return (b[0]-r,b[1]-r,b[2]+r,b[3]+r)
    if isinstance(seg,Nurbs):
        # Rational positive-weight B-splines lie in the convex hull.
        return (min(p[0] for p in seg.controls),min(p[1] for p in seg.controls),
                max(p[0] for p in seg.controls),max(p[1] for p in seg.controls))
    if isinstance(seg,Ellipse):
        pts=[seg.start,seg.end]
        for a,b in ((seg.major[0],seg.minor[0]),(seg.major[1],seg.minor[1])):
            t=math.atan2(b,a)
            for theta in (t,t+math.pi):
                dt=angular_delta(seg.angle,theta,1 if seg.sweep>0 else -1)
                if dt<=abs(seg.sweep)+1e-9:
                    pts.append(seg.point(dt/abs(seg.sweep)))
        return (min(p[0] for p in pts),min(p[1] for p in pts),
                max(p[0] for p in pts),max(p[1] for p in pts))
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


def _line_parametric_intersections(line,seg):
    """Scalar line/parametric-curve root isolation with bisection refinement."""
    v=sub(line.end,line.start);length2=dot(v,v)
    if length2<EPS:return []
    scale=length(v)
    flat=_flatten(seg,5e-4,12)
    values=[cross(v,sub(q,line.start))/scale for _,q in flat]
    out=[]
    for i,((t0,p0),(t1,p1)) in enumerate(zip(flat,flat[1:])):
        y0=values[i];y1=values[i+1]
        # Include near-tangent contacts; refinement checks actual separation.
        if y0*y1>0 and min(abs(y0),abs(y1))>1e-5:continue
        if y0*y1>0:
            t=t0 if abs(y0)<abs(y1) else t1
        else:
            lo=t0;hi=t1;sign=y0
            for _ in range(31):
                t=(lo+hi)/2;value=cross(v,sub(seg.point(t),line.start))/scale
                if abs(value)<2e-9:break
                if sign*value>0:lo=t;sign=value
                else:hi=t
        point=seg.point(t)
        fraction=dot(sub(point,line.start),v)/length2
        if -2e-7<=fraction<=1+2e-7 and abs(cross(v,sub(point,line.start))/scale)<2e-6:
            if not any(near(point,q,1e-5) for q in out):out.append(point)
    return out


def line_ellipse(line,ellipse):
    """Exact line/conic intersection in ellipse-local coordinates."""
    det=cross(ellipse.major,ellipse.minor)
    u=sub(line.start,ellipse.center);v=sub(line.end,line.start)
    x=cross(u,ellipse.minor)/det;y=cross(ellipse.major,u)/det
    dx=cross(v,ellipse.minor)/det;dy=cross(ellipse.major,v)/det
    A=dx*dx+dy*dy
    if A<EPS:return []
    B=2*(x*dx+y*dy);C=x*x+y*y-1
    disc=B*B-4*A*C
    if disc<-1e-11:return []
    return [line.point(t) for t in ((-B-math.sqrt(max(0.,disc)))/(2*A),
                                    (-B+math.sqrt(max(0.,disc)))/(2*A))
            if -1e-9<=t<=1+1e-9]


def intersections(a,b):
    if isinstance(a,Line) and isinstance(b,Line):raw=line_line(a,b)
    elif isinstance(a,Line) and isinstance(b,Arc):raw=line_circle(a,b.center,b.radius)
    elif isinstance(a,Arc) and isinstance(b,Line):raw=line_circle(b,a.center,a.radius)
    elif isinstance(a,Arc) and isinstance(b,Arc):raw=circle_circle(a.center,a.radius,b.center,b.radius)
    elif isinstance(a,Line) and isinstance(b,Ellipse):raw=line_ellipse(a,b)
    elif isinstance(a,Ellipse) and isinstance(b,Line):raw=line_ellipse(b,a)
    elif isinstance(a,Line):return _line_parametric_intersections(a,b)
    elif isinstance(b,Line):return _line_parametric_intersections(b,a)
    else:return _numeric_intersections(a,b)
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
    if isinstance(seg,Ellipse):
        return (cross(seg.major,seg.minor)*seg.sweep+
                cross(seg.center,sub(seg.end,seg.start)))/2
    if not isinstance(seg,Arc):
        return _integrate(seg,lambda p,d:(p[0]*d[1]-p[1]*d[0])/2)
    c=seg.center;s=seg.start;e=seg.end
    return (seg.radius**2*seg.sweep+c[0]*(e[1]-s[1])-c[1]*(e[0]-s[0]))/2


# 8-point Gauss-Legendre integration over 16 subintervals. This is used for
# exact *curve* evaluations of non-circular splines, not polygonal area sums.
_GL8=((.09501250983763744,.1894506104550685),
      (.2816035507792589,.1826034150449236),
      (.4580167776572274,.16915651939500254),
      (.6178762444026438,.14959598881657673),
      (.755404408355003,.12462897125553387),
      (.865631202387832,.09515851168249279),
      (.944575023073233,.06225352393864789),
      (.98940093499165,.027152459411754095))


def _integrate(seg,func):
    total=0.
    for i in range(16):
        mid=(i+.5)/16;half=.5/16
        for x,w in _GL8:
            for sign in (-1,1):
                t=mid+sign*half*x
                total+=half*w*func(seg.point(t),_derivative(seg,t))
    return total


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
        elif isinstance(s,Arc):
            cx,cy=s.center;R=s.radius
            a=s.start_angle;b=a+s.sweep
            ds=math.sin(b)-math.sin(a)
            dc=math.cos(b)-math.cos(a)
            d2=math.sin(2*b)-math.sin(2*a)
            mx+=R/2*(cx**2*ds+2*cx*R*(s.sweep/2+d2/4)+
                     R**2*(ds-(math.sin(b)**3-math.sin(a)**3)/3))
            my+=R/2*(-cy**2*dc+2*cy*R*(s.sweep/2-d2/4)+
                     R**2*(-dc+(math.cos(b)**3-math.cos(a)**3)/3))
        else:
            mx+=_integrate(s,lambda p,d:p[0]*p[0]*d[1]/2)
            my+=_integrate(s,lambda p,d:-p[1]*p[1]*d[0]/2)
    return mx/area,my/area


def point_distance(seg,p):
    if isinstance(seg,Line):
        u=sub(seg.end,seg.start);t=max(0.,min(1.,dot(sub(p,seg.start),u)/dot(u,u)))
        return length(sub(p,seg.point(t)))
    if isinstance(seg,Ellipse) and abs(seg.sweep)>TAU-1e-7:
        # Convex full ellipse: symmetry reduces closest-point search to one
        # quadrant. Include both axis endpoints for centre/axis cases.
        q=sub(p,seg.center)
        a=length(seg.major);b=length(seg.minor)
        X=abs(dot(q,seg.major)/a);Y=abs(dot(q,seg.minor)/b)
        phi=(math.sqrt(5)-1)/2
        lo=0.;hi=math.pi/2
        def d2(t):
            return (a*math.cos(t)-X)**2+(b*math.sin(t)-Y)**2
        u=hi-phi*(hi-lo);v=lo+phi*(hi-lo)
        for _ in range(36):
            if d2(u)<d2(v):hi=v;v=u;u=hi-phi*(hi-lo)
            else:lo=u;u=v;v=lo+phi*(hi-lo)
        return math.sqrt(min(d2(0.),d2(math.pi/2),d2((lo+hi)/2)))
    if not isinstance(seg,Arc):
        t=_closest_parameter(seg,p)
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
        elif isinstance(s,Arc):
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
        else:
            b=bounds(s)
            if py<b[1] or py>b[3] or px>b[2]:continue
            ray=Line((px,py),(b[2]+max(1.,b[2]-px),py))
            for p in intersections(s,ray):
                if p[0]<=px+1e-8:continue
                t=parameter(s,p,2e-5)
                if t is None or t>=1-1e-8:continue
                vy=s.tangent(t)[1]
                if abs(vy)<1e-7:continue
                winding+=1 if vy>0 else -1
    return winding!=0


def sample(loop,chord_tolerance=.001):
    out=[]
    for s in loop:
        if isinstance(s,Line):out.append(s.start);continue
        if chord_tolerance<=0:raise ValueError('Chord tolerance must be positive')
        if not isinstance(s,Arc):
            out.extend(p for _,p in _flatten(s,chord_tolerance,15)[:-1])
            continue
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
    if not isinstance(seg,Arc):
        if near(seg.start,seg.end,1e-8) and dot(seg.tangent(0),seg.tangent(1))>.999:
            return [Offset(seg,-r),Offset(seg.reverse(),-r)]
        a=Offset(seg,-r);b=Offset(seg.reverse(),-r)
        return [a,Arc(seg.end,a.end,b.start,math.pi),
                b,Arc(seg.start,b.end,a.start,math.pi)]
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


def ellipse_quadratics(seg,max_sweep=math.pi/2):
    """Exact rational quadratic Bezier pieces of an elliptical arc.

    Returns (control points, weights). In particular no polyline approximation
    is involved, even after the arc has been clipped or orientation reversed.
    """
    if not isinstance(seg,Ellipse):raise TypeError('Expected Ellipse')
    n=max(1,math.ceil(abs(seg.sweep)/max_sweep))
    result=[]
    for i in range(n):
        a=seg.angle+seg.sweep*i/n;b=seg.angle+seg.sweep*(i+1)/n
        middle=(a+b)/2;weight=math.cos((b-a)/2)
        p0=seg.point(i/n);p2=seg.point((i+1)/n)
        p1=add(seg.center,mul(add(mul(seg.major,math.cos(middle)),
                                  mul(seg.minor,math.sin(middle))),1/weight))
        result.append(((p0,p1,p2),(1.,weight,1.)))
    return result


def approximate_cubic_beziers(seg,tolerance=1e-4,max_depth=12):
    """Tangent-preserving NURBS output for non-NURBS offset curves.

    The original parametric curve is retained by the clipping engine. Only a
    final, non-algebraic offset is converted to C1 cubic Bezier sketch curves.
    The subdivision tolerance is in Fusion centimetres.
    """
    out=[]
    def cubic(ctrl,t):
        u=1-t
        return add(add(mul(ctrl[0],u**3),mul(ctrl[1],3*u*u*t)),
                   add(mul(ctrl[2],3*u*t*t),mul(ctrl[3],t**3)))
    def go(a,b,depth):
        q0=seg.point(a);q3=seg.point(b)
        d0=_derivative(seg,a);d1=_derivative(seg,b)
        ctrl=(q0,add(q0,mul(d0,(b-a)/3)),sub(q3,mul(d1,(b-a)/3)),q3)
        error=max(length(sub(seg.point(a+(b-a)*t),cubic(ctrl,t)))
                  for t in (.2,.4,.6,.8))
        if error>tolerance and depth<max_depth:
            m=(a+b)/2;go(a,m,depth+1);go(m,b,depth+1)
        else:out.append(ctrl)
    go(0.,1.,0)
    return out


def trimmed_nurbs(seg):
    """Exact B-spline subcurve via homogeneous knot insertion (no Fusion API).

    Returns an open, clamped NURBS with domain [min(u0,u1),max(u0,u1)].
    Orientation of the original segment does not affect the sketch curve.
    """
    if not isinstance(seg,Nurbs):raise TypeError('Expected Nurbs')
    p=seg.degree
    u0=min(seg.u0,seg.u1);u1=max(seg.u0,seg.u1)
    if u1-u0<1e-12:raise ValueError('Empty NURBS segment')
    U=list(seg.knots)
    P=[[x*w,y*w,w] for (x,y),w in zip(seg.controls,seg.weights)]
    for u in (u0,u1):
        # Internal knots need multiplicity p to separate their two Bézier
        # spans, while endpoint knots must already have multiplicity p+1.
        domain_left=U[p];domain_right=U[len(P)]
        end=(abs(u-domain_left)<1e-10 or abs(u-domain_right)<1e-10)
        goal=p+1 if end else p
        while sum(abs(k-u)<1e-10 for k in U)<goal:
            n=len(P)-1
            k=max(j for j in range(p,n+1) if U[j]<=u)
            s=sum(abs(x-u)<1e-10 for x in U)
            Q=[None]*(n+2)
            for i in range(0,k-p+1):Q[i]=P[i]
            for i in range(k-s,n+1):Q[i+1]=P[i]
            for i in range(k-p+1,k-s+1):
                denominator=U[i+p]-U[i]
                alpha=(u-U[i])/denominator if denominator else 0
                Q[i]=[(1-alpha)*a+alpha*b for a,b in zip(P[i-1],P[i])]
            assert all(x is not None for x in Q)
            P=Q;U.insert(k+1,u)
    start=0 if abs(u0-U[p])<1e-10 else next(i for i,u in enumerate(U) if abs(u-u0)<1e-10)-1
    end=len(P)-1 if abs(u1-U[len(P)])<1e-10 else next(i for i,u in enumerate(U) if abs(u-u1)<1e-10)-1
    ctrl=P[start:end+1]
    knots=[u0]*(p+1)+[u for u in U if u0+1e-10<u<u1-1e-10]+[u1]*(p+1)
    # Need len(knots) == len(ctrl)+p+1 for clamped NURBS.
    if len(knots)!=len(ctrl)+p+1:
        raise ValueError('Could not trim native NURBS to a clamped knot domain')
    pts=tuple((q[0]/q[2],q[1]/q[2]) for q in ctrl)
    weights=tuple(q[2] for q in ctrl)
    return Nurbs(pts,p,tuple(knots),weights,u0,u1,False)
