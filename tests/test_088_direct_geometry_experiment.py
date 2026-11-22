"""Geometry-only shared boundary and local fillet experiment.

Does not exercise Fusion/CAM. Comparison uses the original exact generator as
reference and preserves per-pocket identifiers, cut count and corner rejection.
"""
import math
import pathlib
import sys
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import curves2d as c
import geometry as g
from shared_boundary import PreparedDirect
from fast_corner import rounded_pocket as local_fillet
from test_curved_dxf_regression import test_regions


class DirectGeometryExperiment(unittest.TestCase):
    def test_default_and_autofit_retained_shapes_match(self):
        regions=test_regions()
        common=dict(rib=.2,perimeter=.3,void_clearance=.3,rotation=0.,
                    corner_radius=.15,min_area_fraction=.05,max_cells=1600,
                    vertex_hole_diameter=.3)
        for pitch,dx,dy,expected_rejected in ((2.,0.,0.,6),
                                               (1.928114,.921259,.567284,4)):
            options=dict(common,pitch=pitch,offset_x=dx,offset_y=dy)
            with self.subTest(pitch=pitch):
                orig=[];new=[]
                baseline=g.make_pockets(regions,rejected=orig,**options)
                prepared=PreparedDirect(regions,.3,.3,.15)
                alternative=g.make_pockets(regions,prepared=prepared,
                    round_pocket=local_fillet,rejected=new,**options)
                self.assertEqual((len(baseline),len(orig)),(131,expected_rejected))
                self.assertEqual((len(alternative),len(new)),(131,expected_rejected))
                def keyed(shapes):
                    return {tuple(round(v,5) for v in g.polygon_centroid(sh.outline)):sh
                            for sh in shapes}
                old=keyed(baseline);modern=keyed(alternative)
                self.assertEqual(old.keys(),modern.keys())
                for key,sh in modern.items():
                    for loop in sh.curve_loops or []:
                        self.assertTrue(c.close_loop(loop,2e-5))
                    # Compare sampled geometry. The legacy 256-node Green
                    # integrator has >1e-5 cm² error on some arbitrarily
                    # shortened NURBS intervals, even when contours coincide.
                    a=sum(g.area(c.sample(loop,.0003))
                          for loop in old[key].curve_loops or [])
                    b=sum(g.area(c.sample(loop,.0003))
                          for loop in sh.curve_loops or [])
                    self.assertLess(abs(a-b),1e-6)

    def test_shared_region_preserves_round_hole(self):
        outside=[c.Line((0,0),(9,0)),c.Line((9,0),(9,6)),
                 c.Line((9,6),(0,6)),c.Line((0,6),(0,0))]
        hole=[c.circle((4.5,3),.78,False)]
        loops=[outside,hole]
        regions=[g.Region([(c.sample(loop,.0005),i==0)
                           for i,loop in enumerate(loops)],curve_loops=loops)]
        prep=PreparedDirect(regions,.25,.25,.11)
        self.assertIsNotNone(prep.direct)
        self.assertEqual(len(prep.direct.loops),2)
        self.assertEqual(sum(c.loop_area(loop)<0 for loop in prep.direct.loops),1)

    def test_missing_void_causes_fallback_not_missing_material(self):
        outside=[c.Line((0,0),(9,0)),c.Line((9,0),(9,6)),
                 c.Line((9,6),(0,6)),c.Line((0,6),(0,0))]
        ellipse=[c.Ellipse((4.5,3),(1.,0),(0,.65),0.,-math.tau)]
        loops=[outside,ellipse]
        regions=[g.Region([(c.sample(loop,.0005),i==0)
                           for i,loop in enumerate(loops)],curve_loops=loops)]
        prep=PreparedDirect(regions,.25,.25,.11)
        self.assertIsNone(prep.direct)
        self.assertIsNotNone(prep.region.exact)

if __name__=='__main__':unittest.main()
