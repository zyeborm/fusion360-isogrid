"""v0.7.2: nonzero vertex holes and one-shot computed maximum action."""
import json
import pathlib
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import geometry
from test_063_field_errors import Inputs, Units
from test_preview_lifecycle import load_fusion_ui

ROOT = pathlib.Path(__file__).resolve().parents[1]


class AutoVertexHoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_fusion_ui()

    def test_computed_maximum_uses_live_rib_and_corner_expressions(self):
        inputs = Inputs(rib='3 mm', corner='2 mm', nodehole='1 mm')
        with patch.object(self.ui, '_units_manager', return_value=Units()):
            result = self.ui._auto_vertex_hole(inputs)
        self.assertAlmostEqual(result, 1.0)  # internal cm: 10 mm
        self.assertEqual(inputs.itemById('nodehole').value, '10 mm')

    def test_default_dimensions_yield_7mm_maximum(self):
        inputs = Inputs(nodehole='5 mm')
        with patch.object(self.ui, '_units_manager', return_value=Units()):
            self.assertAlmostEqual(self.ui._auto_vertex_hole(inputs), .7)
        self.assertEqual(inputs.itemById('nodehole').value, '7 mm')
        self.assertAlmostEqual(geometry.maximum_vertex_hole_diameter(.2,.15), .7)

    def test_invalid_dimensions_leave_manually_entered_diameter_unchanged(self):
        for rib, corner in [('-1 mm','1 mm'), ('2 mm','-1 mm'), ('bad','1 mm')]:
            with self.subTest(rib=rib, corner=corner):
                inputs=Inputs(rib=rib, corner=corner, nodehole='4 mm')
                with patch.object(self.ui, '_units_manager', return_value=Units()):
                    with self.assertRaises(ValueError):
                        self.ui._auto_vertex_hole(inputs)
                self.assertEqual(inputs.itemById('nodehole').value, '4 mm')

    def test_auto_button_click_updates_preview_once_then_resets(self):
        inputs=Inputs(nodehole='4 mm', auto_nodehole=True, status='')
        session=SimpleNamespace(updating=False,
                                invalidate_fits=MagicMock(),
                                request_preview=MagicMock())
        event=SimpleNamespace(input=SimpleNamespace(id='auto_nodehole'), inputs=inputs)
        with patch.object(self.ui, '_units_manager', return_value=Units()), \
             patch.object(self.ui, '_refresh_field_feedback') as feedback:
            self.ui.ChangedHandler(session).notify(event)
        self.assertEqual(inputs.itemById('nodehole').value, '7 mm')
        self.assertFalse(inputs.itemById('auto_nodehole').value)
        self.assertFalse(session.updating)
        session.invalidate_fits.assert_called_once_with(inputs)
        session.request_preview.assert_called_once_with(inputs)
        feedback.assert_called_once_with(inputs)
        # The action does not bind hole diameter to later parameter changes.
        inputs.itemById('nodehole').value='3 mm'
        self.assertEqual(inputs.itemById('nodehole').value,'3 mm')

    def test_command_ui_creates_default_field_and_one_shot_button(self):
        command=MagicMock()
        command.commandInputs.addDropDownCommandInput.return_value.listItems=MagicMock()
        with patch.object(self.ui.adsk.core, 'DropDownStyles',
                          SimpleNamespace(TextListDropDownStyle=0), create=True), \
             patch.object(self.ui.adsk.core, 'ValueInput', MagicMock(), create=True), \
             patch.object(self.ui, 'Session', return_value=SimpleNamespace()), \
             patch.object(self.ui, '_refresh_field_feedback'), \
             patch.object(self.ui, '_update_placement_visibility'), \
             patch.object(self.ui, '_update_checker', None), \
             patch.object(self.ui, 'UI', MagicMock()):
            before=len(self.ui._sessions)
            self.ui.CreatedHandler().notify(SimpleNamespace(command=command))
            del self.ui._sessions[before:]
        string_calls=[c.args for c in command.commandInputs.addStringValueInput.call_args_list]
        self.assertIn(('nodehole', 'Vertex hole diameter (0 = off)', '5 mm'), string_calls)
        button_calls=[c.args for c in command.commandInputs.addBoolValueInput.call_args_list]
        self.assertIn(('auto_nodehole', 'Auto Max Hole', False, '', False), button_calls)
        self.assertEqual(json.loads((ROOT/'fusion360-isogrid.manifest').read_text())['version'],
                         self.ui.RUNNING_VERSION)


if __name__=='__main__':
    unittest.main()
