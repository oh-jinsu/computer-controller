"""Startup screen access checks. OS calls are mocked; never reset real TCC permissions."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from mac_bridge import app_control, native

ROOT = Path(__file__).resolve().parents[1]


class ScreenPermissionStartupTests(unittest.TestCase):
    def call_helper(self, action, allowed):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'not-created'
            output = io.StringIO()
            with mock.patch('sys.argv', ['app_entry.py', action, '--data', str(data)]), \
                 mock.patch.object(native, 'screen_permission', return_value=allowed) as permission, \
                 redirect_stdout(output):
                self.assertEqual(app_control.main(), 0)
            self.assertFalse(data.exists(), 'Permission query must not create/edit app state')
            self.assertEqual(json.loads(output.getvalue()), {'screen_recording_allowed': allowed})
            permission.assert_called_once_with(request=action == 'permission')

    def test_preflight_allowed_without_prompt(self):
        self.call_helper('permission-status', True)

    def test_preflight_denied_never_prompts(self):
        self.call_helper('permission-status', False)

    def test_requested_allow_uses_system_api(self):
        self.call_helper('permission', True)

    def test_requested_denial_is_not_reported_as_allow(self):
        self.call_helper('permission', False)

    def test_query_failure_does_not_fabricate_permission(self):
        with mock.patch('sys.argv', ['app_entry.py', 'permission-status']), \
             mock.patch.object(native, 'screen_permission', side_effect=OSError('test failure')):
            with self.assertRaises(OSError):
                app_control.main()

    def test_native_read_uses_only_preflight(self):
        cg = mock.Mock()
        cg.CGPreflightScreenCaptureAccess.return_value = False
        with mock.patch.object(native, 'quartz', return_value=(cg, mock.Mock())):
            self.assertFalse(native.screen_permission())
        cg.CGPreflightScreenCaptureAccess.assert_called_once_with()
        cg.CGRequestScreenCaptureAccess.assert_not_called()
        cg.CGWindowListCopyWindowInfo.assert_not_called()

    def test_native_request_does_not_capture_or_enumerate(self):
        cg = mock.Mock()
        cg.CGRequestScreenCaptureAccess.return_value = False
        with mock.patch.object(native, 'quartz', return_value=(cg, mock.Mock())):
            self.assertFalse(native.screen_permission(request=True))
        cg.CGRequestScreenCaptureAccess.assert_called_once_with()
        cg.CGWindowListCopyWindowInfo.assert_not_called()

    def test_launch_and_manual_path_have_guards(self):
        swift = (ROOT / 'packaging/macos/MacBridge.swift').read_text()
        launch = swift.split('func applicationDidFinishLaunching', 1)[1].split('func buildWindow()', 1)[0]
        self.assertLess(launch.index('if noConnect {'), launch.index('checkScreenPermission()'))
        self.assertIn('guard !noConnect, screenStatusItem != nil, !screenPermissionBusy', swift)
        self.assertIn('checkScreenPermission(manual: true)', swift)
        self.assertIn('applicationDidBecomeActive', swift)
        self.assertIn('helper(["permission-status"])', swift)
        self.assertIn('if open { self.openScreenPermissionSettings() }', swift)
        self.assertLess(swift.index('defaults.set(true', swift.index('case .request:')),
                        swift.index('self.helper(["permission"])'))

    def test_policy_is_compiled_into_app(self):
        builder = (ROOT / 'packaging/scripts/build_app.py').read_text()
        self.assertIn('packaging/macos/ScreenPermissionPolicy.swift', builder)

    def test_no_system_permission_override(self):
        source = (ROOT / 'packaging/macos/MacBridge.swift').read_text()
        for forbidden in ['tccutil', 'TCC.db', 'AllFiles', 'ScreenCaptureAccess = true']:
            self.assertNotIn(forbidden, source)
        self.assertIn('value["screen_recording_allowed"] as? Bool', source)


if __name__ == '__main__':
    unittest.main()
