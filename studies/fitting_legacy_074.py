"""Bounded multi-start differential evolution for the existing 2D geometry engine.

All trial layouts are scored by calling geometry.make_pockets, the same routine
used to generate the final Fusion sketch. Fusion APIs are never called here.
Lengths are Fusion database centimetres, angles in degrees.
"""
from dataclasses import dataclass
import math
import random
import geometry
import curves2d as curves
import exact_clipper as exact


@dataclass
class Fit:
    pitch: float
    dx: float
    dy: float
    rotation: float
    area: float
    slivers: int
    pocket_count: int
    partials: int
    symmetry: float
    edge_quality: float
    area_fraction: float
    nominal_closeness: float
    score: float = 0.0
    label: str = ''
    phase_u: float = 0.0
    phase_v: float = 0.0


def _centroid(poly):
    a2=0.0; sx=sy=0.0
    for p,q in zip(poly, poly[1:]+poly[:1]):
        cr=geometry.cross(p,q)
        a2+=cr
        sx+=(p[0]+q[0])*cr
        sy+=(p[1]+q[1])*cr
    if abs(a2)<1e-12: return (sum(p[0] for p in poly)/len(poly),
                              sum(p[1] for p in poly)/len(poly))
    return sx/(3*a2),sy/(3*a2)


def _metrics(shapes,pitch,rib,corner,region_box,area_limit,nominal,pmin,pmax):
    # This is the true geometry with the corner rounds already clipped/applied;
    # native circles use their exact analytic area.
    triangle=[(0,0),(pitch,0),(pitch/2,geometry.SQRT3*pitch/2)]
    full_polygon=geometry.rounded_triangle(triangle,rib/2,0)
    full_curves=[curves.Line(a,b) for a,b in zip(full_polygon,full_polygon[1:]+full_polygon[:1])]
    full=abs(curves.loop_area(exact.fillet_loop(full_curves,corner)))
    total=0.0; pocket_count=0; small=0; partial=0
    sumx=sumy=0.0
    for shape in shapes:
        if shape.circle:
            center,r=shape.circle
            value=math.pi*r*r
            xc,yc=center
        else:
            # Exact circular-sector integrals for the new curve engine;
            # polygons remain a view-only representation for these shapes.
            if shape.curve_loops:
                value=sum(curves.loop_area(loop) for loop in shape.curve_loops)
                if value>1e-10:
                    mx=sum(curves.loop_area(loop)*curves.loop_centroid(loop)[0]
                           for loop in shape.curve_loops)
                    my=sum(curves.loop_area(loop)*curves.loop_centroid(loop)[1]
                           for loop in shape.curve_loops)
                    xc,yc=mx/value,my/value
            else:
                value=sum(geometry.area(poly) for poly in shape.loops)
            if value<=1e-10: continue
            pocket_count+=1
            # A cell can fragment into multiple pieces, so count each partial.
            if value<.96*full:partial+=1
            if value<.35*full:small+=1
            if not shape.curve_loops:
                xc=sum(geometry.area(poly)*_centroid(poly)[0] for poly in shape.loops)/value
                yc=sum(geometry.area(poly)*_centroid(poly)[1] for poly in shape.loops)/value
        total+=value
        sumx+=value*xc;sumy+=value*yc
    if total<=1e-9: return None
    x0,y0,x1,y1=region_box
    centre=((x0+x1)/2,(y0+y1)/2)
    # A first-order symmetry metric; layout balanced about the face-box centre.
    # Normalisation avoids penalising a wide rectangle more than a small one.
    displacement=math.hypot((sumx/total-centre[0])/max(x1-x0,1e-6),
                            (sumy/total-centre[1])/max(y1-y0,1e-6))
    symmetry=max(0.0,1.0-4*displacement)
    edge_quality=max(0.0,1.0-(partial+2*small)/max(1,pocket_count))
    area_fraction=max(0.0,min(1.0,total/max(area_limit,1e-9)))
    preferred=max((pmax-pmin)/2,nominal*.1,1e-6)
    nominal_closeness=max(0.0,1.0-abs(pitch-nominal)/preferred)
    return total,pocket_count,small,partial,symmetry,edge_quality,area_fraction,nominal_closeness


