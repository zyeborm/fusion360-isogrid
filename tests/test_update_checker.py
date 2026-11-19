"""On-demand update checks have no Autodesk Fusion dependency."""
import json
import threading
import time
import unittest
from unittest.mock import patch

import update_checker


class VersionTests(unittest.TestCase):
    def test_version_comparison(self):
        self.assertTrue(update_checker.newer_version('0.6.3', '0.6.4'))
        self.assertTrue(update_checker.newer_version('0.6.3', '1.0.0'))
        self.assertFalse(update_checker.newer_version('0.6.4', '0.6.4'))
        self.assertFalse(update_checker.newer_version('1.0.0', '0.9.999'))
        self.assertTrue(update_checker.newer_version('0.6.4', 'v0.7.0'))
        self.assertFalse(update_checker.newer_version('0.6.4', 'release-v2'))
        self.assertFalse(update_checker.newer_version('broken', '2.0.0'))
        self.assertFalse(update_checker.newer_version('0.6.4', '0.6.5-beta'))

    def test_fetch_manifest_version(self):
        class FakeResponse:
            def __init__(self, data): self.data = data
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, size): return self.data[:size]
        body = json.dumps({'version': '0.6.5'}).encode()
        with patch.object(update_checker, 'urlopen', return_value=FakeResponse(body)) as stub:
            self.assertEqual(update_checker.fetch_remote_version(), '0.6.5')
            self.assertEqual(stub.call_args.kwargs['timeout'], 4)
        with patch.object(update_checker, 'urlopen', return_value=FakeResponse(b'{bad')):
            with self.assertRaises(ValueError):
                update_checker.fetch_remote_version()
        with patch.object(update_checker, 'urlopen', return_value=FakeResponse(b'0' * 16385)):
            with self.assertRaises(ValueError):
                update_checker.fetch_remote_version()


class CheckTests(unittest.TestCase):
    def test_only_on_open_with_cache(self):
        calls = []
        ready = threading.Event()
        now = [100.0]
        def fetch():
            calls.append('fetch')
            return '0.6.5'
        checker = update_checker.UpdateChecker(
            '0.6.4', ready.set, fetch=fetch, clock=lambda: now[0], interval=60)
        try:
            self.assertIsNone(checker.check_on_open())
            self.assertTrue(ready.wait(2))
            self.assertEqual(checker.available(), '0.6.5')
            self.assertEqual(checker.check_on_open(), '0.6.5')
            self.assertEqual(len(calls), 1)
            ready.clear()
            now[0] += 61
            self.assertEqual(checker.check_on_open(), '0.6.5')
            self.assertTrue(ready.wait(2))
            self.assertEqual(len(calls), 2)
        finally:
            checker.close()

    def test_late_completion_after_shutdown_ignored(self):
        unblock = threading.Event()
        entered = threading.Event()
        called = threading.Event()
        def fetch():
            entered.set()
            unblock.wait(2)
            return '10.0.0'
        checker = update_checker.UpdateChecker('0.6.4', called.set, fetch=fetch)
        checker.check_on_open()
        self.assertTrue(entered.wait(2))
        checker.close()
        unblock.set()
        self.assertFalse(called.wait(.05))
        self.assertIsNone(checker.available())

    def test_failure_quiet_and_cached(self):
        complete = threading.Event()
        calls = []
        def fail():
            calls.append('called')
            raise OSError('offline')
        checker = update_checker.UpdateChecker('0.6.4', complete.set, fetch=fail)
        try:
            checker.check_on_open()
            self.assertTrue(complete.wait(2))
            self.assertIsNone(checker.available())
            checker.check_on_open()
            self.assertEqual(len(calls), 1)
        finally:
            checker.close()

    def test_at_most_one_simultaneous_http_request(self):
        entered, release, complete = threading.Event(), threading.Event(), threading.Event()
        calls = []
        def fetch():
            calls.append(1)
            entered.set()
            release.wait(2)
            return '0.6.5'
        checker = update_checker.UpdateChecker('0.6.4', complete.set, fetch=fetch)
        try:
            checker.check_on_open()
            self.assertTrue(entered.wait(2))
            for _ in range(25): checker.check_on_open()
            self.assertEqual(len(calls), 1)
            release.set()
            self.assertTrue(complete.wait(2))
        finally:
            checker.close()


if __name__ == '__main__':
    unittest.main()
