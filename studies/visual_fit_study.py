"""Reproducible visual QA for the pure-Python isogrid integer-fit search.

Optional matplotlib is used only to render the study, not by the Fusion add-in.
Run from the repository root: python studies/visual_fit_study.py
The report compares nominal layout, legacy Clean edges, maximum removal,
and the new highest-quality candidate for multiple part geometries/scales.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import csv
import math
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import curves2d as c
import geometry as g
import fitting


def polygon(points):
    return [c.Line(p,q) for p,q in zip(points,points[1:]+points[:1])]


def shape_region(paths):
    return g.Region([(c.sample(segments,.001),outer) for segments,outer in paths],
                    curve_loops=[segments for segments,_ in paths])


def rectangle(w,h):
    return shape_region([(polygon([(0,0),(w,0),(w,h),(0,h)]),True)])


def l_plate():
    return shape_region([(polygon([(0,0),(16,0),(16,3),(10,3),
                                  (10,11),(0,11)]),True)])


def notch_and_hole():
    p=[c.Line((0,0),(20,0)),c.Line((20,0),(20,12)),
       c.Line((20,12),(14,12)),
       c.Arc((10,12),(14,12),(6,12),-math.pi),
       c.Line((6,12),(0,12)),c.Line((0,12),(0,0))]
    return shape_region([(p,True),([c.circle((12,4),1.3,False)],False)])


def taper():
    return shape_region([(polygon([(0,0),(18,0),(14,10),(5,10)]),True)])


def stepped():
    return shape_region([(polygon([(0,0),(20,0),(20,7),(15,7),
                                  (15,12),(8,12),(8,9),(0,9)]),True)])


CASES=[
    ('120 × 40 mm strip',lambda:rectangle(12,4),5.0,2.3,6.5,.18,.11,.13),
    ('40 × 22 mm plate',lambda:rectangle(4,2.2),1.35,.7,2.2,.075,.055,.07),
    ('1,000 × 450 mm plate',lambda:rectangle(100,45),22.,12.,36.,1.4,1.0,1.2),
    ('L-plate 160 × 110 mm',l_plate,4.,2.2,6.,.22,.17,.22),
    ('Tapered plate 180 × 100 mm',taper,4.,2.2,6.,.22,.17,.22),
    ('Arc notch + circular hole',notch_and_hole,4.,2.2,6.,.22,.17,.22),
    # The stepped boundary stresses an unrelated exact-clipping degeneracy;
    # keep it available in the test geometry library for isolated profiling.
]


def settings(case):
    name,fn,nom,lo,hi,rib,fillet,edge=case
    return dict(pitch=nom,rib=rib,perimeter=edge,holeclear=edge,
                corner=fillet,dx=0.,dy=0.,nodehole=0.,minfraction=5.,
                angle=0.,backend='python')


def cuts_for(region,s,fit=None):
    pitch=fit.pitch if fit else s['pitch']
    return g.make_pockets([region],pitch,s['rib'],s['perimeter'],
        s['holeclear'],fit.dx if fit else 0.,fit.dy if fit else 0.,
        fit.rotation if fit else 0.,s['corner'],s['minfraction']/100,
        max_cells=1600,vertex_hole_diameter=0.)


def metrics_for(region,s,fit,shapes):
    p=fit.pitch if fit else s['pitch']
    b=g.face_bounds([region]);area=abs(sum(c.loop_area(path) for path in region.curve_loops))
    perimeter=sum(sum(c.length(c.sub(seg.end,seg.start)) if isinstance(seg,c.Line)
                       else abs(seg.sweep)*seg.radius for seg in loop)
                  for loop in region.curve_loops)
    return fitting._metrics(shapes,p,s['rib'],s['corner'],b,area,s['pitch'],p,p,perimeter)


def plot(ax,region,s,fit,shapes):
    from matplotlib.patches import Polygon, Circle
    m=metrics_for(region,s,fit,shapes)
    full=[(0.,0.),(fit.pitch if fit else s['pitch'],0.)]
    p=fit.pitch if fit else s['pitch']
    full_triangle=[(0,0),(p,0),(p/2,g.SQRT3*p/2)]
    poly=g.rounded_triangle(full_triangle,s['rib']/2,0)
    import exact_clipper as exact
    full_area=abs(c.loop_area(exact.fillet_loop([c.Line(a,b) for a,b in zip(poly,poly[1:]+poly[:1])],s['corner'])))
    for shape in shapes:
        if shape.circle:
            center,r=shape.circle
            ax.add_patch(Circle(center,r,color='#444444',alpha=.5))
        else:
            val=sum(c.loop_area(path) for path in (shape.curve_loops or []))
            if not shape.curve_loops:val=sum(g.area(poly) for poly in shape.loops)
            colour='#008888' if val/full_area>=.985 else '#e38320'
            for poly in shape.loops:
                if len(poly)>2 and g.area(poly)>0:
                    ax.add_patch(Polygon(poly,facecolor=colour,edgecolor='#32434a',lw=.38,alpha=.78))
    for path,outer in zip(region.curve_loops,(o for _,o in region.loops)):
        pts=c.sample(path,.006)
        ax.plot([pt[0] for pt in pts]+[pts[0][0]],
                [pt[1] for pt in pts]+[pts[0][1]],
                color='#333333',lw=1.25,ls='-' if outer else '--')
    bounds=g.face_bounds([region]);w=bounds[2]-bounds[0];h=bounds[3]-bounds[1]
    ax.set_xlim(bounds[0]-.04*w,bounds[2]+.04*w)
    ax.set_ylim(bounds[1]-.07*h,bounds[3]+.07*h)
    ax.set_aspect('equal',adjustable='box')
    ax.set_xticks([]);ax.set_yticks([])
    return m


def run(outdir=Path('/mnt/data'),budget=160):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from PIL import Image
    legacy_path=Path(__file__).with_name('fitting_legacy_074.py')
    old=None
    if legacy_path.is_file():
        spec=importlib.util.spec_from_file_location('fitting_v074',legacy_path)
        mod=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=mod
        spec.loader.exec_module(mod)
        old=mod
    rows=[]
    all_fits=[]
    outdir.mkdir(exist_ok=True,parents=True)
    row_images=[]
    headers=('Manual nominal','Legacy Clean edges','Maximum removal','Best integer fit')
    for i,case in enumerate(CASES):
        name,construct,nom,pmin,pmax,*_=case
        region=construct();s=settings(case)
        a=time.monotonic()
        new=fitting.find_fits([region],s,pitch_min=pmin,pitch_max=pmax,
                 allow_rotation=False,evaluations=budget,max_cells=1600,seed=73021)
        tnew=time.monotonic()-a
        a=time.monotonic()
        oldfits=(old.find_fits([region],s,pitch_min=pmin,pitch_max=pmax,
                 allow_rotation=False,evaluations=budget,max_cells=1600,seed=73021)
                 if old else [])
        told=time.monotonic()-a
        oldfit=next((f for f in oldfits if f.label=='Clean edges'),None)
        best=max((f for f in new if f.label!='Maximum removal'),key=lambda f:f.fit_quality)
        removed=next(f for f in new if f.label=='Maximum removal')
        fig,axes=plt.subplots(1,4,figsize=(18,2.9),squeeze=False)
        axes=axes[0]
        for j,(label,fit) in enumerate(zip(headers,[None,oldfit,removed,best])):
            axes[j].set_title(label,fontsize=10.5,weight='bold')
            if j==1 and oldfit is None:continue
            shapes=cuts_for(region,s,fit)
            m=plot(axes[j],region,s,fit,shapes)
            score=m[-1].score
            pitch=fit.pitch if fit else s['pitch']
            axes[j].text(.5,-.10,f'{pitch*10:.1f} mm  |  {m[3]} partial  |  score {score:.3f}',
                transform=axes[j].transAxes,va='top',ha='center',fontsize=8)
            rows.append(dict(case=name,layout=label,pitch_mm=round(pitch*10,2),
                partials=m[3],run=m[-1].longest_run,
                score=round(m[-1].score,4),area_cm2=round(m[0],4),
                search_s=round(tnew if j>1 else told if j==1 else 0.,2)))
        fig.suptitle(name,fontsize=12.5,y=.995)
        fig.subplots_adjust(left=.02,right=.99,top=.82,bottom=.25,wspace=.065)
        image=outdir/f'isogrid_study_{i+1:02d}.png'
        fig.savefig(image,dpi=130)
        plt.close(fig)
        row_images.append(image)
        all_fits.append((name,new))
        print(f'{i+1}/{len(CASES)} {name}: best integer {best.pitch*10:.2f}mm '
              f'quality={best.fit_quality:.3f}, partials={best.partials}; '
              f'legacy={oldfit.pitch*10:.2f}mm if old; times {tnew:.1f}s/{told:.1f}s',flush=True)
    pictures=[Image.open(path).convert('RGB') for path in row_images]
    composite=Image.new('RGB',(max(pic.width for pic in pictures),sum(pic.height for pic in pictures)),'white')
    y=0
    for pic in pictures:
        composite.paste(pic,(0,y));y+=pic.height
    target=outdir/'isogrid_integer_fit_comparison.png'
    composite.save(target,optimize=True)
    with (outdir/'isogrid_integer_fit_metrics.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=rows[0].keys())
        writer.writeheader();writer.writerows(rows)
    return rows,all_fits


if __name__=='__main__':
    target=Path(sys.argv[1]) if len(sys.argv)>1 else Path('/mnt/data')
    budget=int(sys.argv[2]) if len(sys.argv)>2 else 160
    if len(sys.argv)>3:
        CASES=[CASES[int(sys.argv[3])]]
    run(target,budget)
