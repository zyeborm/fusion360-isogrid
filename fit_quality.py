"""Scale-independent geometric fit quality for a triangular pocket lattice.

This module only handles Python geometry/metrics.  It deliberately does not
compute or imply structural strength.  One source triangle may produce multiple
cut islands; those are accumulated before measuring partial-cell fractions.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Quality:
    score: float
    partial_damage: float
    longest_run: int
    strip_damage: float
    partial_count: int
    clipped_fraction: float


def _runs(partials, pitch):
    """Connected runs of partial-cell centroids, with straightness/consistency.

    Adjacent equilateral triangles have centroids about pitch/sqrt(3) apart.
    A bounded spatial hash avoids O(n²) pairwise comparisons for dense layouts.
    A circular boundary's changing direction and intersection fractions reduce
    its penalty relative to a long, straight strip of similar partial cells.
    """
    if len(partials)<3:
        return 0,0.0
    step=pitch/math.sqrt(3)
    grid=defaultdict(list)
    for i,(x,y,_) in enumerate(partials):
        grid[(math.floor(x/step),math.floor(y/step))].append(i)
    parent=list(range(len(partials)))
    rank=[0]*len(partials)
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]
            i=parent[i]
        return i
    def union(i,j):
        a,b=find(i),find(j)
        if a==b:return
        if rank[a]<rank[b]:a,b=b,a
        parent[b]=a
        if rank[a]==rank[b]:rank[a]+=1
    near2=(step*1.25)**2
    for i,(x,y,_) in enumerate(partials):
        gx,gy=math.floor(x/step),math.floor(y/step)
        for a in (gx-2,gx-1,gx,gx+1,gx+2):
            for b in (gy-2,gy-1,gy,gy+1,gy+2):
                for j in grid.get((a,b),()):
                    if j>=i:continue
                    xx,yy,_=partials[j]
                    if (x-xx)**2+(y-yy)**2<=near2:
                        union(i,j)
    groups=defaultdict(list)
    for i,p in enumerate(partials):groups[find(i)].append(p)
    longest=max(map(len,groups.values()),default=0)
    strip=0.0
    for group in groups.values():
        n=len(group)
        if n<3:continue
        mx=sum(p[0] for p in group)/n
        my=sum(p[1] for p in group)/n
        xx=sum((p[0]-mx)**2 for p in group)/n
        yy=sum((p[1]-my)**2 for p in group)/n
        xy=sum((p[0]-mx)*(p[1]-my) for p in group)/n
        eiggap=math.hypot(xx-yy,2*xy)
        # Eigenvalue ratio -> 1 for collinear points, 0 for isotropic clusters.
        straightness=eiggap/max(xx+yy,1e-15)
        fr=[p[2] for p in group]
        mean=sum(fr)/n
        variance=sum((v-mean)**2 for v in fr)/n
        consistency=max(0.,1.-math.sqrt(variance)/.33)
        # Long rows matter beyond their per-cell penalty.  The multiplicative
        # term leaves curved or inconsistent boundary fragments less penalised.
        strip+=(n-2)*straightness**2*consistency
    return longest,strip


def evaluate(cells, pitch, perimeter_length):
    """Score cell-fit quality independently of absolute part dimensions.

    `cells` is an iterable of (source_centroid_xy, retained_area_fraction).
    Only retained pockets belong here; completely excluded lattice cells
    are not defects.  Fractions refer to *rounded, full-size pocket area*.
    """
    cells=list(cells)
    if pitch<=0:raise ValueError('Pitch must be positive.')
    if not cells:return Quality(0.,0.,0,0.,0,0.)
    partials=[]
    damage=0.
    for (x,y),f in cells:
        f=max(0.,min(1.,f))
        if f>=.985:continue
        # Base charge for a partial pocket plus extra for middle-sized cuts.
        # Tiny retained islands already carry a partial penalty; the upstream
        # min-area filter decides whether to omit them altogether.
        penalty=.50+.50*4*f*(1-f)
        damage+=penalty
        partials.append((x,y,f))
    longest,strip=_runs(partials,pitch)
    # Expected number of cells meeting a boundary scales as its length/pitch.
    # This denominator prevents small-pitch solutions winning solely from
    # having more complete interior cells, or large parts scoring differently.
    opportunities=max(1.,perimeter_length/(pitch*.58))
    loss=(damage+1.1*strip)/opportunities
    score=1./(1.+loss)
    return Quality(score,damage,longest,strip,len(partials),
                   sum(1-f for _,_,f in partials)/max(1,len(cells)))
