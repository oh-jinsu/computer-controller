from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from mac_bridge import browser_connection as bc
from mac_bridge import credentials
from mac_bridge import platform_support as ps


class LinuxPortabilityTests(unittest.TestCase):
    def test_linux_data_path_uses_xdg_and_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as tmp,              mock.patch.object(ps, 'IS_WINDOWS', False),              mock.patch.object(ps, 'IS_MAC', False),              mock.patch.object(ps, 'IS_LINUX', True),              mock.patch.object(ps.Path, 'home', return_value=Path(tmp)),              mock.patch.dict(os.environ, {'XDG_DATA_HOME': str(Path(tmp) / 'xdg')}, clear=False):
            base = Path(tmp) / 'xdg'
            self.assertEqual(ps.app_data_dir(), base / 'computer-controller')
            legacy = base / 'mac-bridge'
            legacy.mkdir(parents=True)
            self.assertEqual(ps.app_data_dir(), legacy)
            current = base / 'computer-controller'
            current.mkdir()
            self.assertEqual(ps.app_data_dir(), current)

    def test_linux_shell_does_not_require_zsh(self):
        workspace = Path('/tmp/computer-controller-project')
        with mock.patch.object(ps, 'IS_WINDOWS', False),              mock.patch.object(ps, 'IS_MAC', False),              mock.patch.object(ps, 'IS_LINUX', True),              mock.patch.object(ps.Path, 'home', return_value=Path('/home/tester')),              mock.patch.object(ps.Path, 'is_file', autospec=True, return_value=True):
            wrapped, engine_shell = ps.shell_command(workspace, 'printf ok')
        self.assertEqual(engine_shell, '/bin/sh')
        self.assertIn('/bin/bash --noprofile --norc -c', wrapped)
        self.assertNotIn('/bin/zsh', wrapped)

    def test_linux_browser_defaults_to_dedicated_headless(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sys, 'platform', 'linux'):
            value = bc.browser_settings(Path(tmp))
        self.assertEqual(value, {'schema': 2, 'mode': 'dedicated', 'headless': True})

    def test_linux_personal_browser_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sys, 'platform', 'linux'):
            with self.assertRaisesRegex(Exception, 'dedicated mode'):
                bc.set_browser_mode(Path(tmp), 'personal')

    def test_linux_runtime_key_file_is_private_and_tunnel_bound(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(credentials, 'IS_LINUX', True):
            root = Path(tmp)
            credentials.set_runtime_key(root, 'tunnel_abcdefgh', 'secret-value')
            path = root / '.state/runtime-key.json'
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            raw = json.loads(path.read_text())
            self.assertEqual(raw['tunnel_id'], 'tunnel_abcdefgh')
            self.assertEqual(credentials.get_runtime_key(root, 'tunnel_abcdefgh'), 'secret-value')
            with self.assertRaisesRegex(Exception, 'does not match'):
                credentials.get_runtime_key(root, 'tunnel_other123')

    def test_runtime_key_env_override_works_without_file(self):
        with tempfile.TemporaryDirectory() as tmp,              mock.patch.object(credentials, 'IS_LINUX', True),              mock.patch.dict(os.environ, {'CONTROL_PLANE_API_KEY': 'env-secret'}, clear=False):
            self.assertEqual(credentials.get_runtime_key(Path(tmp), 'tunnel_abcdefgh'), 'env-secret')


if __name__ == '__main__':
    unittest.main()
