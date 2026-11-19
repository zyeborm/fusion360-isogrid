"""Nominal junction-hole clearance follows rounded triangular pocket geometry."""
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
        calculated = geometry.maximum_vertex_hole_diameter(rib,radius)/2
        # Polygonal fillets inscribe the arc: the sampled boundary lies just
        # inside the true pocket, giving slightly more apparent clearance.
        self.assertGreaterEqual(measured,calculated - 1e-7)
        self.assertLess(measured-calculated,1e-5)

    def test_hole_can_exceed_rib_width_without_warning(self):
        # 2 mm ribs + 1.5 mm fillets permit a nominal 7 mm diameter hole.
        warnings = self.ui._geometry_warnings(self.settings(.5))
        self.assertFalse(any('Vertex hole diameter' in x for x in warnings),warnings)

    def test_hole_greater_than_max_warns(self):
        messages = self.ui._geometry_warnings(self.settings(.71))
        self.assertTrue(any('7 mm' in x for x in messages),messages)
        self.assertTrue(self.ui._advisory_field_errors(self.settings(.71)).get('nodehole'))

    def test_exact_tangency_is_advisory(self):
        messages = self.ui._geometry_warnings(self.settings(.7))
        self.assertTrue(any('tangent' in x for x in messages),messages)
        self.assertFalse(self.ui._advisory_field_errors(self.settings(.7)).get('nodehole'))


if __name__=='__main__':
    unittest.main()
