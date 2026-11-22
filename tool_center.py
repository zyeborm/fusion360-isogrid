"""Shared tool-centre pocket construction, independent of the Fusion API.

Erode the source face once, intersect with each triangle's analytic erosion,
and dilate the resulting centre region by the corner radius. The finished
parametric contours are shared by Fusion preview and extrusion.
"""
import math
import geometry as g
import curves2d as c
from shared_boundary import Boundary, sampled_signed_area


def inset_triangle(tri,r):
    if g.area(tri)<0:tri=list(reversed(tri))
    if r<=0:return tri
    perimeter=sum(c.length(c.sub(tri[(i+1)%3],tri[i])) for i in range(3))
    if 2*g.area(tri)/perimeter<=r+1e-9:return []
    return g.offset_valid_side(tri,r)


def outward(seg,r):
    if isinstance(seg,c.Line):
        n=c.mul(c.normal(seg.tangent()),-r)
        return c.Line(c.add(seg.start,n),c.add(seg.end,n))
    if isinstance(seg,c.Arc):
        rad=seg.radius + (r if seg.sweep>0 else -r)
        if rad<=1e-8:return None
        k=rad/seg.radius
        return c.Arc(seg.center,c.add(seg.center,c.mul(c.sub(seg.start,seg.center),k)),
                     c.add(seg.center,c.mul(c.sub(seg.end,seg.center),k)),seg.sweep)
    # A signed offset composed with another parallel is mathematically a
    # single offset of the source on regular non-cusped spans.
    if isinstance(seg,c.Offset):return c.Offset(seg.base,seg.distance-r)
    # Exact trim-parametric offset from the loop-cleanup experiment.
    from offset_cleanup import OffsetInterval
    if isinstance(seg,OffsetInterval):
        return OffsetInterval(c.Offset(seg.source.base,seg.source.distance-r),seg.u0,seg.u1)
    return c.Offset(seg,-r)


def expand_center_loop(loop,r):
    """Dilate parametric centre contours by r, with local junction handling.

    Convex joins are circular arcs. Concave joins are intersections of the
    two outward-offset supports, trimmed at that crossing. This constructs
    the finished region directly, never performing a second polygon Boolean.
    A degenerate overlapping offset fails closed as an unsupported contour.
    """
    if not loop:return None
    if r<=0:return loop
    offsets=[outward(seg,r) for seg in loop]
    if any(s is None for s in offsets):return None
    n=len(loop);start=[0.]*n;end=[1.]*n;joins=[None]*n
    for i,seg in enumerate(loop):
        nxt=loop[(i+1)%n]
        ti,tj=seg.tangent(1),nxt.tangent(0)
        turn=math.atan2(c.cross(ti,tj),c.dot(ti,tj))
        a=offsets[i];b=offsets[(i+1)%n]
        if turn>1e-5:
            joins[i]=c.Arc(seg.end,a.end,b.start,turn)
        elif turn < -1e-5:
            points=(c.line_line(a,b,True) if isinstance(a,c.Line) and isinstance(b,c.Line)
                    else c.intersections(a,b))
            contacts=[]
            for p in points:
                u=c.parameter(a,p,5e-5);v=c.parameter(b,p,5e-5)
                if u is not None and v is not None:
                    contacts.append((c.length(c.sub(p,seg.end)),u,v))
            if not contacts:return None
            _,u,v=min(contacts)
            end[i]=u;start[(i+1)%n]=v
        elif not c.near(a.end,b.start,3e-5):
            return None
    out=[]
    for i,seg in enumerate(offsets):
        if end[i]-start[i]<1e-7:return None
        out.append(seg.section(start[i],end[i]))
        if joins[i] is not None:out.append(joins[i])
    if not c.close_loop(out,3e-5):return None
    return out


class ToolCentre:
    def __init__(self,regions,perimeter,void_clearance,radius):
        if radius<=0:raise ValueError('Radius must be > 0 for the tool-centre branch')
        self.radius=radius
        # Plain polygon regions share the same analytic line-boundary path.
        # Convert once, rather than falling back to Python polygon Booleans.
        native_regions=[]
        for region in regions:
            if region.curve_loops is not None:
                native_regions.append(region)
            else:
                native_regions.append(g.Region(list(region.loops),
                    curve_loops=[g.polyline_curves(poly) for poly,_ in region.loops]))
        self.boundary=Boundary(native_regions,perimeter+radius,void_clearance+radius,
                               allow_merged_voids=True,sampled_area=True)
        self.infeasible=0;self.nonconvex=0;self.clips=0
        self._vertex_prepared=None
        self._regions=regions
        self._perimeter=perimeter
        self._void_clearance=void_clearance

    def vertex_circle_fits(self,center,radius):
        if self._vertex_prepared is None:
            self._vertex_prepared=g.PreparedGeometry(
                self._regions,self._perimeter,self._void_clearance)
        return self._vertex_prepared.circle_fits(center,radius)
    def pocket(self,tri):
        center_tri=inset_triangle(tri,self.radius)
        if len(center_tri)!=3 or g.area(center_tri)<=1e-10:
            self.infeasible+=1;return []
        centres=self.boundary.clip(center_tri)
        self.clips+=1
        out=[]
        for loop in centres:
            expanded=expand_center_loop(loop,self.radius)
            if expanded is None:
                self.nonconvex+=1;continue
            if abs(sampled_signed_area(expanded))>1e-10:out.append(expanded)
        return out


def make_toolcentre_pockets(regions,pitch,rib,perimeter,void_clearance,
        offset_x,offset_y,rotation,corner_radius,min_area_fraction=.05,
        max_cells=1600,vertex_hole_diameter=0,base_origin=None,anchor='vertex',
        check_cancel=None,prepared=None):
    if corner_radius<=0:raise ValueError('Positive corner radius required')
    if not regions:raise ValueError('No selected area.')
    box=g.face_bounds(regions)
    for region in regions[1:]:
        x0,y0,x1,y1=g.face_bounds([region])
        box=(max(box[0],x0),max(box[1],y0),min(box[2],x1),min(box[3],y1))
    if box[0]>=box[2] or box[1]>=box[3]:return [],prepared
    origin=g.lattice_origin(box,pitch,rotation,offset_x,offset_y,base_origin,anchor)
    pockets=list(g.lattice_pockets(box,pitch,rib,origin,rotation,0,max_cells))
    engine=prepared or ToolCentre(regions,perimeter,void_clearance,corner_radius)
    if abs(engine.radius-corner_radius)>1e-12:
        raise ValueError('Prepared tool-centre radius differs from requested radius')
    engine.infeasible=engine.nonconvex=engine.clips=0
    min_area=g.SQRT3/4*(pitch-g.SQRT3*rib)**2*min_area_fraction
    result=[]
    for tri in pockets:
        if check_cancel:check_cancel()
        raw=engine.pocket(tri)
        outers=[loop for loop in raw if sampled_signed_area(loop)>min_area]
        holes=[loop for loop in raw if sampled_signed_area(loop)<0 and
               any(c.loop_contains(outer,loop[0].start) for outer in outers)]
        finished=outers+holes
        if outers:
            result.append(g.CutShape(tri,[c.sample(loop,.0004) for loop in finished],
                                     curve_loops=finished))
    if vertex_hole_diameter>g.EPS:
        r=vertex_hole_diameter/2
        for center in g.lattice_vertices(box,pitch,origin,rotation):
            if check_cancel:check_cancel()
            if not engine.vertex_circle_fits(center,r):continue
            circle=g.circle_polygon(center,r)
            result.append(g.CutShape(circle,[circle],(center,r)))
    return result,engine
