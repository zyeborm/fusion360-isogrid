"""Saved-mass estimate and cancellable exact preview (Fusion-independent)."""
import pathlib
import sys
import unittest
from types import SimpleNamespace as NS

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import geometry
import saved_mass
from test_curved_dxf_regression import test_regions


class SavedMassTests(unittest.TestCase):
    def test_removed_area_counts_pockets_and_vertex_holes(self):
        outer=[(0.,0.),(2.,0.),(0.,2.)]  # 2 cm²
        circle=NS(circle=((3.,3.),.5),loops=[])
        pocket=NS(circle=None,loops=[outer])
        area=2.+3.141592653589793*.25
        self.assertAlmostEqual(saved_mass.removed_area_cm2([pocket,circle]),area)
        self.assertAlmostEqual(saved_mass.saved_volume_cm3([pocket,circle],.2),area*.2)
        self.assertAlmostEqual(saved_mass.saved_mass_g([pocket,circle],.2,'Aluminium'),area*.2*2.7)

    def test_protected_island_reduces_removed_volume(self):
        outer=[(0.,0.),(4.,0.),(4.,4.),(0.,4.)]
        island=[(1.,1.),(1.,2.),(2.,2.),(2.,1.)]  # CW; subtract 1 cm²
        pocket=NS(circle=None,loops=[outer,island])
        self.assertAlmostEqual(saved_mass.removed_area_cm2([pocket]),15.)

    def test_materials_and_custom_density(self):
        self.assertEqual(saved_mass.density('Aluminium'),2.7)
        self.assertEqual(saved_mass.density('Steel'),7.85)
        self.assertEqual(saved_mass.density('UHMW'),.93)
        self.assertEqual(saved_mass.density('1'),1.)
        self.assertEqual(saved_mass.density('User','1.42'),1.42)
        for invalid in ('0','-2','NaN','inf','hello'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                saved_mass.density('User',invalid)


class CancellationTests(unittest.TestCase):
    def test_exact_generation_aborts_between_clipped_cells(self):
        region=geometry.Region([([(0.,0.),(20.,0.),(20.,10.),(0.,10.)],True)])
        class Superseded(Exception):pass
        checked=[0]
        def cancel():
            checked[0]+=1
            if checked[0]>=5:raise Superseded()
        with self.assertRaises(Superseded):
            geometry.make_pockets([region],2.,.2,.2,.2,0.,0.,0.,.15,
                                  check_cancel=cancel,max_cells=1600)
        self.assertEqual(checked[0],5)


if __name__=='__main__':unittest.main()