def _fitness(fit,objective):
    if objective=='Maximum removal':
        return fit.area_fraction
    if objective=='Clean edges':
        return .70*fit.edge_quality+.30*fit.area_fraction
    if objective=='Best symmetry':
        return .66*fit.symmetry+.34*fit.area_fraction
    if objective=='Closest to nominal':
        return .76*fit.nominal_closeness+.24*fit.area_fraction
    raise ValueError('Unknown fit objective.')


def _distinct(candidate,existing):
    for old in existing:
        # Compare actual phase in face-local coordinates modulo the lattice;
        # pitch and rotation differences can make layouts quite different.
        pdiff=abs(candidate.pitch-old.pitch)/max(old.pitch,1e-6)
        adiff=abs((candidate.rotation-old.rotation+30)%60-30)
        du=abs(candidate.phase_u-old.phase_u)
        dv=abs(candidate.phase_v-old.phase_v)
        du=min(du,1-du)
        dv=min(dv,1-dv)
        if pdiff<.045 and adiff<4 and du<.22 and dv<.22:
            return False
    return True


def find_fits(regions, settings, base_origin=None, anchor='vertex', rotation=None,
              pitch_min=None, pitch_max=None, allow_rotation=False,
              evaluations=480, max_cells=1600, progress=None, seed=73021,
              prepared=None):
    """Return 4–8 alternative fits, with independently optimised objectives.

    `progress(done,total)` is called at the start and periodically during the
    search, and may raise to cancel. All intermediate evaluations use exactly
    the same geometry.make_pockets as the final extrusion.
    """
    s=settings
    nominal=s['pitch']
    pmin=float(pitch_min if pitch_min is not None else nominal*.75)
    pmax=float(pitch_max if pitch_max is not None else nominal*1.25)
    if pmin<=0 or pmin>=pmax:
        raise ValueError('Auto Fit minimum pitch must be smaller than maximum pitch.')
    if pmax<=geometry.SQRT3*s['rib']+2*geometry.SQRT3*s['corner']:
        raise ValueError('Auto Fit pitch range is incompatible with the rib width and corner radius.')
    if not 80<=evaluations<=2000:
        raise ValueError('Fit trials must be between 80 and 2000.')
    base_rotation=rotation if rotation is not None else math.degrees(s.get('angle',0.0))
    bx=geometry.face_bounds(regions)
    # Face geometry is invariant under all search dimensions; build masks,
    # margins, and prepared spatial lookups once per entire optimiser run.
    # Even when the user requests an *untrimmed output sketch*, fit quality
    # must be scored within the actual face and its voids. The fit evaluator
    # uses the same geometry engine in its trimmed mode; the selected layout
    # is subsequently drawn/generated using the user's trim choice.
    if prepared is None:
        prepared=geometry.PreparedGeometry(regions,s['perimeter'],s['holeclear'],
                                           backend=s.get('backend','auto'))
    # The mask may cover less than the selected face; a conservative area cap
    # is sufficient because it is constant across candidates.
    region_area=min(sum(curves.loop_area(loop) for loop in reg.curve_loops)
                    if reg.curve_loops else sum(geometry.area(poly) for poly,_ in reg.loops)
                    for reg in regions)
    objectives=('Maximum removal','Clean edges','Best symmetry','Closest to nominal')
    population_size=12
    variables=4 if allow_rotation else 3
    rng=random.Random(seed)
    trials=0
    trial_cache={}
    every=[]
    leaders={}
    if progress:progress(0,evaluations)

    def trial(vec):
        nonlocal trials
        pitch=max(pmin,min(pmax,vec[0]))
        u=vec[1]%1.0;v=vec[2]%1.0
        delta=((vec[3]+30)%60-30) if allow_rotation else 0.0
        rot=base_rotation+delta
        angle=math.radians(rot)
        h=geometry.SQRT3*pitch/2
        px=pitch*(u+.5*v);py=h*v
        dx=s['dx']+math.cos(angle)*px-math.sin(angle)*py
        dy=s['dy']+math.sin(angle)*px+math.cos(angle)*py
        key=(round(pitch,8),round(u,7),round(v,7),round(delta,6))
        fit=trial_cache.get(key,'uncached')
        if fit=='uncached':
            fit=None
            if pitch>geometry.SQRT3*s['rib']+2*geometry.SQRT3*s['corner']:
                try:
                    cuts=geometry.make_pockets(
                        regions,pitch,s['rib'],s['perimeter'],s['holeclear'],
                        dx,dy,rot,s['corner'],s['minfraction']/100,
                        max_cells=max_cells,vertex_hole_diameter=s['nodehole'],
                        base_origin=base_origin,anchor=anchor,prepared=prepared,
                        trim_boundary=True)
                    metrics=_metrics(cuts,pitch,s['rib'],s['corner'],bx,
                                     region_area,nominal,pmin,pmax)
                    if metrics:
                        area,pockets,slivers,partials,symmetry,edge,frac,closeness=metrics
                        fit=Fit(pitch,dx,dy,rot,area,slivers,pockets,
                                partials,symmetry,edge,frac,closeness,
                                phase_u=u,phase_v=v)
                        every.append(fit)
                except ValueError:
                    # Invalid geometric layouts are simply infeasible points
                    # in the optimisation domain.
                    pass
            trial_cache[key]=fit
        trials+=1
        if progress and (trials%10==0 or trials==evaluations):
            progress(trials,evaluations)
        return fit

    # Fixed total budget, split evenly across independent optimisations.
    budgets=[evaluations//4 + (i<evaluations%4) for i in range(4)]
    for oi,objective in enumerate(objectives):
        count=budgets[oi]
        def random_vec():
            v=[rng.uniform(pmin,pmax),rng.random(),rng.random()]
            if allow_rotation:v.append(rng.uniform(-30,30))
            return v
        pop=[random_vec() for _ in range(population_size)]
        # Include current manual phase, and the requested nominal pitch, when
        # inside the limits. This guarantees a familiar baseline in the pool.
        pop[0]=[max(pmin,min(pmax,nominal)),0.0,0.0]+([0.0] if allow_rotation else [])
        fitted=[trial(x) for x in pop]
        best=None
        for item in fitted:
            if item and (best is None or _fitness(item,objective)>_fitness(best,objective)):
                best=item
        for _ in range(count-population_size):
            i=rng.randrange(population_size)
            inds=rng.sample([j for j in range(population_size) if j!=i],3)
            a,b,c=(pop[j] for j in inds)
            F=.55+.35*rng.random()
            mutated=[a[j]+F*(b[j]-c[j]) for j in range(variables)]
            mutated[0]=max(pmin,min(pmax,mutated[0]))
            for j in (1,2):mutated[j]%=1.0
            if allow_rotation:mutated[3]=((mutated[3]+30)%60)-30
            forced=rng.randrange(variables)
            proposed=[mutated[j] if j==forced or rng.random()<.80 else pop[i][j]
                      for j in range(variables)]
            challenger=trial(proposed)
            incumbent=fitted[i]
            if challenger and (incumbent is None or
                               _fitness(challenger,objective)>=_fitness(incumbent,objective)):
                pop[i]=proposed;fitted[i]=challenger
            if challenger and (best is None or _fitness(challenger,objective)>_fitness(best,objective)):
                best=challenger
        leaders[objective]=best
    if not every:
        raise ValueError('Auto Fit found no valid layouts. Raise the minimum pitch or reduce margins.')

    answer=[]
    # Present objective-specific solutions first, taking the best *distinct*
    # solution for each goal, so the drop-down contains actual alternatives.
    for name in objectives:
        ranked=sorted(every,key=lambda item:_fitness(item,name),reverse=True)
        selected=next((item for item in ranked if _distinct(item,answer)),None)
        if selected:
            selected.label=name
            selected.score=_fitness(selected,name)
            answer.append(selected)
    # Enrich with up to four high-area but significantly different phases/pitches.
    for item in sorted(every,key=lambda f:f.area,reverse=True):
        if len(answer)>=8:break
        if _distinct(item,answer):
            item.label='Alternative fit'
            item.score=item.area_fraction
            answer.append(item)
    if progress:progress(evaluations,evaluations)
    return answer
