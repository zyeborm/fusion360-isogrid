"""Final fillets are represented by true circular arcs before tessellation."""
import math
import unittest
import geometry as g


class NativeArcTests(unittest.TestCase):
    def assert_loop_closed(self, segments, places=7):
        self.assertTrue(segments)
        for i, seg in enumerate(segments):
            next_seg=segments[(i+1)%len(segments)]
            self.assertAlmostEqual(g.norm(g.sub(seg.end,next_seg.start)),0,places=places)

    def test_three_exact_equal_radius_arcs_in_complete_triangle(self):
        triangle=[(0,0),(4,0),(2,2*math.sqrt(3))]
        r=.15
        segments=g.fillet_curve_loop(triangle,r)
        self.assertEqual(len([x for x in segments if isinstance(x,g.Arc2D)]),3)
        self.assertEqual(len([x for x in segments if isinstance(x,g.Line2D)]),3)
        self.assert_loop_closed(segments)
        for arc in segments:
            if not isinstance(arc,g.Arc2D): continue
            self.assertAlmostEqual(g.norm(g.sub(arc.start,arc.center)),r,places=9)
            self.assertAlmostEqual(g.norm(g.sub(arc.end,arc.center)),r,places=9)
            self.assertAlmostEqual(g.norm(g.sub(arc.middle,arc.center)),r,places=9)
            self.assertAlmostEqual(arc.sweep,2*math.pi/3,places=9)
        sampled=g.sample_curve_loop(segments)
        self.assertLess(g.area(sampled),g.area(triangle))
        self.assertGreater(len(sampled),len(triangle))

    def test_clipped_corner_retains_native_arcs(self):
        contour=[(0,0),(3,0),(3,2),(2,3),(0,3)]
        r=.2
        segments=g.fillet_curve_loop(contour,r)
        self.assert_loop_closed(segments)
        self.assertGreaterEqual(sum(isinstance(x,g.Arc2D) for x in segments),4)
        sampled=g.sample_curve_loop(segments)
        self.assertAlmostEqual(g.area(sampled),g.area(g.round_clipped_contour(contour,r)),places=8)

    def test_generated_shape_keeps_curves_and_polygon_scoring_derivative(self):
        region=g.Region([([(0,0),(8,0),(8,8),(0,8)],True)])
        shapes=g.make_pockets([region],2.2,.2,.15,.15,0,0,7,.12,
                              max_cells=500,backend='python')
        full=[shape for shape in shapes if shape.curve_loops and
              sum(isinstance(c,g.Arc2D) for loop in shape.curve_loops for c in loop)>=3]
        self.assertTrue(full)
        for shape in full:
            self.assertEqual(len(shape.loops),len(shape.curve_loops))
            for polygon,curves in zip(shape.loops,shape.curve_loops):
                self.assert_loop_closed(curves)
                self.assertAlmostEqual(g.area(polygon),g.area(g.sample_curve_loop(curves)),places=7)

    def test_zero_radius_remains_lines(self):
        triangle=[(0,0),(2,0),(1,math.sqrt(3))]
        self.assertTrue(all(isinstance(x,g.Line2D)
                            for x in g.fillet_curve_loop(triangle,0)))

if __name__=='__main__':
    unittest.main()
