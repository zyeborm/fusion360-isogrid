"""Regression for round-cutout and clipped-tip fillet failures (v0.7.0).

Source geometry reconstructed from the user's Sketch1.dxf.  Coordinates are
converted from DXF millimetres to Fusion database centimetres; the DXF bulge
is preserved as a true major circular arc, not tessellated for the solver.
These tests require only the Python standard library.
"""
import math
import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import curves2d as c
import exact_clipper as clip
import geometry as geo


# Vertices and bulge from Sketch1.dxf (in millimetres), then scaled to cm.
_DXF_PROFILE = [
    (0.0, 0.0),
    (38.7804430841028, 0.0),
    (54.497217379578515, 25.85362872273521),
    (54.497217379578515, 50.591273471827165),
    (20.366707518989248, 50.591273471827165),
    (0.0, 50.591273471827165),
    (-172.2737345717522, 50.591273471827165),
    (-172.2737345717522, 0.0),
]
_CUTOUT_BULGE = -1.1137778168200114
_CIRCLE_CENTER = (16.646760940178424 / 10, 10.880843743021664 / 10)
_CIRCLE_RADIUS = 2.9053711561547244 / 10


def test_panel():
    points = [(x / 10, y / 10) for x,y in _DXF_PROFILE]
    outer=[]
    for i,a in enumerate(points):
        b=points[(i+1)%len(points)]
        if i == 4:
            # Bulge theta = 4 atan(bulge), including major clockwise arcs.
            sweep=4*math.atan(_CUTOUT_BULGE)
            chord=c.sub(b,a)
            midpoint=c.mul(c.add(a,b),.5)
            # Circle centre along the left normal to the directed chord.
            h=c.length(chord)/(2*math.tan(abs(sweep)/2))
            direction=1 if sweep>0 else -1
            centre=c.add(midpoint,c.mul(c.normal(c.unit(chord)),direction*h))
            # The actual DXF centre is (10.1833537595,49.4918140543) mm.
            outer.append(c.Arc(centre,a,b,sweep))
        else:
            outer.append(c.Line(a,b))
    void=[c.circle(_CIRCLE_CENTER,_CIRCLE_RADIUS,False)]
    return clip.CurveRegion([(outer,True),(void,False)])


class ExactBoundaryFilletRegression(unittest.TestCase):
    def setUp(self):
        self.panel=test_panel()
        self.source=geo.Region(
            [(c.sample(path,.001),outer) for path,outer in self.panel.loops],
            curve_loops=[path for path,_ in self.panel.loops])
        self.prepared=geo.PreparedGeometry([self.source],.3,.3)

    def test_profile_contains_original_major_arc(self):
        perimeter=self.panel.loops[0][0]
        self.assertEqual(len(perimeter),8)
        self.assertTrue(c.close_loop(perimeter))
        self.assertEqual(sum(isinstance(s,c.Arc) for s in perimeter),1)
        arc=perimeter[4]
        self.assertLess(arc.sweep,-math.pi)
        self.assertAlmostEqual(arc.radius,1.0242534100596101,places=7)

    def test_full_pattern_has_no_unrounded_corners(self):
        shapes=geo.make_pockets([self.source],2,.2,.3,.3,0,0,0,.15,
                                prepared=self.prepared,max_cells=2500)
        self.assertEqual(len(shapes),68)
        self.assertEqual(sum(s.fillet_warnings for s in shapes),0)
        self.assertGreater(sum(isinstance(s,c.Arc) for shape in shapes
                               for loop in shape.curve_loops for s in loop),200)
        for shape in shapes:
            for loop in shape.curve_loops or []:
                self.assertTrue(c.close_loop(loop,2e-6))
                if c.loop_area(loop)<0:
                    continue  # protected hole: original circular geometry
                for i,seg in enumerate(loop):
                    following=loop[(i+1)%len(loop)]
                    self.assertGreater(c.dot(seg.tangent(1),following.tangent(0)),.99999)

    def test_round_by_opening_removes_clipped_tip_at_full_radius(self):
        box=geo.face_bounds([self.source])
        origin=geo.lattice_origin(box,2,0,0,0,None,'vertex')
        candidates=list(geo.lattice_pockets(box,2,.2,origin,0,0,2500))
        # Original v0.7.0 failed at these five retained cells (6 sharp corners).
        for index in (20,27,51,73,92):
            raw=next(loop for loop in self.prepared.clip(candidates[index])
                     if c.loop_area(loop)>0)
            old_warnings=[]
            clip.fillet_loop(raw,.15,old_warnings)
            self.assertTrue(old_warnings,index)
            fixed_warnings=[]
            result=clip.rounded_pocket(raw,.15,fixed_warnings)
            self.assertFalse(fixed_warnings,index)
            self.assertTrue(c.close_loop(result,2e-6))
            self.assertLessEqual(c.loop_area(result),c.loop_area(raw)+1e-7)
            for i,edge in enumerate(result):
                following=result[(i+1)%len(result)]
                self.assertGreater(c.dot(edge.tangent(1),following.tangent(0)),.99999)
                if isinstance(edge,c.Arc) and edge.sweep>0:
                    self.assertAlmostEqual(edge.radius,.15,places=6)

    def test_physically_impossible_radius_keeps_advisory(self):
        # A 0.3 cm triangle has no centre at least 0.15 cm from every edge.
        triangle=[c.Line((0,0),(.3,0)),c.Line((.3,0),(.15,.2598076211)),
                  c.Line((.15,.2598076211),(0,0))]
        warnings=[]
        result=clip.rounded_pocket(triangle,.15,warnings)
        self.assertTrue(warnings)
        self.assertTrue(c.close_loop(result))


if __name__=='__main__':unittest.main()
