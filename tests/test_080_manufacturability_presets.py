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
            with self.assertRaises(ValueError):store.put('obsolete',{'min_web':'3 mm'})
            self.assertEqual(store.names(),[])

    def test_existing_v080_presets_drop_retired_fields_without_losing_others(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'presets.json'
            path.write_text(json.dumps({'version':1,'presets':{
                'CNC':{'rib':'2 mm','tool_diameter':'6 mm',
                       'stock_thickness':'8 mm','min_skin':'2 mm',
                       'min_web':'3 mm','min_pocket':'5 mm'},
                'Only legacy dimensions':{'min_web':'2 mm'}}}))
            store=presets.Store(path)
            self.assertEqual(store.names(),['CNC'])
            self.assertEqual(store.get('CNC'),{
                'rib':'2 mm','tool_diameter':'6 mm'})
            store.put('Printing',{'tool_diameter':'0 mm'})
            self.assertEqual(presets.Store(path).get('Printing'),
                             {'tool_diameter':'0 mm'})
            self.assertNotIn('min_web',json.loads(path.read_text())['presets']['CNC'])

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
    def test_zero_cutter_preserves_every_cut_and_skips_tool_checks(self):
        shapes=[cut(0,0,.2,.2),cut(.4,0,1.4,1.0),
                geometry.CutShape([],[],circle=((2.,2.),.03))]
        region=geometry.Region([(square(-10,-10,10,10),True)])
        settings=dict(rib=.1,perimeter=0.,holeclear=0.,tool_diameter=0.)
        with patch.object(m,'_can_fit_disk',side_effect=AssertionError(
                'Cutter 0 must not invoke cutter accessibility screening')):
            remaining,report=m.screen(shapes,[region],settings)
        self.assertIs(remaining,shapes)
        self.assertEqual(len(remaining),3)
        self.assertEqual(report.inaccessible_pockets,0)
        self.assertEqual(report.unmachinable_corners,0)
        self.assertFalse(report.cutter_shapes)

    def test_nonzero_cutter_reports_unmachinable_pockets_without_omission(self):
        shapes=[cut(0,0,.2,.2),cut(.4,0,1.4,1.0),
                geometry.CutShape([],[],circle=((2.,2.),.03))]
        region=geometry.Region([(square(-10,-10,10,10),True)])
        remaining,report=m.screen(shapes,[region],dict(
            rib=.1,perimeter=0.,holeclear=0.,tool_diameter=.4))
        self.assertIs(remaining,shapes)
        self.assertEqual(len(remaining),3)
        self.assertEqual(report.inaccessible_pockets,1)
        self.assertEqual(report.cutter_shapes,(0,))
        self.assertTrue(remaining[-1].circle)

    def test_unrounded_corner_is_cutter_warning_not_automatic_deletion(self):
        shape=cut(1,1,2,2)
        shape.fillet_warnings=2
        region=geometry.Region([(square(0,0,10,10),True)])
        actual,report=m.screen([shape],[region],dict(
            rib=.1,perimeter=.05,holeclear=.05,tool_diameter=.1))
        self.assertEqual(len(actual),1)
        self.assertEqual(report.unmachinable_corners,1)
        self.assertEqual(report.cutter_shapes,(0,))

    def test_detect_adjacent_pocket_web_and_preview_index(self):
        shapes=[cut(1,1,2,2),cut(2.1,1,3.1,2),cut(5,5,6,6)]
        region=geometry.Region([(square(0,0,10,10),True)])
        kept,report=m.screen(shapes,[region],dict(
            rib=.2,perimeter=.05,holeclear=.05))
        self.assertEqual(len(kept),3)
        self.assertEqual(report.narrow_web_count,1)
        self.assertEqual(report.web_shapes,(0,1))
        self.assertAlmostEqual(report.minimum_web_cm,.1,places=5)

    def test_detect_web_to_source_face_perimeter(self):
        shapes=[cut(.1,1,1,2),cut(3,3,4,4)]
        region=geometry.Region([(square(0,0,10,10),True)])
        _,report=m.screen(shapes,[region],dict(
            rib=.05,perimeter=.2,holeclear=.05))
        self.assertEqual(report.web_shapes,(0,))

    def test_sampled_boundary_tolerance_avoids_false_positives(self):
        # Source and output splines have independent polygonal approximations.
        # Their few-micron chord differences are not real design violations.
        region=geometry.Region([(square(0,0,10,10),True)])
        settings=dict(rib=.1,perimeter=.3,holeclear=.3,tool_diameter=0.)
        _,near=m.screen([cut(.299,2.,1.,3.)],[region],settings)
        self.assertEqual(near.narrow_web_count,0)
        _,genuine=m.screen([cut(.28,2.,1.,3.)],[region],settings)
        self.assertGreater(genuine.narrow_web_count,0)

    def test_void_clearance_is_independent_of_rib_width(self):
        shapes=[cut(3.7,4.5,3.85,5.5)]
        region=geometry.Region([(square(0,0,10,10),True),
                                (square(4,4,6,6)[::-1],False)])
        _,report=m.screen(shapes,[region],dict(
            rib=.05,perimeter=.05,holeclear=.2))
        self.assertEqual(report.web_shapes,(0,))

    def test_cutter_zero_and_nonzero_warn_without_rewriting_corner_radius(self):
        ui=load_fusion_ui()
        inputs=Inputs(corner='1.5 mm',tool_diameter='0 mm')
        with patch.object(ui,'_units_manager',return_value=Units()):
            settings=ui._inputs_to_settings(inputs)
            ui._validate_settings(settings)
            self.assertFalse(any('cutter' in x.lower()
                                 for x in ui._geometry_warnings(settings)))
        inputs.itemById('tool_diameter').value='6 mm'
        with patch.object(ui,'_units_manager',return_value=Units()):
            settings=ui._inputs_to_settings(inputs)
            ui._validate_settings(settings)
            self.assertAlmostEqual(settings['corner'],.15)
            self.assertTrue(any('cutter radius' in x
                                for x in ui._geometry_warnings(settings)))
        inputs.itemById('tool_diameter').value='-1 mm'
        with patch.object(ui,'_units_manager',return_value=Units()):
            settings=ui._inputs_to_settings(inputs)
            self.assertIn('Cutter diameter',self._validation_failure(ui,settings))

    def test_auto_vertex_hole_ignores_cutter_diameter(self):
        ui=load_fusion_ui()
        inputs=Inputs(corner='1.5 mm',rib='2 mm',tool_diameter='10 mm')
        with patch.object(ui,'_units_manager',return_value=Units()):
            new_diameter=ui._auto_vertex_hole(inputs)
        self.assertAlmostEqual(new_diameter,.3)

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
