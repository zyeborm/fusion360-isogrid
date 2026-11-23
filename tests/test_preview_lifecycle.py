"""Simulated Fusion event-order tests; no Autodesk installation required."""
import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_fusion_ui(initialize=True):
    """Load actual command source against a minimal adsk namespace shim."""
    adsk = types.ModuleType('adsk')
    core = types.ModuleType('adsk.core')
    fusion = types.ModuleType('adsk.fusion')
    for name in ('CommandCreatedEventHandler', 'CommandEventHandler',
                 'InputChangedEventHandler', 'ValidateInputsEventHandler',
                 'CustomEventHandler'):
        setattr(core, name, type(name, (), {}))
    class Application:
        @staticmethod
        def get():
            return types.SimpleNamespace(userInterface=object(), log=lambda _: None)
    core.Application = Application
    adsk.core, adsk.fusion = core, fusion
    spec = importlib.util.spec_from_file_location('isogrid_fusion_lifecycle_test',
                                                  ROOT / 'fusion360-isogrid.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'adsk': adsk, 'adsk.core': core,
                                  'adsk.fusion': fusion}):
        spec.loader.exec_module(module)
    if initialize:
        module._load_runtime()
    return module


class Input:
    def __init__(self, value=None):
        self.value = value
        self.text = ''


class Inputs:
    def __init__(self, show=True):
        self.fields = {'show_preview': Input(show), 'status': Input(),
                       'activity': Input()}
    def itemById(self, name):
        return self.fields[name]


class PreviewLifecycleTests(unittest.TestCase):
    def test_import_only_registers_helpers_until_command_activation(self):
        ui=load_fusion_ui(initialize=False)
        self.assertFalse(ui._runtime_loaded)
        self.assertNotIn('geometry',ui.__dict__)
        self.assertNotIn('preview_timing',ui.__dict__)
        ui._load_runtime()
        self.assertTrue(ui._runtime_loaded)
        self.assertIs(ui.OffsetInterval,ui.offset_cleanup.OffsetInterval)
        initial=ui.geometry
        ui._load_runtime()
        self.assertIs(ui.geometry,initial)

    @classmethod
    def setUpClass(cls):
        cls.ui = load_fusion_ui()

    def session(self):
        session = self.ui.Session.__new__(self.ui.Session)
        session.alive = True
        session.updating = False
        session.fit_running = False
        session.last_signature = 'sig'
        session.cache_signature = 'sig'
        session.cache = ('face','profile','frame',{'depth':.2},[],['outline'])
        session.graphics = object()  # Simulate a stale Fusion-rolled-back group.
        session.inputs = Inputs()
        session._activity = lambda *args: None
        session.request_preview = lambda inputs: None
        session.clear_preview = lambda: None
        return session

    def test_execute_preview_recreates_graphics_after_rollback(self):
        session = self.session()
        calls = []
        args = types.SimpleNamespace(command=types.SimpleNamespace(
            commandInputs=session.inputs))
        with patch.object(self.ui, '_draw_preview',
                          side_effect=lambda s, data: calls.append(data)):
            session.preview(args)
            session.preview(args)  # Fusion has rolled back the first transaction.
        self.assertEqual(calls, [session.cache, session.cache])

    def test_worker_result_requests_execute_preview_instead_of_drawing(self):
        session = self.session()
        session.pending_kind = 'preview'
        session.revision = 7
        session.cache = None
        session.cache_signature = None
        session.snapshot = ('sig', ('face','profile','frame',{'depth':.2},[]), {})
        session.worker = types.SimpleNamespace(drain=lambda: [{
            'kind':'preview', 'revision':7, 'value':['new outline']}])
        session._preview_text = lambda inputs,data: None
        events = []
        in_preview = [False]
        args = types.SimpleNamespace(command=types.SimpleNamespace(
            commandInputs=session.inputs))
        def do_execute_preview():
            events.append('doExecutePreview')
            in_preview[0] = True
            session.preview(args)
            in_preview[0] = False
            return True
        session.command = types.SimpleNamespace(doExecutePreview=do_execute_preview)
        with patch.object(self.ui,'_inputs_to_settings',return_value={
                 'depth':.2,'depth_expression':'2 mm'}), patch.object(
                 self.ui, '_draw_preview', side_effect=lambda s,data:
                 events.append('draw inside executePreview' if in_preview[0]
                               else 'draw outside executePreview')):
            session.consume()
        self.assertEqual(events, ['doExecutePreview','draw inside executePreview'])
        self.assertEqual(session.cache[-1], ['new outline'])

    def test_hidden_preview_is_not_rendered(self):
        session = self.session()
        session.inputs.fields['show_preview'].value = False
        events = []
        session.clear_preview = lambda: events.append('clear')
        args = types.SimpleNamespace(command=types.SimpleNamespace(
            commandInputs=session.inputs))
        with patch.object(self.ui,'_draw_preview',side_effect=AssertionError('drawn')):
            session.preview(args)
        self.assertEqual(events,['clear'])


if __name__ == '__main__':
    unittest.main()
