"""Reproducible comparison: native pure-Python geometry, no Fusion SDK."""
import sys,time,statistics,math
from pathlib import Path
p=Path(__file__).parent
sys.path[:0]=[str(p),str(p/'fusion360-isogrid'),str(p/'fusion360-isogrid/tests')]
import curves2d as c,geometry as g
from shared_boundary import PreparedDirect
from fast_corner import rounded_pocket as fast_rounded_pocket
from test_curved_dxf_regression import test_regions
try:
 from shapely.geometry import Point,Polygon
 from shapely.ops import unary_union
except ImportError:Point=Polygon=unary_union=None

REGIONS=test_regions()
COMMON=dict(rib=.2,perimeter=.3,void_clearance=.3,rotation=0.,corner_radius=.15,min_area_fraction=.05,max_cells=1600,vertex_hole_diameter=.3)
CASES={
 'default':dict(pitch=2.,offset_x=0.,offset_y=0.),
 'Auto Fit':dict(pitch=1.928114,offset_x=.921259,offset_y=.567284),
}

def generate(case,fast=False):
 c.segment_area.cache_clear();c._closest_parameter.cache_clear()
 begin=time.perf_counter()
 prep=PreparedDirect(REGIONS,.3,.3,COMMON['corner_radius']) if fast else g.PreparedGeometry(REGIONS,.3,.3)
 prepare=time.perf_counter()-begin
 rejected=[];begin=time.perf_counter()
 shapes=g.make_pockets(REGIONS,prepared=prep,rejected=rejected,round_pocket=fast_rounded_pocket if fast else None,**(COMMON|CASES[case]))
 generation=time.perf_counter()-begin
 return shapes,prepare,generation,len(rejected),getattr(getattr(prep,'direct',None),'count_intersections',None)

def shape_key(shape):return tuple(round(x,5) for x in g.polygon_centroid(shape.outline))
def polygon(shape):
 if shape.circle:
  center,r=shape.circle
  return Point(center).buffer(r,quad_segs=96)
 pos=[];neg=[]
 for loop in shape.curve_loops or []:
  p=Polygon(c.sample(loop,.0004))
  if c.loop_area(loop)>0:pos.append(p)
  else:neg.append(p)
 return unary_union(pos).difference(unary_union(neg))

def validate(reference,alternative):
 a={shape_key(s):s for s in reference};b={shape_key(s):s for s in alternative}
 if a.keys()!=b.keys():return {'mismatched_pocket_keys':len(a.keys()^b.keys())}
 assert all(c.close_loop(loop,2e-5) for s in alternative for loop in (s.curve_loops or []))
 if Polygon is None:return {'same_pocket_keys':len(a),'sampled_area_comparison':'Shapely not installed'}
 differences=[]
 for key in a:
  x=polygon(a[key]);y=polygon(b[key])
  differences.append(x.symmetric_difference(y).area)
 return {'same_pocket_keys':len(a),
         'sampled_symmetric_difference_mm2':round(sum(differences)*100,9),
         'maximum_individual_difference_mm2':round(max(differences)*100,9)}

if __name__=='__main__':
 for case in CASES:
  results=[]
  for method in (False,True,False,True):
   out,setup,elapsed,rejected,hits=generate(case,method)
   results.append((out,setup,elapsed,rejected,hits))
   print(f'{case:<8} {"direct" if method else "baseline":<8} prep={setup:.4f}s generation={elapsed:.4f}s total={setup+elapsed:.4f}s shapes={len(out)} rejected={rejected} hits={hits}',flush=True)
  base=[x[1]+x[2] for x in (results[0],results[2])]
  direct=[x[1]+x[2] for x in (results[1],results[3])]
  print(case,'median total speedup',round(statistics.median(base)/statistics.median(direct),3),'x',flush=True)
  print(case,'geometry comparison',validate(results[0][0],results[1][0]),flush=True)
