"""Regression profile reconstructed from user's curved.dxf (millimetres).

No Fusion dependencies. This checks whole-pattern generation, not just
individual NURBS operations. Fusion geometry is represented in centimetres.
"""
import math
import time
import unittest
import pathlib
import sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import curves2d as c
import exact_clipper as e
import geometry as g

SPLINE_MM = (
    (0, 50.59127347),
    (-0.20971484, 52.50110258),
    (-0.79204617, 56.19409041),
    (-2.15426083, 61.35357171),
    (-4.95042241, 67.47080387),
    (-10.0562294, 73.82117181),
    (-16.67668202, 78.81563366),
    (-24.60263183, 82.35297361),
    (-33.45663703, 84.27173069),
    (-42.67695077, 84.3636083),
    (-51.64957486, 82.501769),
    (-59.81935653, 78.75751962),
    (-66.80389013, 73.51393242),
    (-72.52153054, 67.60885862),
    (-77.2760666, 62.39691526),
    (-81.56521103, 59.28210227),
    (-85.93739384, 59.35675231),
    (-90.8053844, 62.90929686),
    (-96.36568597, 69.27750046),
    (-102.67470011, 77.22905118),
    (-109.68830055, 85.22169603),
    (-117.31200357, 91.68785405),
    (-125.45176337, 95.35304161),
    (-134.04181792, 95.378721),
    (-143.03453088, 91.2337009),
    (-152.3996467, 82.63646371),
    (-160.1757093, 72.10604459),
    (-166.16408837, 62.14785578),
    (-170.22563643, 54.59569454),
    (-172.27373457, 50.59127347),
)

def mm(point):
    return (point[0]/10.,point[1]/10.)

def test_regions():
    controls=tuple(mm(p) for p in SPLINE_MM)
    knots=(0.,)*6+tuple(round(.04*i,10) for i in range(1,25))+(1.,)*6
    spline=c.Nurbs(controls,5,knots,(1.,)*len(controls),0.,1.)
    points=[(0.,0.),(38.7804430841,0.),(54.4972173796,25.8536287227),
            (54.4972173796,50.5912734718),(20.366707519,50.5912734718)]
    outer=[c.Line(mm(a),mm(b)) for a,b in zip(points,points[1:])]
    outer.append(c.Arc(mm((10.1833537595,49.4918140543)),
                       mm((20.366707519,50.5912734718)),
                       mm((0.,50.5912734718)),math.radians(-192.32429200456)))
    outer.append(spline)
    outer.extend([c.Line(mm((-172.2737345718,50.5912734718)),mm((-172.2737345718,0.))),
                  c.Line(mm((-172.2737345718,0.)),mm((0.,0.)))])
    hole=[c.circle(mm((16.6467609402,10.880843743)),2.90537115615/10.,False)]
    assert c.close_loop(outer,5e-5), 'DXF profile closure and edge orientation'
    region=e.CurveRegion([(outer,True),(hole,False)])
    sampling=[(c.sample(outer,.0025),True),(c.sample(hole,.0025),False)]
    return [g.Region(sampling,curve_loops=[outer,hole])]

class CurvedDxfPatternTests(unittest.TestCase):
    def test_native_profile_produces_pockets(self):
        regions=test_regions()
        start=time.perf_counter()
        shapes=g.make_pockets(regions,2.,.2,.1,.1,0.,0.,0.,.1,
                              max_cells=1600,vertex_hole_diameter=0.)
        elapsed=time.perf_counter()-start
        self.assertGreater(len(shapes),10, 'Expected isogrid pocket geometry')
        self.assertLess(elapsed,30.,'Full preview path still exceeds 30 seconds')
        self.assertTrue(all(shape.loops for shape in shapes))
        print('curved DXF whole-pattern: %d shapes in %.3f s'%(len(shapes),elapsed))

    def test_fusion_default_settings_include_vertex_holes(self):
        # Actual UI defaults, unlike the simplified fixture above. Before
        # the tolerance fix, corner repair failed in CurveRegion.__post_init__.
        start=time.perf_counter()
        shapes=g.make_pockets(test_regions(),2.,.2,.3,.3,0.,0.,0.,.15,
                              min_area_fraction=.05,max_cells=1600,
                              vertex_hole_diameter=.3)
        elapsed=time.perf_counter()-start
        self.assertEqual(len(shapes),131)
        self.assertEqual(sum(shape.circle is not None for shape in shapes),36)
        # The old fallback generated six pointed pockets that could approach
        # the nominal 3 mm vertex holes within 0.5 mm. Unroundable pockets
        # are now rejected instead of silently violating the requested 1.5 mm
        # corner radius and 2 mm rib width.
        self.assertFalse(any(shape.fillet_warnings for shape in shapes))
        self.assertTrue(all(shape.loops for shape in shapes))
        for shape in shapes:
            for loop in shape.curve_loops or []:
                self.assertTrue(c.close_loop(loop,2e-5))
        self.assertLess(elapsed,30.,'Default preview exceeds 30 seconds')
        print('curved DXF Fusion defaults: %d shapes in %.3f s'%(len(shapes),elapsed))

    def test_rounding_accepts_assembler_tolerance_but_rejects_open_loop(self):
        near_gap=2.25e-6  # cm; observed 0.0000223 mm corner-repair gap
        contour=[c.Line((0.,0.),(2.,0.)),c.Line((2.,0.),(2.,2.)),
                 c.Line((2.,2.),(0.,2.)),c.Line((0.,2.),(near_gap,0.))]
        self.assertTrue(e.CurveRegion([(contour,True)]).contains((1.,1.)))
        too_large=5e-5
        contour[-1]=c.Line((0.,2.),(too_large,0.))
        with self.assertRaisesRegex(ValueError,'Open curve boundary'):
            e.CurveRegion([(contour,True)])

if __name__ == '__main__':
    unittest.main()
