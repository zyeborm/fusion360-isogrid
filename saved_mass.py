"""Nominal isogrid pocket volume and removed mass, in Fusion internal cm units.

The estimate uses the same accepted cut contours as the final sketch. It is
based on constant depth and assumes the cuts remain wholly inside the solid;
no expensive B-Rep boolean is required while choosing fits.
"""
import math
import geometry

DENSITY_G_CM3 = {
    'Aluminium': 2.70,
    'Steel': 7.85,
    'UHMW': 0.93,
    '1': 1.0,
}


def density(material, custom=None):
    """Density in g/cm³, allowing user entry only for the User selection."""
    if material == 'User':
        try:
            value = float(custom)
        except (ValueError, TypeError) as exc:
            raise ValueError('Enter a valid density in g/cm³.') from exc
        if not math.isfinite(value) or value <= 0:
            raise ValueError('Density must be a positive finite number.')
        return value
    return DENSITY_G_CM3[material]


def removed_area_cm2(shapes):
    """Add accepted pocket areas, subtracting protected holes in each island."""
    total = 0.
    for shape in shapes:
        if shape.circle is not None:
            total += math.pi * shape.circle[1]**2
        else:
            total += sum(geometry.area(loop) for loop in shape.loops)
    return max(0., total)


def saved_volume_cm3(shapes, depth_cm):
    if depth_cm < 0 or not math.isfinite(depth_cm):
        raise ValueError('Depth must be non-negative and finite.')
    return removed_area_cm2(shapes) * depth_cm


def saved_mass_g(shapes, depth_cm, material, custom=None):
    return saved_volume_cm3(shapes,depth_cm) * density(material,custom)
