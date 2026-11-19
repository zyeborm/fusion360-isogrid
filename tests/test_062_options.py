"""v0.6.2: advisory-only constraints, raw lattice and clipped-pocket preservation."""
import math
import unittest
from types import SimpleNamespace

import geometry
from test_preview_lifecycle import load_fusion_ui


class OptionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_fusion_ui()
        cls.region = geometry.Region([
            ([(0, 0), (10, 0), (10, 10), (0, 10)], True),
            ([(5 + 0.6*math.cos(i*math.tau/64),
               5 + 0.6*math.sin(i*math.tau/64)) for i in range(64)], False),
        ])

    def test_validate_handler_does_not_block_geometrically_invalid_values(self):
        args = SimpleNamespace(areInputsValid=False)
        self.ui.ValidateHandler().notify(args)
        self.assertTrue(args.areInputsValid)

    def test_oversized_vertex_hole_warns_without_failing_geometry(self):
        data = {'pitch': 2, 'rib': .2, 'corner': .1,
                'nodehole': .7, 'depth': .2, 'perimeter': .1,
                'holeclear': .2, 'minfraction': 5, 'trim_boundary': True}
        message = ' '.join(self.ui._geometry_warnings(data))
        self.assertIn('rounded-pocket contact limit', message)
        shapes = geometry.make_pockets([self.region], 2, .2, .1, .2,
             0, 0, 0, .1, vertex_hole_diameter=.5, backend='python')
        self.assertGreater(len(shapes), 0)

    def test_raw_grid_does_not_clip_face_holes_or_perimeter(self):
        args = ([self.region], 2, .2, .3, .4, 0, 0, 12, .1)
        trimmed = geometry.make_pockets(*args, backend='python', trim_boundary=True)
        raw = geometry.make_pockets(*args, backend='python', trim_boundary=False)
        self.assertGreater(len(raw), len(trimmed))
        self.assertTrue(any(not self.region.contains(p) for shape in raw
                            for loop in shape.loops for p in loop))
        self.assertTrue(all(self.region.contains(p) for shape in trimmed
                            for loop in shape.loops for p in loop))

    def test_raw_mode_emits_circles_across_exclusions(self):
        kw=dict(vertex_hole_diameter=.2, backend='python')
        trimmed=geometry.make_pockets([self.region], 2, .2, .3, .4,
                                     0, 0, 0, .1, trim_boundary=True, **kw)
        raw=geometry.make_pockets([self.region], 2, .2, .3, .4,
                                 0, 0, 0, .1, trim_boundary=False, **kw)
        self.assertGreater(sum(bool(x.circle) for x in raw),
                           sum(bool(x.circle) for x in trimmed))

    def test_tight_fillet_keeps_usable_pocket_with_advisory(self):
        # 99% of the pocket remains, but one very short edge forces one radius
        # to be omitted rather than discarding the entire clipped contour.
        poly=[(0,0),(3,0),(3,2),(2.999,2.001),(0,2)]
        flags=[]
        output=geometry.round_clipped_contour(poly,.25,warnings=flags)
        self.assertGreater(geometry.area(output),.95*geometry.area(poly))
        self.assertTrue(flags)
        self.assertGreater(len(output),5)

    def test_backend_agreement_untrimmed_without_compiled_dependency(self):
        kwargs=dict(vertex_hole_diameter=.25,trim_boundary=False)
        a=geometry.make_pockets([self.region], 2, .2, .3, .3,
                                0, 0, 15, .1, backend='python',**kwargs)
        b=geometry.make_pockets([self.region], 2, .2, .3, .3,
                                0, 0, 15, .1, backend='geos',**kwargs)
        self.assertAlmostEqual(sum(sum(geometry.area(p) for p in x.loops) for x in a),
                               sum(sum(geometry.area(p) for p in x.loops) for x in b),
                               places=7)


if __name__=='__main__': unittest.main()
