"""Regress Fusion's SDK restriction on collapsibility of nested groups.

Autodesk GroupCommandInput.isExpanded:
If a group is nested and has no enable checkbox, it must stay expanded.
Test the *actual AST statements* from CreatedHandler.notify against a strict
mock, rather than duplicating their implementation.
"""
import ast
from pathlib import Path
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Input:
    def __init__(self, key, parent=None):
        self.id=key
        self.parent=parent
        self.listItems=[]
        self.isExpanded=True


class Group(Input):
    def __init__(self, key, parent=None):
        self._expanded=True
        self.isEnabledCheckBoxDisplayed=False
        super().__init__(key,parent)
        self.children=Inputs(self)

    @property
    def isExpanded(self):
        return self._expanded

    @isExpanded.setter
    def isExpanded(self,value):
        if self.parent is not None and not value and not self.isEnabledCheckBoxDisplayed:
            raise RuntimeError('3 : the group cannot be folded')
        self._expanded=value


class Inputs:
    def __init__(self,parent=None):
        self.parent=parent
        self.items={}

    def addGroupCommandInput(self,key,title):
        obj=Group(key,self.parent)
        self.items[key]=obj
        return obj

    def addDropDownCommandInput(self,key,title,style):
        obj=Input(key,self.parent);self.items[key]=obj;return obj

    def addStringValueInput(self,key,title,value):
        obj=Input(key,self.parent);self.items[key]=obj;return obj

    def addBoolValueInput(self,key,title,is_checkbox,icon,value):
        obj=Input(key,self.parent);self.items[key]=obj;return obj

    def addTextBoxCommandInput(self,key,title,body,rows,readonly):
        obj=Input(key,self.parent);self.items[key]=obj;return obj


class PresetGroupConstructionTests(unittest.TestCase):
    def test_nested_group_is_expanded_while_outer_group_can_fold(self):
        import sys
        sys.path.insert(0,str(ROOT))
        import presets
        source=(ROOT/'fusion360-isogrid.py').read_text(encoding='utf-8')
        tree=ast.parse(source)
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef)
                 and n.name=='CreatedHandler')
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='notify')
        # The command's UI construction occurs inside its try: block.
        body=next(n for n in fn.body if isinstance(n,ast.Try)).body
        start=next(i for i,n in enumerate(body)
                   if isinstance(n,ast.Assign) and any(
                   isinstance(t,ast.Name) and t.id=='preset_group'
                   for t in n.targets))
        end=next(i for i,n in enumerate(body[start:],start)
                 if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
                 and isinstance(n.value.func,ast.Attribute)
                 and n.value.func.attr=='addTextBoxCommandInput'
                 and n.value.args and isinstance(n.value.args[0],ast.Constant)
                 and n.value.args[0].value=='preset_status')
        statements=body[start:end+1]
        isolated=ast.fix_missing_locations(ast.Module(body=statements,type_ignores=[]))
        inputs=Inputs()
        core=types.SimpleNamespace(DropDownStyles=types.SimpleNamespace(
            TextListDropDownStyle=object()))
        adsk=types.SimpleNamespace(core=core)
        env={'inputs':inputs,'adsk':adsk,'presets':presets}
        exec(compile(isolated,'fusion360-isogrid.py','exec'),env)
        outer=inputs.items['preset_group']
        inner=outer.children.items['preset_fields_group']
        self.assertFalse(outer.isExpanded)
        self.assertTrue(inner.isExpanded)
        self.assertEqual(len(inner.children.items),len(presets.FIELDS))
        with self.assertRaisesRegex(RuntimeError,'cannot be folded'):
            inner.isExpanded=False


if __name__=='__main__': unittest.main()
