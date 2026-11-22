"""Geometry-only offset-loop benchmark; external geometry reference is Shapely."""
import math,time,statistics,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/"tests"))
import curves2d as c
import geometry as g
import exact_clipper as exact
from offset_cleanup import clean_closed_offset,clean_open_offset,self_crossings
from shared_boundary import Boundary
from test_curved_dxf_regression import test_regions
from shapely.geometry import Polygon


def sample_times(fn,count=5):
    times=[]
    for _ in range(count):
        start=time.perf_counter()
        result=fn()
        times.append((time.perf_counter()-start)*1000.)
    return result,round(statistics.median(times),3)


def main():
    ell=c.Ellipse((0.,0.),(4.,0.),(0.,1.))
    source_poly=Polygon(c.sample([ell],1e-5))
    for d in (.1,.3,.6,.9,1.):
        off=c.Offset(ell,d)
        crossings,t_cross=sample_times(lambda:self_crossings(off))
        cleaned,t_clean=sample_times(lambda:clean_closed_offset(ell,d,True))
        ref=source_poly.buffer(-d,quad_segs=96)
        estimate=(Polygon(c.sample(cleaned[0],1e-5)) if cleaned else Polygon())
        error=estimate.symmetric_difference(ref).area
        print(f'ellipse d={d:.1f} cm self-crossings={len(crossings)} clean segments={sum(map(len,cleaned))} '
              f'crossings={t_cross:.2f} ms cleaning={t_clean:.2f} ms '
              f'symmetric difference={error*100:.6f} mm²',flush=True)
    cubic=c.Nurbs(((0,0),(1,2),(2,-2),(3,0)),3,(0,)*4+(1,)*4,(1,)*4,0.,1.)
    kept,t_open=sample_times(lambda:clean_open_offset(cubic,.5))
    print(f'open cubic NURBS d=0.5 cm retained={len(kept)} sections cleaning={t_open:.2f} ms '
          f'join gap={c.length(c.sub(kept[0].end,kept[1].start)):.3e} cm',flush=True)
    spline=next(s for s in test_regions()[0].curve_loops[0] if isinstance(s,c.Nurbs))
    hits,t_spline=sample_times(lambda:self_crossings(c.Offset(spline,.3)))
    print(f'original curved DXF source spline d=0.3 cm self-crossings={len(hits)} '
          f'detection={t_spline:.2f} ms',flush=True)
    region=g.Region([(c.sample([ell],5e-4),True)],curve_loops=[[ell]])
    prepared,t_prep=sample_times(lambda:Boundary([region],.6,.6))
    tris=[[(x-.5,y-.25),(x+.5,y-.25),(x,y+.5)] for x in (-3.5,-2.,0.,2.,3.5)
          for y in (-.6,-.15,.3,.75)]
    clipped,t_tri=sample_times(lambda:[prepared.clip(tri) for tri in tris])
    print(f'prepared boundary={t_prep:.2f} ms; 20 triangle clips={t_tri:.2f} ms; '
          f'{sum(bool(out) for out in clipped)} nonempty',flush=True)
    prep=exact.PreparedCurves([exact.CurveRegion([([ell],True)])],.6,.6)
    box=[(-5,-2),(5,-2),(5,2),(-5,2)]
    original,t_original=sample_times(lambda:prep.clip(box))
    print(f'previous exact clip of enclosing rectangle={t_original:.2f} ms, '
          f'{len(original)} regions (expected one; old method fails this topology)',flush=True)

if __name__=='__main__':main()
