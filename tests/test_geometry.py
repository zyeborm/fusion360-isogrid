import math
import random
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import geometry as g

class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.square=g.Region([([(0,0),(10,0),(10,10),(0,10)],True)])
        self.annulus=g.Region([([(0,0),(10,0),(10,10),(0,10)],True),
                                ([(3,3),(3,7),(7,7),(7,3)],False)])
    def test_basic_intersections(self):
        p=[(1,1),(5,1),(3,5)]
        self.assertAlmostEqual(sum(map(g.area,g.clip_pocket(p,[self.annulus]))),7)
        self.assertAlmostEqual(sum(map(g.area,g.clip_pocket(p,[self.square]))),8)
        self.assertEqual(g.clip_pocket([(3.3,3.3),(4,3.3),(3.6,4)],[self.annulus]),[])
    def test_hole_enclosed(self):
        p=[(-5,-5),(20,-5),(5,20)]
        got=g.clip_pocket(p,[self.annulus]);self.assertTrue(any(g.area(x)<0 for x in got))
    def test_offset(self):
        off=self.annulus.inset(0.5,0.5)
        self.assertAlmostEqual(g.area(off.loops[0][0]),81)
        self.assertAlmostEqual(abs(g.area(off.loops[1][0])),25)
        self.assertFalse(off.contains((3.1,4)))
        self.assertTrue(off.contains((1,1)))
    def test_lattice_spacing(self):
        arr=list(g.lattice_pockets((0,0,8,8),2,0.2,(0,0),0))
        self.assertGreater(len(arr),10)
        for p in arr:self.assertGreater(g.area(p),0)
        self.assertAlmostEqual(g.rounded_triangle([(0,0),(2,0),(1,math.sqrt(3))],.1,0)[0][0],math.sqrt(3)*.1)
    def test_rounded(self):
        v=[(0,0),(2,0),(1,math.sqrt(3))]
        a=g.area(g.rounded_triangle(v,.1,0))
        b=g.area(g.rounded_triangle(v,.1,.1))
        self.assertGreater(a,b)
        self.assertGreater(b,0.9*a)
    def test_multiple_regions(self):
        extra=g.Region([([(0,0),(5,0),(5,10),(0,10)],True)])
        p=[(1,1),(9,1),(5,9)]
        got=g.clip_pocket(p,[self.square,extra])
        self.assertAlmostEqual(sum(map(g.area,got)),16)
    def test_generate(self):
        res=g.make_pockets([self.annulus],2,.2,.2,.2,0,0,12)
        self.assertGreater(len(res),10)
        for shape in res:
            self.assertGreater(g.area(shape.outline),0)
            self.assertTrue(any(g.area(loop)>0 for loop in shape.loops))

    def test_cusp_region_with_margin_and_void(self):
        # Arc is tangent to a vertical edge but reverses direction at their
        # shared point. The old miter inset raised "near-cusp" here.
        arc=[(7+7*math.cos(t*math.pi/64),20-7*math.sin(t*math.pi/64))
             for t in range(65)]
        face=g.Region([([(0,0),(20,0),(25,8),(25,20)]+arc+[(0,0)],True),
                ([(10+math.cos(t*math.tau/64),5+math.sin(t*math.tau/64))
                  for t in range(64)],False)])
        result=g.make_pockets([face],2,.2,.3,.3,0,0,0,.15,
                              max_cells=700,vertex_hole_diameter=.2)
        self.assertGreater(len(result),30)
        self.assertGreater(sum(bool(s.circle) for s in result),10)
        # Check all output contour samples stay inside the offset mask,
        # subject to the conservative polygonal capsule approximation.
        for shape in result:
            for poly in shape.loops:
                for p in poly:
                    self.assertTrue(face.contains(p),p)

    def test_vertex_holes_follow_grid_and_respect_clearance(self):
        result=g.make_pockets([self.annulus],2,.2,.3,.4,0,0,19,.1,
                              vertex_hole_diameter=.2)
        holes=[shape for shape in result if shape.circle]
        self.assertGreater(len(holes),6)
        for item in holes:
            center,r=item.circle
            self.assertAlmostEqual(r,.1)
            self.assertTrue(self.annulus.contains(center))
            for poly,is_outer in self.annulus.loops:
                clearance=.3 if is_outer else .4
                for a,b in zip(poly,poly[1:]+poly[:1]):
                    self.assertGreaterEqual(g._distance_to_segment(center,a,b)+1e-5,
                                            r+clearance)

    def test_newly_clipped_corners_receive_rounding(self):
        # A large triangular pocket cuts across two face edges, introducing
        # square corners that never existed in the original triangle.
        candidate=[(-2,2),(8,-2),(8,8)]
        clipped=g.clip_pocket(candidate,[self.square])
        self.assertEqual(len(clipped),1)
        sharp=clipped[0]
        rounded=g.round_clipped_contour(sharp,.20)
        self.assertGreater(len(rounded),len(sharp)+5)
        self.assertGreater(g.area(sharp),g.area(rounded))
        self.assertTrue(all(-1e-7<=p[0]<=10+1e-7 and
                            -1e-7<=p[1]<=10+1e-7 for p in rounded))

    def test_clipped_fillets_never_enter_hole_or_margin(self):
        from shapely.geometry import Polygon
        border=g._buffer_edges([self.annulus],.25,.25)
        candidate=[(-2,2),(8,-2),(8,8)]
        clipped=g.clip_pocket(candidate,[self.annulus],border)
        for poly in clipped:
            if g.area(poly)<=0:continue
            filleted=g.round_clipped_contour(poly,.15)
            # A fragment too narrow for the full requested milling radius is
            # deliberately omitted rather than generated with sharp corners.
            if filleted:
                self.assertTrue(Polygon(poly).buffer(.00001).covers(Polygon(filleted)))

    def test_generated_pockets_fillet_new_edge_intersections(self):
        # Look at actual final pockets rather than just the low-level fillet
        # function: a square face clips several of these large triangles.
        s=self.square
        plain=g.make_pockets([s],3.2,.2,.2,.2,.11,.25,7,0,
                              max_cells=350,min_area_fraction=0)
        rounded=g.make_pockets([s],3.2,.2,.2,.2,.11,.25,7,.12,
                                max_cells=350,min_area_fraction=0)
        self.assertGreater(len(rounded),3)
        # Rounding applies to the *finished* intersection, so the 2D area
        # must shrink; this includes corners created at the perimeter.
        area_plain=sum(sum(g.area(p) for p in sh.loops) for sh in plain)
        area_round=sum(sum(g.area(p) for p in sh.loops) for sh in rounded)
        self.assertLess(area_round,area_plain)

    def test_origin_anchor_selection(self):
        box=(0,0,10,10)
        self.assertEqual(g.lattice_origin(box,2,0,0,0),(5,5))
        self.assertEqual(g.lattice_origin(box,2,0,.2,-.1,(1,2)),(1.2,1.9))
        vertex=g.lattice_origin(box,2,0,0,0,(1,2),'triangle')
        self.assertAlmostEqual(vertex[0],0)
        self.assertAlmostEqual(vertex[1],2-g.SQRT3/3)

if __name__=='__main__':unittest.main()
