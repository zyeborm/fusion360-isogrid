"""Version strings and command/update state without requiring Autodesk Fusion."""
import json
import pathlib
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import update_checker
from test_preview_lifecycle import load_fusion_ui

ROOT = pathlib.Path(__file__).resolve().parents[1]


class VersionVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_fusion_ui()

    def test_running_code_version_matches_manifest(self):
        manifest = json.loads((ROOT / 'fusion360-isogrid.manifest').read_text())
        self.assertEqual(self.ui.RUNNING_VERSION, manifest['version'])
        self.assertEqual(self.ui.COMMAND_TITLE,
                         f'fusion360-isogrid v{self.ui.RUNNING_VERSION}')

    def test_command_definition_uses_versioned_title(self):
        ui = self.ui
        fusion_ui = MagicMock()
        fusion_ui.commandDefinitions.itemById.return_value = None
        panel = fusion_ui.workspaces.itemById.return_value.toolbarPanels.itemById.return_value
        panel.controls.itemById.return_value = None
        app = MagicMock()
        app.registerCustomEvent.return_value = MagicMock()
        with patch.object(ui, 'UI', fusion_ui), patch.object(ui, 'APP', app), \
             patch.object(ui.importlib, 'reload', side_effect=lambda module: module), \
             patch.object(ui, '_update_checker', None), \
             patch.object(ui, '_update_installer', None):
            ui.run({})
        args = fusion_ui.commandDefinitions.addButtonDefinition.call_args.args
        self.assertEqual(args[:2], (ui.COMMAND_ID, ui.COMMAND_TITLE))

    def test_update_notice_shows_running_and_remote_versions(self):
        ui = self.ui
        notice = SimpleNamespace(formattedText='', isVisible=False)
        button = SimpleNamespace(isVisible=False)
        inputs = SimpleNamespace(itemById=lambda key: {
            'update_notice': notice, 'install_update': button}[key])
        session = SimpleNamespace(alive=True, inputs=inputs, _shown_update=None)
        checker = SimpleNamespace(available=lambda: '99.0.0',
                                  manual_status=lambda: ('idle', None))
        installer = SimpleNamespace(state=lambda: ('idle', None, None))
        with patch.object(ui, '_update_checker', checker), \
             patch.object(ui, '_update_installer', installer):
            ui._show_update_notice(session)
            self.assertTrue(notice.isVisible)
            self.assertTrue(button.isVisible)
            self.assertIn('v99.0.0', notice.formattedText)
            self.assertIn(f'v{ui.RUNNING_VERSION}', notice.formattedText)
            installer.state = lambda: ('installed', '99.0.0', None)
            ui._show_update_notice(session)
            self.assertTrue(notice.isVisible)
            self.assertFalse(button.isVisible)
            self.assertIn('Installed v99.0.0', notice.formattedText)
            self.assertIn(f'running v{ui.RUNNING_VERSION}', notice.formattedText)
            self.assertIn('Restart Fusion', notice.formattedText)

    def test_equal_remote_version_clears_old_available_notice(self):
        completed = threading.Event()
        time = [0]
        versions = iter(['0.6.8', '0.6.7'])
        checker = update_checker.UpdateChecker('0.6.7', completed.set,
            fetch=lambda: next(versions), clock=lambda: time[0], interval=1)
        try:
            checker.check_on_open()
            self.assertTrue(completed.wait(2))
            self.assertEqual(checker.available(), '0.6.8')
            time[0] += 2
            completed.clear()
            checker.check_on_open()
            self.assertTrue(completed.wait(2))
            self.assertIsNone(checker.available())
        finally:
            checker.close()


if __name__ == '__main__':
    unittest.main()