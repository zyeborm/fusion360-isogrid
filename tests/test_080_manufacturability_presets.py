"""v0.8: Optional geometry-based manufacturing screening and sparse presets."""
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import geometry
import manufacturability as m
import presets
from test_preview_lifecycle import load_fusion_ui
from test_063_field_errors import Inputs, Units


def square(x0,y0,x1,y1):
    return [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]


def cut(x0,y0,x1,y1):
    p=square(x0,y0,x1,y1)
    return geometry.CutShape(p,[p])


class PresetTests(unittest.TestCase):
    def test_sparse_named_preset_roundtrip_preserves_expressions(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'nested'/'presets.json'
            store=presets.Store(path)
            store.put('Aluminium / 6 mm',{
                'tool_diameter':'6 mm','rib':'2 * wall_width',
                'trim_boundary':True,'anchor':'Grid vertex'})
            copy=presets.Store(path)
            self.assertEqual(copy.names(),['Aluminium / 6 mm'])
            self.assertEqual(copy.get('Aluminium / 6 mm')['rib'],'2 * wall_width')
            self.assertNotIn('pitch',copy.get('Aluminium / 6 mm'))
            self.assertEqual(json.loads(path.read_text())['version'],1)
            copy.put('Only corners',{'corner':'3.5 mm'})
            self.assertEqual(len(presets.Store(path).get('Only corners')),1)
            copy.delete('Aluminium / 6 mm')
            self.assertEqual(copy.names(),['Only corners'])

    def test_invalid_or_empty_presets_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            store=presets.Store(Path(temp)/'presets.json')
            with self.assertRaises(ValueError):store.put('empty',{})
            with self.assertRaises(ValueError):store.put('unknown',{'source_face':'token'})
            with self.assertRaises(ValueError):store.put('bad',{'trim_boundary':'true'})
            self.assertEqual(store.names(),[])

    def test_native_field_application_preserves_unselected_values(self):
        ui=load_fusion_ui()
        inputs=Inputs()
        current_pitch=inputs.itemById('pitch').value
        ui._set_preset_field(inputs,'rib','5 mm')
        ui._set_preset_field(inputs,'tool_diameter','8 mm')
        ui._set_preset_field(inputs,'trim_boundary',False)
        self.assertEqual(inputs.itemById('pitch').value,current_pitch)
        self.assertEqual(inputs.itemById('rib').value,'5 mm')
        self.assertEqual(inputs.itemById('tool_diameter').value,'8 mm')
        self.assertFalse(inputs.itemById('trim_boundary').value)


class ManufacturingTests(unittest.TestCase):
    def test_effective_ribs_and_corner_follow_optional_limits(self):
        original=dict(rib=.2,perimeter=.3,holeclear=.1,corner=.1,
                      min_web=.4,tool_diameter=.6)
        self.assertEqual(m.effective(original),(.4,.4,.4,.3))
        original.update(min_web=0,tool_diameter=0)
        self.assertEqual(m.effective(original),(.2,.3,.1,.1))

    def test_usable_pocket_diameter_excludes_only_small_islands(self):
        shapes=[cut(0,0,.2,.2),cut(.4,0,1.4,1.0),
                geometry.CutShape([],[],circle=((2.,2.),.03))]
        region=geometry.Region([(square(-10,-10,10,10),True)])
        remaining,report=m.screen(shapes,[region],{'min_pocket':.4})
        self.assertEqual(report.omitted,1)
        self.assertEqual(len(remaining),2)
        self.assertTrue(remaining[-1].circle)

    def test_detect_adjacent_pocket_web_and_preview_index(self):
        shapes=[cut(1,1,2,2),cut(2.1,1,3.1,2),cut(5,5,6,6)]
        region=geometry.Region([(square(0,0,10,10),True)])
        kept,report=m.screen(shapes,[region],{'min_web':.2})
        self.assertEqual(len(kept),3)
        self.assertEqual(report.narrow_web_count,1)
        self.assertEqual(report.web_shapes,(0,1))
        self.assertAlmostEqual(report.minimum_web_cm,.1,places=5)

    def test_detect_web_to_source_face_perimeter(self):
        shapes=[cut(.1,1,1,2),cut(3,3,4,4)]
        region=geometry.Region([(square(0,0,10,10),True)])
        _,report=m.screen(shapes,[region],{'min_web':.2})
        self.assertEqual(report.web_shapes,(0,))

    def test_minimum_skin_is_checked_using_supplied_uniform_thickness(self):
        ui=load_fusion_ui()
        inputs=Inputs(stock_thickness='4 mm',min_skin='2 mm',depth=.3)
        with patch.object(ui,'_units_manager',return_value=Units()):
            settings=ui._inputs_to_settings(inputs)
            self.assertIn('minimum remaining skin',
                self._validation_failure(ui,settings))
        inputs.itemById('depth').value=.1
        with patch.object(ui,'_units_manager',return_value=Units()):
            settings=ui._inputs_to_settings(inputs)
            ui._validate_settings(settings)

    @staticmethod
    def _validation_failure(ui,settings):
        try:ui._validate_settings(settings)
        except ValueError as exc:return str(exc)
        return ''


if __name__=='__main__':unittest.main()

class PresetCommandTests(unittest.TestCase):
    def test_preset_input_resolves_nested_groups(self):
        from types import SimpleNamespace
        ui=load_fusion_ui()
        def children(fields):
            return SimpleNamespace(itemById=lambda key:fields.get(key))
        innermost=children({'preset_include_rib':SimpleNamespace(value=True)})
        nested=children({'preset_fields_group':SimpleNamespace(children=innermost),
                         'preset_name':SimpleNamespace(value='Only ribs')})
        root=children({'preset_group':SimpleNamespace(children=nested)})
        self.assertTrue(ui._preset_input(root,'preset_include_rib').value)
        self.assertEqual(ui._preset_input(root,'preset_name').value,'Only ribs')

    def test_save_and_apply_subset_through_command_event(self):
        from types import SimpleNamespace
        from test_063_field_errors import Field
        ui=load_fusion_ui()
        inputs=Inputs()
        class ListItems:
            def __init__(self,owner):self.owner=owner;self.items=[]
            def clear(self):self.items=[]
            def add(self,name,selected=False):
                item=SimpleNamespace(name=name,isSelected=selected)
                self.items.append(item)
                if selected:self.owner.selectedItem=item
                return item
            def itemByName(self,name):
                return next((i for i in self.items if i.name==name),None)
        for key,value in [('preset_choice',''),('preset_name','My cutter'),
                          ('preset_status',''),('preset_save',False),
                          ('preset_delete',False)]:
            inputs.fields[key]=Field(key,value)
        inputs.itemById('preset_choice').listItems=ListItems(inputs.itemById('preset_choice'))
        for key in presets.FIELDS:
            inputs.fields['preset_include_'+key]=Field(key, key in ('corner','tool_diameter'))
        with tempfile.TemporaryDirectory() as temp:
            store=presets.Store(Path(temp)/'presets.json')
            calls=[]
            session=SimpleNamespace(updating=False,presets=store,
                invalidate_fits=lambda inputs:calls.append('fits'),
                request_preview=lambda inputs:calls.append('preview'))
            handler=ui.ChangedHandler(session)
            inputs.itemById('corner').value='4 mm'
            inputs.itemById('tool_diameter').value='6 mm'
            inputs.itemById('preset_save').value=True
            args=SimpleNamespace(inputs=inputs,input=SimpleNamespace(id='preset_save'))
            with patch.object(ui,'_units_manager',return_value=Units()):
                handler.notify(args)
            self.assertEqual(store.get('My cutter'),
                             {'corner':'4 mm','tool_diameter':'6 mm'})
            self.assertFalse(inputs.itemById('preset_save').value)
            self.assertFalse(calls)
            inputs.itemById('corner').value='1 mm'
            inputs.itemById('tool_diameter').value='0 mm'
            inputs.itemById('rib').value='2 mm'
            args.input.id='preset_choice'
            with patch.object(ui,'_units_manager',return_value=Units()), \
                 patch.object(ui,'_update_placement_visibility',lambda inputs:None):
                handler.notify(args)
            self.assertEqual(inputs.itemById('corner').value,'4 mm')
            self.assertEqual(inputs.itemById('tool_diameter').value,'6 mm')
            self.assertEqual(inputs.itemById('rib').value,'2 mm')
            self.assertEqual(calls,['fits','preview'])

