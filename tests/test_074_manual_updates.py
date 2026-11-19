"""Manual GitHub update checks bypass the auto cache and report their outcome."""
import pathlib
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import update_checker
from test_preview_lifecycle import load_fusion_ui

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ManualUpdateChecks(unittest.TestCase):
    def test_check_now_bypasses_cache_and_reports_current_version(self):
        complete = threading.Event()
        versions = iter(['0.7.4', '0.7.4'])
        calls = []
        def fetch():
            calls.append(True)
            return next(versions)
        checker = update_checker.UpdateChecker('0.7.4', complete.set,
            fetch=fetch, clock=lambda: 100, interval=3600)
        try:
            checker.check_on_open()
            self.assertTrue(complete.wait(2))
            self.assertEqual(checker.manual_status(), ('idle', None))
            complete.clear()
            self.assertTrue(checker.check_now())
            self.assertTrue(complete.wait(2))
            self.assertEqual(len(calls), 2)
            self.assertEqual(checker.manual_status(), ('current', '0.7.4'))
            self.assertIsNone(checker.available())
        finally:
            checker.close()

    def test_check_now_reports_new_version(self):
        complete = threading.Event()
        checker = update_checker.UpdateChecker('0.7.4', complete.set,
            fetch=lambda: '0.7.9')
        try:
            self.assertTrue(checker.check_now())
            self.assertTrue(complete.wait(2))
            self.assertEqual(checker.available(), '0.7.9')
            self.assertEqual(checker.manual_status(), ('available', '0.7.9'))
        finally:
            checker.close()

    def test_manual_failure_is_visible_while_auto_failure_is_silent(self):
        complete = threading.Event()
        def fail(): raise OSError('offline')
        checker = update_checker.UpdateChecker('0.7.4', complete.set,
            fetch=fail, clock=lambda: 100)
        try:
            checker.check_on_open()
            self.assertTrue(complete.wait(2))
            self.assertEqual(checker.manual_status(), ('idle', None))
            complete.clear()
            checker.check_now()
            self.assertTrue(complete.wait(2))
            self.assertEqual(checker.manual_status(), ('error', 'offline'))
        finally:
            checker.close()

    def test_click_during_auto_check_reuses_inflight_network_request(self):
        entered, release, completed = (threading.Event() for _ in range(3))
        calls = []
        def fetch():
            calls.append(1)
            entered.set()
            release.wait(2)
            return '0.7.4'
        checker = update_checker.UpdateChecker('0.7.4', completed.set,
            fetch=fetch)
        try:
            checker.check_on_open()
            self.assertTrue(entered.wait(2))
            self.assertTrue(checker.check_now())
            self.assertEqual(checker.manual_status(), ('checking', None))
            self.assertEqual(len(calls), 1)
            release.set()
            self.assertTrue(completed.wait(2))
            self.assertEqual(checker.manual_status(), ('current', '0.7.4'))
            self.assertEqual(len(calls), 1)
        finally:
            checker.close()
            release.set()


class ManualUpdateCommand(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_fusion_ui()

    def test_check_button_is_always_present(self):
        ui = self.ui
        command = MagicMock()
        with patch.object(ui.adsk.core, 'DropDownStyles',
                          SimpleNamespace(TextListDropDownStyle=0), create=True), \
             patch.object(ui.adsk.core, 'ValueInput', MagicMock(), create=True), \
             patch.object(ui, 'Session', return_value=SimpleNamespace()), \
             patch.object(ui, '_refresh_field_feedback'), \
             patch.object(ui, '_update_placement_visibility'), \
             patch.object(ui, '_update_checker', None), \
             patch.object(ui, 'UI', MagicMock()):
            before = len(ui._sessions)
            ui.CreatedHandler().notify(SimpleNamespace(command=command))
            del ui._sessions[before:]
        buttons = [call.args for call in command.commandInputs.addBoolValueInput.call_args_list]
        self.assertIn(('check_update', 'Check for Updates', False, '', False), buttons)

    def test_click_forces_check_resets_button_and_does_not_refresh_geometry(self):
        ui = self.ui
        button = SimpleNamespace(value=True)
        notice = SimpleNamespace(formattedText='', isVisible=False)
        install = SimpleNamespace(isVisible=False)
        widgets = {'check_update':button,'update_notice':notice,'install_update':install}
        inputs = SimpleNamespace(itemById=widgets.__getitem__)
        session = SimpleNamespace(alive=True, updating=False, inputs=inputs,
                                  _shown_update=None,
                                  request_preview=MagicMock(),
                                  invalidate_fits=MagicMock())
        checker = SimpleNamespace(check_now=MagicMock(return_value=True),
            available=lambda: None, manual_status=lambda: ('checking', None))
        event = SimpleNamespace(input=SimpleNamespace(id='check_update'), inputs=inputs)
        with patch.object(ui, '_update_checker', checker), \
             patch.object(ui, '_update_installer', None):
            ui.ChangedHandler(session).notify(event)
        checker.check_now.assert_called_once_with()
        self.assertFalse(button.value)
        self.assertFalse(session.updating)
        self.assertTrue(notice.isVisible)
        self.assertIn('Checking GitHub', notice.formattedText)
        session.request_preview.assert_not_called()
        session.invalidate_fits.assert_not_called()

    def test_ui_reports_current_and_failed_checks(self):
        ui = self.ui
        notice = SimpleNamespace(formattedText='', isVisible=False)
        button = SimpleNamespace(isVisible=False)
        widgets = {'update_notice':notice,'install_update':button}
        session = SimpleNamespace(alive=True, _shown_update=None,
                                  inputs=SimpleNamespace(itemById=widgets.__getitem__))
        status = [('current', '0.7.4')]
        checker = SimpleNamespace(available=lambda: None, manual_status=lambda: status[0])
        with patch.object(ui, '_update_checker', checker), \
             patch.object(ui, '_update_installer', None):
            ui._show_update_notice(session)
            self.assertIn('Up to date', notice.formattedText)
            self.assertTrue(notice.isVisible)
            self.assertFalse(button.isVisible)
            status[0] = ('error', 'offline')
            ui._show_update_notice(session)
            self.assertIn('offline', notice.formattedText)
            self.assertIn('failed', notice.formattedText)
            self.assertFalse(button.isVisible)


if __name__ == '__main__':
    unittest.main()
