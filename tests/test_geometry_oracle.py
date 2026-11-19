"""Optional Shapely oracle: only for developers, never required in Fusion."""
import math,random,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import geometry as g
try:
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
except ImportError:
    Polygon=None

@unittest.skipUnless(Polygon,'Shapely not installed (optional oracle)')
class ClipAgainstShapely(unittest.TestCase):
    def test_crossing_face_holes_and_sketch_mask(self):
        region=g.Region([([(0,0),(10,0),(10,10),(0,10)],True),
                  ([(3,3),(3,7),(7,7),(7,3)],False)])
        mask=g.Region([([(1,1),(9,1),(9,9),(1,9)],True)])
        expected=Polygon([(0,0),(10,0),(10,10),(0,10)],
                  holes=[[(3,3),(3,7),(7,7),(7,3)]]).intersection(Polygon([(1,1),(9,1),(9,9),(1,9)]))
        random.seed(72)
        for _ in range(500):
            x,y=random.uniform(-2,12),random.uniform(-2,12)
            radius=random.uniform(.1,13);theta=random.uniform(0,7)
            tri=[(x+radius*math.cos(theta+i*math.tau/3),
                  y+radius*math.sin(theta+i*math.tau/3)) for i in range(3)]
            clipped=g.clip_pocket(tri,[region,mask])
            self.assertAlmostEqual(sum(g.area(p) for p in clipped),
                 expected.intersection(Polygon(tri)).area,delta=1e-5)

    def test_margin_buffers_with_overlapping_capsules(self):
        # This specifically validates the fallback geometry where several
        # offset bands intersect, including the edges of an internal void.
        region=g.Region([([(0,0),(10,0),(10,10),(0,10)],True),
                    ([(3,3),(3,7),(7,7),(7,3)],False)])
        source=Polygon([(0,0),(10,0),(10,10),(0,10)],
                       holes=[[(3,3),(3,7),(7,7),(7,3)]])
        edges=g._buffer_edges([region],.25,.25)
        expected=source.difference(unary_union([Polygon(g._capsule(a,b,r))
                                                for _,a,b,r in edges]))
        random.seed(1337)
        for _ in range(120):
            x,y=random.uniform(-2,12),random.uniform(-2,12)
            rad=random.uniform(.25,5);theta=random.uniform(0,math.tau)
            tri=[(x+rad*math.cos(theta+j*math.tau/3),
                  y+rad*math.sin(theta+j*math.tau/3)) for j in range(3)]
            clipped=g.clip_pocket(tri,[region],edges)
            self.assertAlmostEqual(sum(g.area(p) for p in clipped),
                expected.intersection(Polygon(tri)).area,delta=1e-5)

if __name__=='__main__':unittest.main()
