"""Junction-hole clearance leaves at least one rib-width web at each pocket."""
import math
import unittest

import geometry
from test_preview_lifecycle import load_fusion_ui


class VertexClearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_fusion_ui()

    def settings(self, hole):
        return dict(pitch=2.0, rib=.2, corner=.15, nodehole=hole,
                    depth=.2, perimeter=.2, holeclear=.2,
                    minfraction=5., trim_boundary=True)

    def test_maximum_matches_true_filleted_pocket_distance(self):
        pitch, rib, radius = 2.0, .2, .15
        full = geometry.rounded_triangle([(0,0), (pitch,0),
                    (pitch/2, geometry.SQRT3*pitch/2)], rib/2, radius,
                    segments_per_corner=120)
        measured = min(geometry._distance_to_segment((0,0), a, b)
                       for a,b in zip(full, full[1:] + full[:1]))
        calculated = geometry.vertex_hole_tangency_diameter(rib,radius)/2
        # Polygonal fillets inscribe the arc: the sampled boundary lies just
        # inside the true pocket, giving slightly more apparent clearance.
        self.assertGreaterEqual(measured,calculated - 1e-7)
        self.assertLess(measured-calculated,1e-5)
        safe_radius=geometry.maximum_vertex_hole_diameter(rib,radius)/2
        # The difference is the actual narrowest edge-to-edge material web.
        self.assertAlmostEqual(measured-safe_radius, rib, delta=1e-5)

    def test_hole_can_exceed_rib_width_without_warning(self):
        # 2 mm ribs + 1.5 mm fillets permit a 3 mm hole with 2 mm radial web.
        warnings = self.ui._geometry_warnings(self.settings(.3))
        self.assertFalse(any('Vertex hole diameter' in x for x in warnings),warnings)

    def test_hole_reducing_web_below_rib_width_warns(self):
        messages = self.ui._geometry_warnings(self.settings(.5))
        self.assertTrue(any('minimum web 2 mm' in x for x in messages),messages)
        self.assertTrue(self.ui._advisory_field_errors(self.settings(.5)).get('nodehole'))

    def test_hole_greater_than_contact_limit_warns_of_overlap(self):
        messages = self.ui._geometry_warnings(self.settings(.71))
        self.assertTrue(any('7 mm' in x and 'overlap' in x for x in messages),messages)
        self.assertTrue(self.ui._advisory_field_errors(self.settings(.71)).get('nodehole'))

    def test_exact_tangency_is_advisory(self):
        messages = self.ui._geometry_warnings(self.settings(.7))
        self.assertTrue(any('tangent' in x for x in messages),messages)
        self.assertTrue(self.ui._advisory_field_errors(self.settings(.7)).get('nodehole'))

    def test_fillets_disabled_give_no_vertex_hole_with_full_rib_web(self):
        self.assertEqual(geometry.maximum_vertex_hole_diameter(.2,0),0)
        self.assertAlmostEqual(geometry.vertex_hole_tangency_diameter(.2,0),.4)

    def test_web_diameter_reduction_is_twice_required_radial_gap(self):
        for rib,corner in ((.2,.15),(.3,.2),(.1,.1)):
            with self.subTest(rib=rib,corner=corner):
                contact=geometry.vertex_hole_tangency_diameter(rib,corner)
                safe=geometry.maximum_vertex_hole_diameter(rib,corner)
                self.assertAlmostEqual((contact-safe)/2,rib)


if __name__=='__main__':
    unittest.main()
