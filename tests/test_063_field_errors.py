"""Fusion-native per-field error flags, with explanatory non-blocking warnings."""
import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from test_preview_lifecycle import load_fusion_ui


class Field:
    def __init__(self, name, value):
        self.name = name
        self.value = value
        self.isValueError = False
        self.text = ''
        self.expression = str(value)
        self.selectedItem = SimpleNamespace(name='Automatic')


class Inputs:
    def __init__(self, **overrides):
        defaults = {
            'pitch': '20 mm', 'rib': '2 mm', 'depth': .2,
            'perimeter': '3 mm', 'holeclear': '3 mm',
            'dx': 0., 'dy': 0., 'angle': 0.,
            'corner': '1.5 mm', 'nodehole': '0 mm', 'minfraction': '5',
            'fit_min_pitch': '16 mm', 'fit_max_pitch': '28 mm',
            'trim_boundary': True, 'origin_mode': 'Automatic',
            'anchor': 'Automatic', 'alignment': 'Automatic',
            'backend_choice': 'Automatic', 'warnings': '',
        }
        defaults.update(overrides)
        self.fields = {k: Field(k, v) for k, v in defaults.items()}
    def itemById(self, key):
        return self.fields[key]


class Units:
    def isValidExpression(self, text, unit):
        try:
            self.evaluateExpression(text, unit)
            return True
        except ValueError:
            return False

    def evaluateExpression(self, text, unit):
        # Simulate Fusion's centimetre database units; no native parser here.
        text = str(text).strip()
        if text.endswith(' * 1 mm') and text.startswith('('):
            return self.evaluateExpression(text[1:-8], 'mm')
        m = re.fullmatch(r'(-?\d+(?:\.\d+)?)\s*(mm|cm)?', text)
        if not m:
            raise ValueError('bad expression')
        value = float(m.group(1))
        suffix = m.group(2) or unit
        if suffix == 'mm':
            value /= 10
        return value

    def formatInternalValue(self, value, unit, show_units):
        if unit == 'mm':
            return f'{value * 10:g} mm'
        return f'{value:g}'


class ErrorHighlightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_fusion_ui()

    def refresh(self, inputs):
        with patch.object(self.ui, '_units_manager', return_value=Units()):
            self.ui._refresh_field_feedback(inputs)

    def test_vertex_hole_warning_keeps_ok_enabled(self):
        inputs = Inputs(nodehole='9 mm')
        inputs.itemById('nodehole').isValueError = True  # stale earlier state
        self.refresh(inputs)
        self.assertFalse(inputs.itemById('nodehole').isValueError)
        self.assertIn('Check Geometry warnings', inputs.itemById('nodehole').tooltip)
        self.assertIn('Vertex hole diameter', inputs.itemById('warnings').text)
        args = SimpleNamespace(inputs=inputs, areInputsValid=False)
        with patch.object(self.ui, '_units_manager', return_value=Units()):
            self.ui.ValidateHandler().notify(args)
        self.assertTrue(args.areInputsValid)

    def test_too_thick_rib_marks_both_contributing_fields(self):
        inputs = Inputs(pitch='20 mm', rib='15 mm')
        self.refresh(inputs)
        self.assertFalse(inputs.itemById('pitch').isValueError)
        self.assertFalse(inputs.itemById('rib').isValueError)
        self.assertTrue(inputs.itemById('rib').tooltip)
        self.assertIn('Rib width', inputs.itemById('warnings').text)

    def test_corner_radius_shows_tooltip_without_native_error(self):
        inputs = Inputs(corner='8 mm')
        self.refresh(inputs)
        self.assertFalse(inputs.itemById('corner').isValueError)
        self.assertTrue(inputs.itemById('corner').tooltip)
        self.assertFalse(inputs.itemById('nodehole').isValueError)

    def test_bad_expression_highlights_field_and_reports_it(self):
        inputs = Inputs(rib='a very bad expression')
        self.refresh(inputs)
        self.assertFalse(inputs.itemById('rib').isValueError)
        self.assertIn('rib: invalid expression', inputs.itemById('warnings').text)

    def test_highlight_is_removed_when_values_are_corrected(self):
        inputs = Inputs(nodehole='8 mm')
        self.refresh(inputs)
        self.assertTrue(inputs.itemById('nodehole').tooltip)
        inputs.itemById('nodehole').value='1 mm'
        self.refresh(inputs)
        self.assertFalse(inputs.itemById('nodehole').isValueError)
        self.assertEqual(inputs.itemById('nodehole').tooltip,'')
        self.assertEqual(inputs.itemById('warnings').text,'No geometric warnings.')

    def test_bad_fit_limits_flag_both_fields(self):
        inputs = Inputs(fit_min_pitch='28 mm',fit_max_pitch='16 mm')
        self.refresh(inputs)
        self.assertFalse(inputs.itemById('fit_min_pitch').isValueError)
        self.assertFalse(inputs.itemById('fit_max_pitch').isValueError)
        self.assertTrue(inputs.itemById('fit_min_pitch').tooltip)
        self.assertIn('minimum < maximum', inputs.itemById('warnings').text)

    def test_optimiser_update_keeps_unit_expressions(self):
        inputs = Inputs()
        with patch.object(self.ui, '_units_manager', return_value=Units()):
            self.ui._set_input_number(inputs,'pitch',2.43)
        self.assertEqual(inputs.itemById('pitch').value,'24.3 mm')

    def test_area_percentage_remains_unitless(self):
        inputs = Inputs(minfraction='5')
        with patch.object(self.ui, '_units_manager', return_value=Units()):
            settings = self.ui._inputs_to_settings(inputs)
        self.assertEqual(settings['minfraction'], 5)


if __name__ == '__main__':
    unittest.main()
