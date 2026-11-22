"""Avoid recomputing exact parametric spline distance and area results.

Immutable frozen curve segments and query points are safe to memoise. Caches
should affect *only* performance, not exact accepted geometry.
"""
import pathlib
import sys
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import curves2d as c
import geometry as g
from test_curved_dxf_regression import test_regions

class ExactSplineCacheTests(unittest.TestCase):
    def test_repeated_closest_point_and_area_are_cached(self):
        spline=next(q for q in test_regions()[0].curve_loops[0] if isinstance(q,c.Nurbs))
        offset=c.Offset(spline,.3)
        q=(1.5,7.0)
        c._closest_parameter.cache_clear()
        x=c._closest_parameter(offset,q)
        self.assertEqual(c._closest_parameter(offset,q),x)
        self.assertGreaterEqual(c._closest_parameter.cache_info().hits,1)
        c.segment_area.cache_clear()
        a=c.segment_area(offset)
        self.assertEqual(c.segment_area(offset),a)
        self.assertGreaterEqual(c.segment_area.cache_info().hits,1)

    def test_exact_pockets_unchanged_across_cold_and_warm_caches(self):
        c.segment_area.cache_clear()
        c._closest_parameter.cache_clear()
        regions=test_regions()
        def run():
            return g.make_pockets(regions,2.,.2,.3,.3,0.,0.,0.,.15,
                                  min_area_fraction=.05,max_cells=1600,
                                  vertex_hole_diameter=.3)
        original=run()
        self.assertEqual(len(original),131)
        self.assertGreater(c._closest_parameter.cache_info().hits,0)
        self.assertGreater(c.segment_area.cache_info().hits,0)
        again=run()
        self.assertEqual(original,again)

if __name__=='__main__':unittest.main()
