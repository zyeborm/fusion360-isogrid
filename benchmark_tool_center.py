"""Reproducible geometry-only benchmark for erosion/intersection/dilation.

The alternate generator is independent of the old pocket-rounding pipeline.
All generated curves are native parametric Line/Arc/Offset segments.
"""
import sys,time,statistics
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'tests'))
import curves2d as c
import geometry as g
import tool_center as tc
from test_curved_dxf_regression import test_regions

REGIONS=test_regions()
CASES={'Default':(2.,0.,0.), 'Auto Fit':(1.928114,.921259,.567284)}


def reset_caches():
    c.segment_area.cache_clear()
    c._closest_parameter.cache_clear()
    c._flatten.cache_clear()


def compute(case,modern=False):
    pitch,dx,dy=CASES[case]
    args=dict(regions=REGIONS,pitch=pitch,rib=.2,perimeter=.3,void_clearance=.3,
              offset_x=dx,offset_y=dy,rotation=0.,corner_radius=.15,
              vertex_hole_diameter=.3,min_area_fraction=.05,max_cells=1600)
    start=time.perf_counter()
    if modern:
        shapes,engine=tc.make_toolcentre_pockets(**args)
        skipped=engine.nonconvex
    else:
        rejected=[]
        shapes=g.make_pockets(**args,rejected=rejected)
        skipped=len(rejected)
    return shapes,time.perf_counter()-start,skipped


def shape_key(shape):
    return tuple(round(v,5) for v in g.polygon_centroid(shape.outline))


def compare(reference,modern):
    """Sample contours for *validation only*, not for output geometry."""
    try:
        from shapely.geometry import Polygon,Point
        from shapely.ops import unary_union
    except ImportError:
        return {'geometry_comparison':'Shapely unavailable'}
    def poly(s):
        if s.circle:return Point(s.circle[0]).buffer(s.circle[1],quad_segs=192)
        a=[Polygon(c.sample(l,1e-5)) for l in s.curve_loops if c.loop_area(l)>0]
        b=[Polygon(c.sample(l,1e-5)) for l in s.curve_loops if c.loop_area(l)<0]
        return unary_union(a).difference(unary_union(b))
    x={shape_key(s):poly(s) for s in reference}
    y={shape_key(s):poly(s) for s in modern}
    diffs=sorted([(x[k].symmetric_difference(y[k]).area,k) for k in x.keys()&y.keys()],reverse=True)
    return {'only_baseline':len(x.keys()-y.keys()),'only_new':len(y.keys()-x.keys()),
            'changed_shapes_over_0.01mm2':sum(d>.0001 for d,_ in diffs),
            'largest_difference_mm2':round(diffs[0][0]*100,6),
            'largest_difference_cell':diffs[0][1],
            'total_cut_area_mm2_baseline':round(sum(p.area for p in x.values())*100,4),
            'total_cut_area_mm2_new':round(sum(p.area for p in y.values())*100,4)}


def de_boor_count(case,modern):
    orig=c._de_boor
    calls=[0]
    def counted(*args):calls[0]+=1;return orig(*args)
    c._de_boor=counted
    try:
        reset_caches()
        _,runtime,_=compute(case,modern)
    finally:
        c._de_boor=orig
    return calls[0],round(runtime,3)


def main():
    for case in CASES:
        times={False:[],True:[]};outputs={}
        for alternate in (False,True,False,True):
            reset_caches()
            shapes,elapsed,unhandled=compute(case,alternate)
            times[alternate].append(elapsed)
            outputs[alternate]=shapes
            print(f'{case:8s} {"centres" if alternate else "baseline":8s}  {elapsed:.3f}s  '
                  f'{len(shapes)} shapes  {unhandled} legacy rejection/unsupported',flush=True)
        old=statistics.median(times[False]);new=statistics.median(times[True])
        print(f'{case:8s} median {old:.3f}s -> {new:.3f}s  SPEEDUP {old/new:.2f}x',flush=True)
        print(case,'sampled region comparison',compare(outputs[False],outputs[True]),flush=True)
    for modern in (False,True):
        count,runtime=de_boor_count('Default',modern)
        print('Default:', 'centre geometry' if modern else 'baseline',
              f'{count:,} NURBS de Boor evaluations, {runtime}s instrumented',flush=True)

if __name__=='__main__':main()
